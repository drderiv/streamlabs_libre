"""StreamLabs API Client using AWS Cognito SRP Authentication.

Copyright 2026 StreamLabs Libre Contributors.
Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any, Final

from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pycognito import Cognito
from pycognito.exceptions import ForceChangePasswordException, SoftwareTokenMFAChallengeException
import requests

from .const import (
    BASE_URL,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
    COGNITO_USER_POOL_ID,
    Mode,
    ValvePosition,
)

_LOGGER = logging.getLogger(__name__)

# Cognito error codes that mean the credentials themselves are bad
_AUTH_ERROR_CODES: Final = frozenset(
    {
        "NotAuthorizedException",
        "UserNotFoundException",
        "UserNotConfirmedException",
        "PasswordResetRequiredException",
    }
)
# Fallback ID-token lifetime and safety margin, in seconds
_DEFAULT_TOKEN_LIFETIME: Final = 3500
_TOKEN_EXPIRY_SKEW: Final = 60


class StreamLabsError(Exception):
    """Base exception for StreamLabs client."""


class StreamLabsAuthError(StreamLabsError):
    """Authentication failed."""


class StreamLabsConnectionError(StreamLabsError):
    """Connection or communication error."""


class StreamLabsDeviceNotFoundError(StreamLabsError):
    """Requested device was not found."""


def extract_reading_value(val: Any) -> float | None:
    """Extract a numeric reading value from API response or nested TooLowTooHigh object.

    StreamLabs returns sentinels <= -1000 (such as -10000) when a sensor reading is
    unavailable, erroneous, or not supported by the hardware model.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        num = float(val)
        return None if num <= -1000 else num
    if isinstance(val, dict):
        for key in ("currentValue", "iCurrentValue", "value"):
            if key in val and val[key] is not None:
                try:
                    num = float(val[key])
                    return None if num <= -1000 else num
                except (ValueError, TypeError):
                    pass
    return None


