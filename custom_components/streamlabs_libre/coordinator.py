"""Coordinator for StreamLabs Libre integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import StreamLabsClient, StreamLabsError, extract_reading_value
from .const import CONF_LOCATIONS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

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
        scan_interval = DEFAULT_SCAN_INTERVAL
        if isinstance(getattr(config_entry, "options", None), dict):
            scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, scan_interval)
        elif isinstance(getattr(config_entry, "data", None), dict):
            scan_interval = config_entry.data.get(CONF_SCAN_INTERVAL, scan_interval)
        try:
            scan_interval = int(scan_interval)
        except (ValueError, TypeError):
            scan_interval = DEFAULT_SCAN_INTERVAL

        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name="StreamLabs Libre",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.monitored_locations: Optional[Set[str]] = None
        locations_cfg = config_entry.data.get(CONF_LOCATIONS)
        if locations_cfg:
            self.monitored_locations = set(locations_cfg)

    async def _async_update_data(self) -> Dict[str, StreamLabsDeviceData]:
        """Fetch latest data from StreamLabs."""
        try:
            return await self.hass.async_add_executor_job(self._update_data)
        except StreamLabsError as err:
            raise UpdateFailed(f"Error communicating with StreamLabs API: {err}") from err
        except Exception as err:
            LOGGER.exception("Unexpected error fetching StreamLabs data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

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
        devices_data: Dict[str, StreamLabsDeviceData] = {}

        for dev in raw_devices:
            loc_id = dev.get("location_id")
            if self.monitored_locations and loc_id not in self.monitored_locations:
                continue

            device_id = dev.get("device_id")
            if not device_id:
                continue

            # Attempt to fetch volumetric consumption for this device
            daily_usage = 0.0
            monthly_usage = 0.0
            yearly_usage = 0.0
            yearly_used_since: Optional[str] = None
            monthly_history: Optional[List[float]] = None

            try:
                usage_resp = self.client.get_water_usage(device_id)
                daily_usage, monthly_usage, yearly_usage = self._extract_usage(usage_resp)
            except Exception as err:
                _LOGGER.debug(
                    "Could not fetch detailed water usage for device %s: %s",
                    device_id,
                    err,
                )

            # In the StreamLabs mobile app, yearly usage and the 13-month bar chart
            # are retrieved via: GET /devices/{device_id}/water/{yyyy}?rolling=true
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
                            monthly_history = float_data
                            # In the mobile app, WaterUsage.total() is the sum of rolling monthly totals
                            rolling_total = sum(float_data)
                            if rolling_total > 0:
                                yearly_usage = round(rolling_total, 1)

                    start_time = year_history.get("startTime")
                    if isinstance(start_time, (int, float)) and start_time > 0:
                        yearly_used_since = datetime.fromtimestamp(
                            start_time, timezone.utc
                        ).strftime("%b, %Y")
                    else:
                        one_year_ago = datetime.now() - timedelta(days=365)
                        yearly_used_since = one_year_ago.strftime("%b, %Y")
            except Exception as err:
                _LOGGER.debug(
                    "Could not fetch rolling yearly water usage for device %s: %s",
                    device_id,
                    err,
                )

            gallons_today = float(dev.get("gallons_today") or 0.0)
            # If detailed daily usage is unavailable, fall back to gallons_today from location
            if daily_usage == 0.0 and gallons_today > 0.0:
                daily_usage = gallons_today

            # Fetch detailed device telemetry (ambient temp, humidity, water pressure, water temp)
            device_detail: Dict[str, Any] = {}
            try:
                device_detail = self.client.get_device(device_id)
            except Exception as err:
                _LOGGER.debug(
                    "Could not fetch detailed telemetry for device %s: %s",
                    device_id,
                    err,
                )

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
                flowing=bool(dev.get("flowing", False)),
                mode=str(dev_mode),
                has_valve=bool(dev.get("has_valve", False)),
                valve_position=valve_pos,
                daily_usage=daily_usage,
                monthly_usage=monthly_usage,
                yearly_usage=yearly_usage,
                gallons_today=gallons_today,
                raw_status=dev,
                room_temp=room_temp,
                room_humidity=room_humidity,
                water_pressure=water_pressure,
                water_temp=water_temp,
                yearly_used_since=yearly_used_since,
                monthly_history=monthly_history,
            )


        return devices_data
