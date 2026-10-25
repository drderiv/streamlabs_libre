"""Coordinator for StreamLabs Libre integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any, NamedTuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    StreamLabsAuthError,
    StreamLabsClient,
    StreamLabsError,
    extract_reading_value,
)
from .const import (
    CONF_LOCATIONS,
    CONF_SCAN_INTERVAL,
    CONF_WATER_OFF_INTERVAL,
    CONF_WATER_ON_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WATER_OFF_INTERVAL,
    DEFAULT_WATER_ON_INTERVAL,
    DOMAIN,
    MAX_STALE_POLLS,
    YEARLY_CACHE_INTERVAL,
    Mode,
)
from .flow import FlowRateEstimator
from .parsing import extract_usage, first_present, parse_year_history

_LOGGER = logging.getLogger(__name__)

type StreamlabsConfigEntry = ConfigEntry[StreamlabsCoordinator]


@dataclass(frozen=True, slots=True)
class StreamLabsDeviceData:
    """Device-level StreamLabs data."""

    device_id: str
    device_name: str
    location_id: str
    location_name: str
    connected: bool
    flowing: bool
    mode: str
    has_valve: bool
    valve_position: str | None
    daily_usage: float
    monthly_usage: float
    yearly_usage: float
    estimated_flow_rate: float = 0.0
    room_temp: float | None = None
    room_humidity: float | None = None
    water_pressure: float | None = None
    water_temp: float | None = None
    yearly_used_since: str | None = None
    monthly_history: list[float] | None = None


class FetchResult(NamedTuple):
    """Everything one blocking poll produces; applied to coordinator state on the loop."""

    devices: dict[str, StreamLabsDeviceData]
    locations: dict[str, str]
    api_device_count: int


def _get_interval(
    options: Mapping[str, Any], data: Mapping[str, Any], key: str, default: Any
) -> int:
    try:
        return int(options.get(key, data.get(key, default)))
    except (TypeError, ValueError):
        return int(default)


class StreamlabsCoordinator(DataUpdateCoordinator[dict[str, StreamLabsDeviceData]]):
    """Data update coordinator for StreamLabs Libre."""

    config_entry: StreamlabsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: StreamlabsConfigEntry,
        client: StreamLabsClient,
    ) -> None:
        """Initialize the coordinator."""
        options = config_entry.options
        data = config_entry.data

        legacy_interval = options.get(
            CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self.scan_interval_off = _get_interval(
            options, data, CONF_WATER_OFF_INTERVAL, legacy_interval
        )
        self.scan_interval_on = _get_interval(
            options, data, CONF_WATER_ON_INTERVAL, DEFAULT_WATER_ON_INTERVAL
        )
        if self.scan_interval_off <= 0:
            self.scan_interval_off = DEFAULT_WATER_OFF_INTERVAL
        if self.scan_interval_on <= 0:
            self.scan_interval_on = DEFAULT_WATER_ON_INTERVAL

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="StreamLabs Libre",
            update_interval=timedelta(seconds=self.scan_interval_off),
        )
        self.client = client

        self.monitored_locations: set[str] | None = None
        locations_cfg = options.get(CONF_LOCATIONS, data.get(CONF_LOCATIONS))
        if locations_cfg is not None:
            self.monitored_locations = {str(x) for x in locations_cfg}

        # Every location on the account (id -> name), refreshed on each poll
        self.known_locations: dict[str, str] = {}

        # Caches below are only touched from the executor thread running _fetch
        self._yearly_cache: dict[str, dict[str, Any]] = {}
        self._telemetry_cache: dict[str, dict[str, Any]] = {}
        self._flow: dict[str, FlowRateEstimator] = {}
        self._logged_device_monitoring: dict[str, bool] = {}

        # Last known good device state, served for a few polls during outages
        self._cached_devices: dict[str, StreamLabsDeviceData] = {}
        self._consecutive_failures = 0

    async def async_client_call[**P, T](
        self, func: Callable[P, T], *args: P.args
    ) -> T:
        """Run a blocking client call, translating failures to HomeAssistantError."""
        try:
            return await self.hass.async_add_executor_job(func, *args)
        except StreamLabsAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except StreamLabsError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> dict[str, StreamLabsDeviceData]:
        """Fetch latest data, tolerating short outages by serving the last known state."""
        try:
            result = await self.hass.async_add_executor_job(self._fetch)
        except StreamLabsAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except StreamLabsError as err:
            return self._handle_failure(err)

        # An empty account-wide device list after we had devices is treated as a glitch
        if result.api_device_count == 0 and self._cached_devices:
            return self._handle_failure(StreamLabsError("API returned an empty device list"))

        if self._consecutive_failures:
            _LOGGER.info(
                "StreamLabs cloud connection restored after %d failed attempt(s)",
                self._consecutive_failures,
            )
            self._consecutive_failures = 0

        self.known_locations = result.locations
        self._cached_devices = result.devices
        self._set_poll_interval(any(d.flowing for d in result.devices.values()))
        return dict(result.devices)

    def _handle_failure(self, err: StreamLabsError) -> dict[str, StreamLabsDeviceData]:
        """Serve cached state for a bounded number of failed polls, then fail."""
        self._consecutive_failures += 1
        # Back off to the slow interval during outages to avoid hammering upstream
        self.update_interval = timedelta(seconds=self.scan_interval_off)

        if self._cached_devices and self._consecutive_failures <= MAX_STALE_POLLS:
            log = _LOGGER.warning if self._consecutive_failures == 1 else _LOGGER.debug
            log(
                "Error communicating with StreamLabs API (attempt %d), "
                "serving last known state: %s",
                self._consecutive_failures,
                err,
            )
            return dict(self._cached_devices)

        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    def _set_poll_interval(self, any_flowing: bool) -> None:
        """Poll quickly while water is flowing, slowly otherwise."""
        target = timedelta(
            seconds=self.scan_interval_on if any_flowing else self.scan_interval_off
        )
        if self.update_interval != target:
            self.update_interval = target
            _LOGGER.debug("Adjusted polling interval to %s (flowing=%s)", target, any_flowing)

    # ------------------------------------------------- blocking fetch (executor)

    def _fetch(self) -> FetchResult:
        """Synchronously poll the API. Must not touch event-loop state."""
        status = self.client.get_status()
        raw_devices: list[dict[str, Any]] = status.get("devices", [])
        locations = {
            str(loc["location_id"]): loc.get("location_name") or f"Location {loc['location_id']}"
            for loc in status.get("locations_summary", [])
            if loc.get("location_id")
        }

        devices: dict[str, StreamLabsDeviceData] = {}
        now_mono = time.monotonic()
        for dev in raw_devices:
            if not (device_id := dev.get("device_id")):
                continue
            loc_id = str(dev["location_id"]) if dev.get("location_id") is not None else None
            if not self._is_monitored(dev, device_id, loc_id):
                continue
            devices[device_id] = self._build_device(dev, loc_id, now_mono)

        return FetchResult(devices, locations, len(raw_devices))

    def _is_monitored(self, dev: Mapping[str, Any], device_id: str, loc_id: str | None) -> bool:
        """Return whether a device is monitored, logging each change in status once."""
        monitored = self.monitored_locations is None or (
            loc_id is not None and loc_id in self.monitored_locations
        )
        if self._logged_device_monitoring.get(device_id) != monitored:
            self._logged_device_monitoring[device_id] = monitored
            _LOGGER.info(
                "%s StreamLabs device %s ('%s') at location %s ('%s')",
                "Including monitored" if monitored else "Skipping unmonitored",
                device_id,
                dev.get("device_name"),
                loc_id,
                dev.get("location_name"),
            )
        return monitored

    def _build_device(
        self, dev: Mapping[str, Any], loc_id: str | None, now_mono: float
    ) -> StreamLabsDeviceData:
        """Assemble one device's data from the status row plus auxiliary endpoints."""
        device_id: str = dev["device_id"]
        prev = self._cached_devices.get(device_id)

        daily, monthly, yearly = self._fetch_usage(device_id, prev)
        history, used_since = self._yearly_history(device_id, monthly, now_mono)
        if history:
            if (total := sum(history)) > 0:
                yearly = round(total, 1)
        else:
            history = prev.monthly_history if prev else None
            used_since = prev.yearly_used_since if prev else None

        # Fall back to the location-level figure if per-device usage is unavailable
        gallons_today = float(dev.get("gallons_today") or 0.0)
        if daily == 0.0 and gallons_today > 0.0:
            daily = gallons_today

        detail = self._fetch_telemetry(device_id, now_mono)
        is_flowing = bool(dev.get("flowing", False))
        flow_rate = self._flow.setdefault(device_id, FlowRateEstimator()).update(
            is_flowing, daily, now_mono
        )

        settings = detail.get("settings")
        valve = detail.get("valve")
        mode = (
            detail.get("mode")
            or (settings.get("mode") if isinstance(settings, dict) else None)
            or dev.get("mode")
            or Mode.HOME
        )
        valve_position = (valve.get("position") if isinstance(valve, dict) else None) or dev.get(
            "valve_position"
        )

        return StreamLabsDeviceData(
            device_id=device_id,
            device_name=dev.get("device_name") or f"StreamLabs {device_id}",
            location_id=loc_id or "unknown",
            location_name=dev.get("location_name") or "StreamLabs Location",
            connected=bool(dev.get("connected", True)),
            flowing=is_flowing,
            mode=str(mode),
            has_valve=bool(dev.get("has_valve", False)),
            valve_position=valve_position,
            daily_usage=daily,
            monthly_usage=monthly,
            yearly_usage=yearly,
            estimated_flow_rate=flow_rate,
            room_temp=extract_reading_value(
                first_present(detail, dev, keys=("ambientTemp", "ambient_temp", "roomTemp"))
            ),
            room_humidity=extract_reading_value(
                first_present(detail, dev, keys=("humidity", "roomHumidity"))
            ),
            water_pressure=extract_reading_value(
                first_present(detail, dev, keys=("waterPressure", "water_pressure", "pressure"))
            ),
            water_temp=extract_reading_value(
                first_present(detail, dev, keys=("waterTemp", "water_temp"))
            ),
            yearly_used_since=used_since,
            monthly_history=history,
        )

    def _fetch_usage(
        self, device_id: str, prev: StreamLabsDeviceData | None
    ) -> tuple[float, float, float]:
        """Fetch daily/monthly/yearly usage, retaining the previous values on failure."""
        daily = prev.daily_usage if prev else 0.0
        monthly = prev.monthly_usage if prev else 0.0
        yearly = prev.yearly_usage if prev else 0.0
        try:
            d, m, y = extract_usage(self.client.get_water_usage(device_id))
        except StreamLabsAuthError:
            raise
        except StreamLabsError as err:
            _LOGGER.debug(
                "Could not fetch detailed water usage for device %s (retaining cached usage): %s",
                device_id,
                err,
            )
        else:
            if d > 0 or m > 0 or y > 0:
                daily, monthly, yearly = d, m, y
        return daily, monthly, yearly

    def _yearly_history(
        self, device_id: str, monthly_usage: float, now_mono: float
    ) -> tuple[list[float] | None, str | None]:
        """Return the rolling 13-month history and its "used since" label.

        The mobile app gets these from GET /devices/{id}/water/{yyyy}?rolling=true. To
        minimise requests it is polled once per YEARLY_CACHE_INTERVAL; between polls the
        newest month is overwritten with the live monthly total.
        """
        cached = self._yearly_cache.get(device_id)
        if cached is None or now_mono - cached["last_fetched"] >= YEARLY_CACHE_INTERVAL:
            now = dt_util.now()
            try:
                parsed = parse_year_history(
                    self.client.get_water_usage(device_id, period=str(now.year), rolling=True),
                    now,
                )
            except StreamLabsAuthError:
                raise
            except StreamLabsError as err:
                _LOGGER.debug("Could not fetch rolling yearly water usage for device %s: %s", device_id, err)
                parsed = None
            if parsed:
                values, used_since = parsed
                cached = {"last_fetched": now_mono, "monthly_history": values, "used_since": used_since}
            elif cached is None:
                # Back off the auxiliary fetch so it doesn't starve routine polling
                cached = {"last_fetched": now_mono}
            else:
                cached["last_fetched"] = now_mono
            self._yearly_cache[device_id] = cached

        history = cached.get("monthly_history")
        if not history:
            return None, None
        if monthly_usage > 0:
            history[-1] = monthly_usage
        return list(history), cached.get("used_since")

    def _fetch_telemetry(self, device_id: str, now_mono: float) -> dict[str, Any]:
        """Fetch device detail, cached for the water-off interval."""
        cached = self._telemetry_cache.get(device_id)
        if cached is not None and now_mono - cached["last_fetched"] < self.scan_interval_off:
            return cached["data"]
        try:
            data = self.client.get_device(device_id)
        except StreamLabsAuthError:
            raise
        except StreamLabsError as err:
            _LOGGER.debug("Could not fetch detailed telemetry for device %s: %s", device_id, err)
            # Keep the last good data and back off so rapid water-on polls don't retry
            data = cached["data"] if cached else {}
        self._telemetry_cache[device_id] = {"last_fetched": now_mono, "data": data}
        return data