class StreamLabsClient:
    """Client for StreamLabs water monitor and shutoff hardware.

    Blocking (``requests`` / pycognito); call from an executor thread. All public
    methods are safe to call from several threads concurrently.
    """

    def __init__(
        self,
        username: str,
        password: str,
        session: requests.Session | None = None,
    ) -> None:
        """Initialize the client."""
        self.username = username
        self.password = password
        self.cognito = Cognito(
            user_pool_id=COGNITO_USER_POOL_ID,
            client_id=COGNITO_CLIENT_ID,
            user_pool_region=COGNITO_REGION,
            username=self.username,
            boto3_client_kwargs={"config": Config(signature_version=UNSIGNED)},
        )
        self.token_expiry: float = 0.0
        self.session = session or requests.Session()
        self._lock = threading.RLock()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    @staticmethod
    def _token_expiry(token: str | None, now: float) -> float:
        """Return the expiry of a JWT (minus a safety skew), or a default lifetime."""
        try:
            payload = token.split(".")[1]  # type: ignore[union-attr]
            payload += "=" * (-len(payload) % 4)
            exp = float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
            return exp - _TOKEN_EXPIRY_SKEW
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return now + _DEFAULT_TOKEN_LIFETIME

    def _ensure_authenticated(self) -> str:
        """Maintain Cognito ID Token validity with SRP authentication and refresh.

        Returns the current ID token.
        """
        with self._lock:
            now = time.time()
            try:
                if not self.cognito.id_token:
                    _LOGGER.debug("Authenticating with AWS Cognito")
                    self.cognito.authenticate(password=self.password)
                    self.token_expiry = self._token_expiry(self.cognito.id_token, now)
                elif now >= self.token_expiry:
                    _LOGGER.debug("Renewing expired AWS Cognito ID token")
                    try:
                        self.cognito.renew_id_token()
                    except (ClientError, BotoCoreError) as renew_err:
                        _LOGGER.info("Token renewal failed (%s), performing full re-authentication", renew_err)
                        self.cognito.authenticate(password=self.password)
                    self.token_expiry = self._token_expiry(self.cognito.id_token, now)
            except (ForceChangePasswordException, SoftwareTokenMFAChallengeException) as err:
                raise StreamLabsAuthError(f"Cognito challenge required: {err}") from err
            except ClientError as err:
                if err.response.get("Error", {}).get("Code") in _AUTH_ERROR_CODES:
                    raise StreamLabsAuthError("Invalid StreamLabs credentials") from err
                raise StreamLabsConnectionError(f"Cognito error: {err}") from err
            except BotoCoreError as err:
                raise StreamLabsConnectionError(f"Cannot reach StreamLabs authentication: {err}") from err
            return self.cognito.id_token

    def _invalidate_token(self) -> None:
        """Force a fresh authentication on the next request."""
        with self._lock:
            self.cognito.id_token = None

    def _validate_response(self, resp: requests.Response) -> Any:
        """Validate HTTP response and detect error payloads disguised as HTTP 200."""
        if resp.status_code in (401, 403):
            raise StreamLabsAuthError(f"HTTP {resp.status_code} from StreamLabs API")
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            raise StreamLabsConnectionError(f"HTTP request failed ({resp.status_code}): {err}") from err

        if resp.status_code in (202, 204) or not resp.content:
            return {}

        try:
            data = resp.json()
        except ValueError as err:
            raise StreamLabsConnectionError(f"Invalid JSON response from StreamLabs API: {err}") from err

        if isinstance(data, dict):
            if "error" in data:
                err_msg = data.get("error_description") or data.get("message") or data.get("error")
                raise StreamLabsError(f"StreamLabs API returned error payload: {err_msg}")
            if "errors" in data and isinstance(data["errors"], list) and data["errors"]:
                err_msg = (
                    data["errors"][0].get("message")
                    if isinstance(data["errors"][0], dict)
                    else str(data["errors"][0])
                )
                raise StreamLabsError(f"StreamLabs API returned error payload: {err_msg}")
            if "code" in data and str(data.get("code")).lower() not in ("200", "ok", "0"):
                err_msg = data.get("message") or data.get("description") or f"Error code {data['code']}"
                raise StreamLabsError(f"StreamLabs API error ({data['code']}): {err_msg}")
            if "statusCode" in data and str(data.get("statusCode")) not in ("200", "0"):
                err_msg = data.get("message") or f"Status code {data['statusCode']}"
                raise StreamLabsError(f"StreamLabs API error ({data['statusCode']}): {err_msg}")
            if data.get("ErrorMessage") and str(data.get("ReturnCode", "1")) not in ("0", "200"):
                raise StreamLabsError(f"StreamLabs API error: {data['ErrorMessage']}")

        return data

    def _request(self, method: str, path: str, what: str, *, timeout: int = 15, **kwargs: Any) -> requests.Response:
        """Perform an authenticated request, retrying once if the token was rejected."""
        for attempt in (1, 2):
            token = self._ensure_authenticated()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                resp = self.session.request(
                    method, f"{BASE_URL}{path}", headers=headers, timeout=timeout, **kwargs
                )
            except requests.RequestException as err:
                raise StreamLabsConnectionError(f"Failed to {what}: {err}") from err
            if resp.status_code in (401, 403) and attempt == 1:
                self._invalidate_token()
                continue
            return resp
        raise AssertionError("unreachable")  # pragma: no cover

    def _get_dict(self, path: str, what: str, **kwargs: Any) -> dict[str, Any]:
        """GET a JSON object."""
        data = self._validate_response(self._request("GET", path, what, **kwargs))
        return data if isinstance(data, dict) else {}

    def _send(self, method: str, path: str, what: str, payload: dict[str, Any], *, timeout: int = 15) -> bool:
        """Send a JSON payload and report whether the API accepted it."""
        resp = self._request(method, path, what, timeout=timeout, json=payload)
        self._validate_response(resp)
        return resp.status_code in (200, 204)

    def get_locations(self) -> dict[str, Any]:
        """Fetch the full locations hierarchy."""
        return self._get_dict("/locations", "fetch locations")

    def get_status(self, device_id: str | None = None) -> dict[str, Any]:
        """Poll locations and return flattened status objects suitable for Home Assistant."""
        data = self.get_locations()
        devices: list[dict[str, Any]] = []

        for loc in data.get("locations", []):
            raw_loc_id = loc.get("locationId") or loc.get("location_id") or loc.get("id")
            loc_id = str(raw_loc_id) if raw_loc_id is not None else None
            loc_name = loc.get("locationName") or loc.get("name")
            gallons_today = loc.get("gallonsToday")

            for dev in loc.get("devices", []):
                valve = dev.get("valve")
                item = {
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "device_id": dev.get("deviceId"),
                    "device_name": dev.get("deviceName"),
                    "connected": dev.get("connected", False),
                    "flowing": dev.get("flowing", False),
                    "mode": dev.get("mode", Mode.HOME),
                    "has_valve": "valve" in dev,
                    "valve_position": valve.get("position") if isinstance(valve, dict) else None,
                    "gallons_today": gallons_today,
                    "ambient_temp": dev.get("ambientTemp"),
                    "humidity": dev.get("humidity"),
                    "water_pressure": dev.get("waterPressure"),
                    "water_temp": dev.get("waterTemp"),
                }
                if device_id and dev.get("deviceId") == device_id:
                    return item
                devices.append(item)

        if device_id:
            raise StreamLabsDeviceNotFoundError(f"Device ID '{device_id}' was not found in account.")

        locations_summary = []
        for loc in data.get("locations", []):
            if not isinstance(loc, dict):
                continue
            raw_loc_id = loc.get("locationId") or loc.get("location_id") or loc.get("id")
            locations_summary.append(
                {
                    "location_id": str(raw_loc_id) if raw_loc_id is not None else None,
                    "location_name": loc.get("locationName") or loc.get("name"),
                    "device_ids": [d.get("deviceId") for d in loc.get("devices", []) if isinstance(d, dict)],
                }
            )

        return {"devices": devices, "locations_summary": locations_summary}

    def get_device(self, device_id: str) -> dict[str, Any]:
        """Fetch detailed device telemetry and settings (GET /devices/{deviceId})."""
        return self._get_dict(f"/devices/{device_id}", f"fetch device {device_id}")

    def set_valve(self, device_id: str, target_position: ValvePosition | str) -> bool:
        """Actuate the water shutoff valve ('set valve' command)."""
        if target_position not in tuple(ValvePosition):
            raise ValueError(f"Invalid valve position: {target_position}")
        payload = {"command": "set valve", "parameters": {"position": str(target_position)}}
        return self._send("POST", f"/devices/{device_id}/command", "actuate valve", payload, timeout=20)

    def set_mode(self, device_id: str, mode: Mode | str) -> bool:
        """Update the monitoring mode (PUT /devices/{deviceId}/settings)."""
        if mode not in tuple(Mode):
            raise ValueError(f"Invalid mode: {mode}")
        return self._send("PUT", f"/devices/{device_id}/settings", "update monitoring mode", {"mode": str(mode)})

    def get_water_usage(
        self,
        device_id: str,
        date_str: str | None = None,
        period: str | None = None,
        rolling: bool | None = None,
    ) -> dict[str, Any]:
        """Retrieve volumetric water consumption (comparative totals, or rolling history)."""
        path = f"/devices/{device_id}/water/{period}" if period else f"/devices/{device_id}/water"
        params: dict[str, Any] = {}
        if date_str:
            params["date"] = date_str
        if rolling is not None:
            params["rolling"] = "true" if rolling else "false"
        return self._get_dict(path, "fetch water usage", params=params or None)

    def get_water_usage_history(self, device_id: str, period: str, rolling: bool = True) -> dict[str, Any]:
        """Retrieve time-series water usage history (e.g. past 13 months rolling total for year)."""
        return self.get_water_usage(device_id, period=period, rolling=rolling)

    def send_command(
        self,
        device_id: str,
        command: str,
        parameters: dict[str, Any] | None = None,
    ) -> bool:
        """Send an arbitrary command to the device (e.g. 'run drip detect', 'calibrate')."""
        payload: dict[str, Any] = {"command": command}
        if parameters:
            payload["parameters"] = parameters
        return self._send("POST", f"/devices/{device_id}/command", f"execute command '{command}'", payload, timeout=20)
