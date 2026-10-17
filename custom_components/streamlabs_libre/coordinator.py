"""Coordinator for StreamLabs Libre integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import StreamLabsClient, StreamLabsError, extract_reading_value
from .const import (
    CONF_LOCATIONS,
    CONF_SCAN_INTERVAL,
    CONF_WATER_OFF_INTERVAL,
    CONF_WATER_ON_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WATER_OFF_INTERVAL,
    DEFAULT_WATER_ON_INTERVAL,
    DOMAIN,
    LOGGER,
    YEARLY_CACHE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)



@dataclass(slots=True)
class StreamLabsDeviceData:
    """Class to hold device-level StreamLabs data."""

    device_id: str
    device_name: str
    location_id: str
    location_name: str
    connected: bool
    flowing: bool
    mode: str
    has_valve: bool
    valve_position: Optional[str]
    daily_usage: float
    monthly_usage: float
    yearly_usage: float
    gallons_today: float
    raw_status: Dict[str, Any]
    estimated_flow_rate: float = 0.0
    room_temp: Optional[float] = None
    room_humidity: Optional[float] = None
    water_pressure: Optional[float] = None
    water_temp: Optional[float] = None
    yearly_used_since: Optional[str] = None
    monthly_history: Optional[List[float]] = None



type StreamlabsConfigEntry = ConfigEntry[StreamlabsCoordinator]


class StreamlabsCoordinator(DataUpdateCoordinator[Dict[str, StreamLabsDeviceData]]):
    """Data update coordinator for StreamLabs Libre."""

    config_entry: StreamlabsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: StreamlabsConfigEntry,
        client: StreamLabsClient,
    ) -> None:
        """Initialize the coordinator."""
        raw_options = getattr(config_entry, "options", None)
        options = raw_options if isinstance(raw_options, dict) else {}
        raw_data = getattr(config_entry, "data", None)
        data = raw_data if isinstance(raw_data, dict) else {}

        legacy_interval = options.get(
            CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        try:
            self.scan_interval_off = int(
                options.get(
                    CONF_WATER_OFF_INTERVAL,
                    data.get(CONF_WATER_OFF_INTERVAL, legacy_interval),
                )
            )
        except (ValueError, TypeError):
            self.scan_interval_off = DEFAULT_WATER_OFF_INTERVAL

        try:
            self.scan_interval_on = int(
                options.get(
                    CONF_WATER_ON_INTERVAL,
                    data.get(CONF_WATER_ON_INTERVAL, DEFAULT_WATER_ON_INTERVAL),
                )
            )
        except (ValueError, TypeError):
            self.scan_interval_on = DEFAULT_WATER_ON_INTERVAL

        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name="StreamLabs Libre",
            update_interval=timedelta(seconds=self.scan_interval_off),
        )
        self.client = client
        self.monitored_locations: Optional[Set[str]] = None
        locations_cfg = options.get(CONF_LOCATIONS, data.get(CONF_LOCATIONS))
        if locations_cfg is not None:
            self.monitored_locations = {str(x) for x in locations_cfg}
        else:
            # Check if user already has a subset of devices registered in Home Assistant
            try:
                from homeassistant.helpers import device_registry as dr
                dev_reg = dr.async_get(hass)
                existing_entries = dr.async_entries_for_config_entry(dev_reg, config_entry.entry_id)
                registered_dev_ids = {
                    dev_id for dev_entry in existing_entries
                    for domain, dev_id in dev_entry.identifiers
                    if domain == DOMAIN
                }
                self._registered_device_ids: Optional[Set[str]] = registered_dev_ids if registered_dev_ids else None
            except Exception:
                self._registered_device_ids = None
        self._yearly_cache: Dict[str, Dict[str, Any]] = {}
        self._telemetry_cache: Dict[str, Dict[str, Any]] = {}
        self._flow_tracking: Dict[str, Dict[str, Any]] = {}

        self._pending_options_update: Optional[Dict[str, Any]] = None

        # Cached device state dictionary to preserve last known valid state across outages
        self._cached_devices: Dict[str, StreamLabsDeviceData] = {}

        # Outage and log throttling tracking
        self._consecutive_failures: int = 0

    async def _async_update_data(self) -> Dict[str, StreamLabsDeviceData]:
        """Fetch latest data from StreamLabs with outage resilience and state preservation."""
        fetch_error: Optional[Exception] = None
        devices_data: Dict[str, StreamLabsDeviceData] = {}

        try:
            devices_data = await self.hass.async_add_executor_job(self._update_data)
        except Exception as err:
            fetch_error = err

        if getattr(self, "_pending_options_update", None):
            opts_to_update = self._pending_options_update
            self._pending_options_update = None
            try:
                self.hass.config_entries.async_update_entry(self.config_entry, options=opts_to_update)
            except Exception as err:
                LOGGER.debug("Could not persist auto-detected locations: %s", err)

        # Handle upstream outage or communication failure
        if fetch_error is not None:
            self._consecutive_failures += 1
            if self._consecutive_failures <= 3:
                LOGGER.warning(
                    "Error communicating with StreamLabs API (attempt %d): %s",
                    self._consecutive_failures,
                    fetch_error,
                )
            else:
                LOGGER.debug(
                    "StreamLabs API outage ongoing (attempt %d): %s",
                    self._consecutive_failures,
                    fetch_error,
                )

            # Revert to water_off polling interval during outages to prevent hammering upstream
            self.update_interval = timedelta(seconds=self.scan_interval_off)

            # Preserve last known valid device state so entities never flap or crash
            if self._cached_devices:
                LOGGER.debug(
                    "Preserving last known device state for %d StreamLabs device(s) during outage",
                    len(self._cached_devices),
                )
                return dict(self._cached_devices)

            raise UpdateFailed(f"Error communicating with StreamLabs API: {fetch_error}") from fetch_error

        # If API returned an empty device list but we previously had valid cached data,
        # treat as a transient empty-payload glitch and preserve active device state.
        if not devices_data and self._cached_devices:
            self._consecutive_failures += 1
            if self._consecutive_failures <= 3:
                LOGGER.warning(
                    "StreamLabs API returned empty device list (attempt %d); preserving last known state for %d device(s)",
                    self._consecutive_failures,
                    len(self._cached_devices),
                )
            else:
                LOGGER.debug(
                    "StreamLabs API empty response ongoing (attempt %d); preserving %d cached device(s)",
                    self._consecutive_failures,
                    len(self._cached_devices),
                )
            self.update_interval = timedelta(seconds=self.scan_interval_off)
            return dict(self._cached_devices)

        # Successful fetch: log recovery if previous attempts failed
        if self._consecutive_failures > 0:
            LOGGER.info(
                "StreamLabs cloud connection restored after %d failed attempt(s)",
                self._consecutive_failures,
            )
            self._consecutive_failures = 0

        self._cached_devices.update(devices_data)
        if self.monitored_locations is not None:
            self._cached_devices = {
                k: v for k, v in self._cached_devices.items()
                if str(v.location_id) in self.monitored_locations
            }

        return dict(self._cached_devices)

    def _extract_usage(self, usage_data: Dict[str, Any]) -> tuple[float, float, float]:
        """Extract daily, monthly, and yearly water consumption totals."""
        daily = 0.0
        monthly = 0.0
        yearly = 0.0

        if not usage_data or not isinstance(usage_data, dict):
            return daily, monthly, yearly

        # 1. Extract daily consumption
        day_val = usage_data.get("day")
        if isinstance(day_val, dict):
            for k in ("todayTotal", "total", "today", "value", "volume"):
                if k in day_val and day_val[k] is not None:
                    try:
                        daily = float(day_val[k])
                        if daily > 0:
                            break
                    except (ValueError, TypeError):
                        pass
        elif isinstance(day_val, (int, float)):
            daily = float(day_val)

        if daily == 0.0:
            for k in ("today", "todayTotal", "daily", "dailyTotal"):
                if k in usage_data and usage_data[k] is not None:
                    try:
                        daily = float(usage_data[k])
                        if daily > 0:
                            break
                    except (ValueError, TypeError):
                        pass

        # 2. Extract monthly consumption
        month_val = usage_data.get("month")
        if isinstance(month_val, dict):
            for k in ("thisMonthTotal", "total", "thisMonth", "value", "volume"):
                if k in month_val and month_val[k] is not None:
                    try:
                        monthly = float(month_val[k])
                        if monthly > 0:
                            break
                    except (ValueError, TypeError):
                        pass
        elif isinstance(month_val, (int, float)):
            monthly = float(month_val)

        if monthly == 0.0:
            for k in ("thisMonth", "thisMonthTotal", "monthly", "monthlyTotal", "monthTotal"):
                if k in usage_data and usage_data[k] is not None:
                    try:
                        monthly = float(usage_data[k])
                        if monthly > 0:
                            break
                    except (ValueError, TypeError):
                        pass

        # 3. Extract yearly consumption
        year_val = usage_data.get("year")
        if isinstance(year_val, dict):
            for k in ("thisYearTotal", "total", "thisYear", "value", "volume"):
                if k in year_val and year_val[k] is not None:
                    try:
                        yearly = float(year_val[k])
                        if yearly > 0:
                            break
                    except (ValueError, TypeError):
                        pass
        elif isinstance(year_val, (int, float)):
            yearly = float(year_val)

        if yearly == 0.0:
            for k in ("thisYear", "thisYearTotal", "yearly", "yearlyTotal", "yearTotal"):
                if k in usage_data and usage_data[k] is not None:
                    try:
                        yearly = float(usage_data[k])
                        if yearly > 0:
                            break
                    except (ValueError, TypeError):
                        pass

        # 4. Timeseries array check: {"data": [...]}
        if "data" in usage_data and isinstance(usage_data["data"], list):
            # Check for list of numbers (floats/ints) from rolling history endpoints
            num_items = [
                float(x) for x in usage_data["data"] if isinstance(x, (int, float))
            ]
            if num_items:
                interval = str(usage_data.get("interval", "")).lower()
                if interval == "month" and yearly == 0.0:
                    yearly = round(sum(num_items), 1)
                elif interval == "day" and monthly == 0.0:
                    monthly = round(sum(num_items), 1)
                elif interval == "hour" and daily == 0.0:
                    daily = round(sum(num_items), 1)
            elif daily == 0.0:
                # Dict items with "volume"
                daily = sum(
                    float(pt.get("volume", 0.0) or 0.0)
                    for pt in usage_data["data"]
                    if isinstance(pt, dict)
                )

        # 5. Logical consistency fallback:
        # A full calendar year's water usage cannot be less than the current month's usage.
        # If the cloud API returns 0.0 for year (e.g. brand new install, uncalibrated,
        # or cloud aggregation delay), yearly usage is at least the current monthly total.
        if yearly == 0.0 and monthly > 0.0:
            yearly = monthly

        return daily, monthly, yearly

    def _update_data(self) -> Dict[str, StreamLabsDeviceData]:
        """Synchronously poll the API for device and location statuses."""
        status_resp = self.client.get_status()
        raw_devices: List[Dict[str, Any]] = status_resp.get("devices", [])
        locations_summary = status_resp.get("locations_summary", [])
        devices_data: Dict[str, StreamLabsDeviceData] = {}

        raw_options = getattr(self.config_entry, "options", None)
        options = raw_options if isinstance(raw_options, dict) else {}
        raw_data = getattr(self.config_entry, "data", None)
        data = raw_data if isinstance(raw_data, dict) else {}

        _LOGGER.warning(
            "StreamLabs API account locations: %s | Active monitored_locations: %s (options=%s, data=%s)",
            locations_summary,
            self.monitored_locations,
            options.get(CONF_LOCATIONS),
            data.get(CONF_LOCATIONS),
        )

        # Auto-detect monitored locations if not configured, but existing HA registry has a subset
        if self.monitored_locations is None and getattr(self, "_registered_device_ids", None):
            matching_loc_ids = {
                str(dev.get("location_id"))
                for dev in raw_devices
                if dev.get("device_id") in self._registered_device_ids and dev.get("location_id")
            }
            if matching_loc_ids and len(matching_loc_ids) < len(locations_summary):
                self.monitored_locations = matching_loc_ids
                _LOGGER.warning(
                    "Auto-detected monitored locations based on existing Home Assistant device registry: %s",
                    self.monitored_locations,
                )
                new_opts = dict(self.config_entry.options or {})
                new_opts[CONF_LOCATIONS] = list(self.monitored_locations)
                self._pending_options_update = new_opts

        for dev in raw_devices:
            raw_loc_id = dev.get("location_id")
            loc_id = str(raw_loc_id) if raw_loc_id is not None else None
            dev_id = dev.get("device_id")
            if self.monitored_locations is not None and (loc_id is None or loc_id not in self.monitored_locations):
                _LOGGER.warning(
                    "SKIPPING unmonitored StreamLabs device %s ('%s') at location %s ('%s')",
                    dev_id,
                    dev.get("device_name"),
                    loc_id,
                    dev.get("location_name"),
                )
                continue

            _LOGGER.warning(
                "INCLUDING monitored StreamLabs device %s ('%s') at location %s ('%s')",
                dev_id,
                dev.get("device_name"),
                loc_id,
                dev.get("location_name"),
            )

            device_id = dev_id
            if not device_id:
                continue

            # Initialize with cached values if available to prevent 0.0 drops during transient fetch errors
            prev_cached = self._cached_devices.get(device_id)
            daily_usage = prev_cached.daily_usage if prev_cached else 0.0
            monthly_usage = prev_cached.monthly_usage if prev_cached else 0.0
            yearly_usage = prev_cached.yearly_usage if prev_cached else 0.0
            yearly_used_since: Optional[str] = prev_cached.yearly_used_since if prev_cached else None
            monthly_history: Optional[List[float]] = prev_cached.monthly_history if prev_cached else None

            try:
                usage_resp = self.client.get_water_usage(device_id)
                d, m, y = self._extract_usage(usage_resp)
                if d > 0 or m > 0 or y > 0:
                    daily_usage, monthly_usage, yearly_usage = d, m, y
            except Exception as err:
                _LOGGER.debug(
                    "Could not fetch detailed water usage for device %s (retaining cached usage): %s",
                    device_id,
                    err,
                )

            # In the StreamLabs mobile app, yearly usage and the 13-month bar chart
            # are retrieved via: GET /devices/{device_id}/water/{yyyy}?rolling=true
            # To minimize requests, we poll endpoint #3 once per hour (YEARLY_CACHE_INTERVAL).
            # In between hourly polls, we update the most recent (last) element in the
            # 13-month array using the live monthly_usage from endpoint #2, keeping
            # yearly_usage accurate in real time on every poll without hitting the server.
            now_mono = time.monotonic()
            cached_year = self._yearly_cache.get(device_id)

            if cached_year is None or (now_mono - cached_year.get("last_fetched", 0)) >= YEARLY_CACHE_INTERVAL:
                try:
                    current_year = datetime.now().strftime("%Y")
                    year_history = self.client.get_water_usage(
                        device_id, period=current_year, rolling=True
                    )
                    if isinstance(year_history, dict) and "data" in year_history:
                        raw_data = year_history["data"]
                        if isinstance(raw_data, list) and raw_data:
                            float_data = [
                                float(x) for x in raw_data if isinstance(x, (int, float))
                            ]
                            if float_data:
                                start_time = year_history.get("startTime")
                                if isinstance(start_time, (int, float)) and start_time > 0:
                                    used_since = datetime.fromtimestamp(
                                        start_time, timezone.utc
                                    ).strftime("%b, %Y")
                                else:
                                    one_year_ago = datetime.now() - timedelta(days=365)
                                    used_since = one_year_ago.strftime("%b, %Y")

                                cached_year = {
                                    "last_fetched": now_mono,
                                    "monthly_history": float_data,
                                    "used_since": used_since,
                                }
                                self._yearly_cache[device_id] = cached_year
                except Exception as err:
                    _LOGGER.debug(
                        "Could not fetch rolling yearly water usage for device %s: %s",
                        device_id,
                        err,
                    )
                    # Back off auxiliary fetch on failure so it doesn't starve or hammer routine polling
                    if cached_year is None:
                        self._yearly_cache[device_id] = {"last_fetched": now_mono}
                    else:
                        cached_year["last_fetched"] = now_mono

            if cached_year and cached_year.get("monthly_history"):
                history = list(cached_year["monthly_history"])
                # Dynamically update the most recent (last) month using current monthly_usage
                if monthly_usage > 0 and len(history) > 0:
                    history[-1] = monthly_usage
                    cached_year["monthly_history"][-1] = monthly_usage

                rolling_total = sum(history)
                if rolling_total > 0:
                    yearly_usage = round(rolling_total, 1)

                monthly_history = history
                yearly_used_since = cached_year.get("used_since")


            gallons_today = float(dev.get("gallons_today") or 0.0)
            # If detailed daily usage is unavailable, fall back to gallons_today from location
            if daily_usage == 0.0 and gallons_today > 0.0:
                daily_usage = gallons_today

            # Fetch detailed device telemetry (ambient temp, humidity, water pressure, water temp)
            # To minimize requests when polling at rapid waterOn rates, Endpoint #4 is cached
            # and refreshed at the waterOff interval (e.g. 60s).
            device_detail: Dict[str, Any] = {}
            cached_telemetry = self._telemetry_cache.get(device_id)
            if (
                cached_telemetry is not None
                and (now_mono - cached_telemetry.get("last_fetched", 0)) < self.scan_interval_off
            ):
                device_detail = cached_telemetry.get("data", {})
            else:
                try:
                    device_detail = self.client.get_device(device_id)
                    self._telemetry_cache[device_id] = {
                        "last_fetched": now_mono,
                        "data": device_detail,
                    }
                except Exception as err:
                    _LOGGER.debug(
                        "Could not fetch detailed telemetry for device %s: %s",
                        device_id,
                        err,
                    )
                    # Back off auxiliary fetch on failure so it doesn't retry on every 5s waterOn poll
                    self._telemetry_cache[device_id] = {
                        "last_fetched": now_mono,
                        "data": cached_telemetry.get("data", {}) if cached_telemetry else {},
                    }
                    if cached_telemetry:
                        device_detail = cached_telemetry.get("data", {})

            # Calculate estimated flow rate (gpm) during waterOn polling
            is_flowing = bool(dev.get("flowing", False))
            tracking = self._flow_tracking.setdefault(
                device_id,
                {
                    "prev_flowing": False,
                    "initial_usage": None,
                    "history": [],
                    "estimated_flow_rate": 0.0,
                },
            )

            if not is_flowing:
                tracking["prev_flowing"] = False
                tracking["initial_usage"] = None
                tracking["history"] = []
                tracking["estimated_flow_rate"] = 0.0
            else:
                if not tracking["prev_flowing"] or tracking["initial_usage"] is None:
                    # First poll of water-on event: record initial usage, wait for cloud sync flush
                    tracking["prev_flowing"] = True
                    tracking["initial_usage"] = daily_usage
                    tracking["history"] = []
                    tracking["estimated_flow_rate"] = 0.0
                elif not tracking["history"]:
                    # Absorb initial cloud sync backlog: do not calculate rate on first advance
                    if daily_usage > tracking["initial_usage"]:
                        # Cloud pre-sync backlog has flushed; establish baseline here
                        tracking["history"].append((daily_usage, now_mono))
                    elif daily_usage < tracking["initial_usage"]:
                        # Midnight rollover
                        tracking["initial_usage"] = daily_usage
                    tracking["estimated_flow_rate"] = 0.0
                else:
                    # Daily rollover check
                    last_usage = tracking["history"][-1][0]
                    if daily_usage < last_usage:
                        tracking["initial_usage"] = daily_usage
                        tracking["history"] = []
                        tracking["estimated_flow_rate"] = 0.0
                    else:
                        # Append new sample point
                        tracking["history"].append((daily_usage, now_mono))
                        # Keep at most 3 points: [t_{n-2}, t_{n-1}, t_n]
                        if len(tracking["history"]) > 3:
                            tracking["history"].pop(0)

                        # Calculate flow rate across up to 2 intervals (approx 2x waterOn interval)
                        # to eliminate cloud quantization/batching jitter between adjacent polls
                        baseline_point = tracking["history"][0]
                        current_point = tracking["history"][-1]

                        delta_time = current_point[1] - baseline_point[1]
                        delta_gallons = current_point[0] - baseline_point[0]

                        if delta_time > 0 and delta_gallons >= 0:
                            delta_minutes = delta_time / 60.0
                            tracking["estimated_flow_rate"] = round(delta_gallons / delta_minutes, 1)

            estimated_flow_rate = tracking["estimated_flow_rate"]

            raw_ambient = (
                device_detail.get("ambientTemp")
                or device_detail.get("ambient_temp")
                or device_detail.get("roomTemp")
                or dev.get("ambient_temp")
                or dev.get("ambientTemp")
            )
            raw_humidity = (
                device_detail.get("humidity")
                or device_detail.get("roomHumidity")
                or dev.get("humidity")
            )
            raw_pressure = (
                device_detail.get("waterPressure")
                or device_detail.get("water_pressure")
                or device_detail.get("pressure")
                or dev.get("water_pressure")
                or dev.get("waterPressure")
            )
            raw_water_temp = (
                device_detail.get("waterTemp")
                or device_detail.get("water_temp")
                or dev.get("water_temp")
                or dev.get("waterTemp")
            )

            room_temp = extract_reading_value(raw_ambient)
            room_humidity = extract_reading_value(raw_humidity)
            water_pressure = extract_reading_value(raw_pressure)
            water_temp = extract_reading_value(raw_water_temp)

            dev_mode = (
                device_detail.get("mode")
                or (device_detail.get("settings", {}).get("mode") if isinstance(device_detail.get("settings"), dict) else None)
                or dev.get("mode")
                or "home"
            )
            valve_pos = (
                (device_detail.get("valve", {}).get("position") if isinstance(device_detail.get("valve"), dict) else None)
                or dev.get("valve_position")
            )

            devices_data[device_id] = StreamLabsDeviceData(
                device_id=device_id,
                device_name=dev.get("device_name") or f"StreamLabs {device_id}",
                location_id=loc_id or "unknown",
                location_name=dev.get("location_name") or "StreamLabs Location",
                connected=bool(dev.get("connected", True)),
                flowing=is_flowing,
                mode=str(dev_mode),
                has_valve=bool(dev.get("has_valve", False)),
                valve_position=valve_pos,
                daily_usage=daily_usage,
                monthly_usage=monthly_usage,
                yearly_usage=yearly_usage,
                gallons_today=gallons_today,
                raw_status=dev,
                estimated_flow_rate=estimated_flow_rate,
                room_temp=room_temp,
                room_humidity=room_humidity,
                water_pressure=water_pressure,
                water_temp=water_temp,
                yearly_used_since=yearly_used_since,
                monthly_history=monthly_history,
            )

        # Dynamically adjust polling interval:
        # If any monitored device is currently flowing, poll at water_on_interval;
        # otherwise, poll at water_off_interval.
        any_flowing = any(d.flowing for d in devices_data.values())
        target_interval = timedelta(
            seconds=self.scan_interval_on if any_flowing else self.scan_interval_off
        )
        if self.update_interval != target_interval:
            self.update_interval = target_interval
            _LOGGER.debug(
                "Adjusted polling interval to %s (flowing=%s)",
                target_interval,
                any_flowing,
            )

        return devices_data
