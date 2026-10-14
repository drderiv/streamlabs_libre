"""StreamLabs API Client using AWS Cognito SRP Authentication.

Copyright 2026 StreamLabs Libre Contributors.
Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Dict, List, Literal, Optional
import requests
from botocore import UNSIGNED
from botocore.config import Config
from pycognito import Cognito
from pycognito.exceptions import ForceChangePasswordException, SoftwareTokenMFAChallengeException

from .const import (
    BASE_URL,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
    COGNITO_USER_POOL_ID,
    VALVE_CLOSE,
    VALVE_OPEN,
)

_LOGGER = logging.getLogger(__name__)


class StreamLabsError(Exception):
    """Base exception for StreamLabs client."""


class StreamLabsAuthError(StreamLabsError):
    """Authentication failed."""


class StreamLabsConnectionError(StreamLabsError):
    """Connection or communication error."""


class StreamLabsDeviceNotFoundError(StreamLabsError):
    """Requested device was not found."""


def extract_reading_value(val: Any) -> Optional[float]:
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
    """Client for StreamLabs water monitor and shutoff hardware."""

    def __init__(
        self,
        username: str,
        password: str,
        session: Optional[requests.Session] = None,
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

    def _ensure_authenticated(self) -> None:
        """Maintain Cognito ID Token validity with SRP authentication and refresh."""
        now = time.time()
        try:
            if not self.cognito.id_token:
                _LOGGER.debug("Authenticating with AWS Cognito for user %s", self.username)
                self.cognito.authenticate(password=self.password)
                self.token_expiry = now + 3500
            elif now >= self.token_expiry:
                _LOGGER.debug("Renewing expired AWS Cognito ID token for user %s", self.username)
                try:
                    self.cognito.renew_id_token()
                except Exception as renew_err:
                    _LOGGER.info("Token renewal failed (%s), performing full re-authentication", renew_err)
                    self.cognito.authenticate(password=self.password)
                self.token_expiry = now + 3500
        except (ForceChangePasswordException, SoftwareTokenMFAChallengeException) as err:
            raise StreamLabsAuthError(f"Cognito challenge required: {err}") from err
        except Exception as err:
            _LOGGER.error("Cognito authentication failed: %s", err)
            raise StreamLabsAuthError(f"Failed to authenticate with StreamLabs: {err}") from err

        self.session.headers.update({
            "Authorization": f"Bearer {self.cognito.id_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def get_locations(self) -> Dict[str, Any]:
        """Fetch the full locations hierarchy."""
        self._ensure_authenticated()
        try:
            resp = self.session.get(f"{BASE_URL}/locations", timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            raise StreamLabsConnectionError(f"Failed to fetch locations: {err}") from err

    def get_status(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Poll locations and return flattened status objects suitable for Home Assistant.
        """
        data = self.get_locations()
        devices: List[Dict[str, Any]] = []

        for loc in data.get("locations", []):
            loc_id = loc.get("locationId")
            loc_name = loc.get("locationName")
            gallons_today = loc.get("gallonsToday")

            for dev in loc.get("devices", []):
                item = {
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "device_id": dev.get("deviceId"),
                    "device_name": dev.get("deviceName"),
                    "connected": dev.get("connected", False),
                    "flowing": dev.get("flowing", False),
                    "mode": dev.get("mode", "home"),
                    "has_valve": "valve" in dev or dev.get("valve") is not None,
                    "valve_position": dev.get("valve", {}).get("position") if dev.get("valve") else None,
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
        return {"devices": devices}

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Fetch detailed device telemetry and settings.
        Wire Route: GET /devices/{deviceId}
        """
        self._ensure_authenticated()
        url = f"{BASE_URL}/devices/{device_id}"
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            raise StreamLabsConnectionError(f"Failed to fetch device {device_id}: {err}") from err

    def set_valve(self, device_id: str, target_position: Literal["open", "close"]) -> bool:
        """
        Actuates the water shutoff valve.
        Wire Command: 'set valve' with parameters {'position': 'open'|'close'}
        """
        if target_position not in (VALVE_OPEN, VALVE_CLOSE):
            raise ValueError(f"Invalid valve position: {target_position}")

        self._ensure_authenticated()
        url = f"{BASE_URL}/devices/{device_id}/command"
        payload = {
            "command": "set valve",
            "parameters": {
                "position": target_position
            }
        }
        try:
            resp = self.session.post(url, json=payload, timeout=20)
            resp.raise_for_status()
            return resp.status_code in (200, 204)
        except requests.RequestException as err:
            raise StreamLabsConnectionError(f"Failed to actuate valve: {err}") from err

    def set_mode(self, device_id: str, mode: Literal["home", "away"]) -> bool:
        """
        Updates the monitoring mode (Home/Away).
        Wire Route: PUT /devices/{deviceId}/settings with payload {'mode': 'home'|'away'}
        """
        if mode not in ("home", "away"):
            raise ValueError(f"Invalid mode: {mode}")

        self._ensure_authenticated()
        url = f"{BASE_URL}/devices/{device_id}/settings"
        payload = {"mode": mode}
        try:
            resp = self.session.put(url, json=payload, timeout=15)
            resp.raise_for_status()
            return resp.status_code in (200, 204)
        except requests.RequestException as err:
            raise StreamLabsConnectionError(f"Failed to update monitoring mode: {err}") from err

    def get_water_usage(
        self,
        device_id: str,
        date_str: Optional[str] = None,
        period: Optional[str] = None,
        rolling: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Retrieve volumetric water consumption (comparative day, week, month, year totals, or rolling history)."""
        self._ensure_authenticated()
        if period:
            url = f"{BASE_URL}/devices/{device_id}/water/{period}"
        else:
            url = f"{BASE_URL}/devices/{device_id}/water"

        params: Dict[str, Any] = {}
        if date_str:
            params["date"] = date_str
        if rolling is not None:
            params["rolling"] = "true" if rolling else "false"

        try:
            resp = self.session.get(url, params=params or None, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            raise StreamLabsConnectionError(f"Failed to fetch water usage: {err}") from err

    def get_water_usage_history(
        self,
        device_id: str,
        period: str,
        rolling: bool = True,
    ) -> Dict[str, Any]:
        """Retrieve time-series water usage history (e.g. past 13 months rolling total for year)."""
        return self.get_water_usage(device_id, period=period, rolling=rolling)


    def send_command(
        self,
        device_id: str,
        command: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send an arbitrary command to the device (e.g. 'run drip detect', 'calibrate').
        """
        self._ensure_authenticated()
        url = f"{BASE_URL}/devices/{device_id}/command"
        payload: Dict[str, Any] = {"command": command}
        if parameters:
            payload["parameters"] = parameters

        try:
            resp = self.session.post(url, json=payload, timeout=20)
            resp.raise_for_status()
            return resp.status_code in (200, 204)
        except requests.RequestException as err:
            raise StreamLabsConnectionError(f"Failed to execute command '{command}': {err}") from err
