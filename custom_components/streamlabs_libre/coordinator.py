"""Coordinator for StreamLabs Libre integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any, Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import StreamLabsClient, StreamLabsError, extract_reading_value
from .const import CONF_LOCATIONS, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

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
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name="StreamLabs Libre",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
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

        if not usage_data:
            return daily, monthly, yearly

        # Format 1: Direct summary fields or comparative fields
        # e.g., {"today": 12.3, "thisMonth": 120.5, "thisYear": 1500.0}
        if "today" in usage_data:
            daily = float(usage_data.get("today", 0.0) or 0.0)
            monthly = float(usage_data.get("thisMonth", 0.0) or 0.0)
            yearly = float(usage_data.get("thisYear", 0.0) or 0.0)
            return daily, monthly, yearly

        # Format 2: Comparative structures {"day": {"todayTotal": ...}, "month": {"thisMonthTotal": ...}}
        day_obj = usage_data.get("day")
        if isinstance(day_obj, dict):
            daily = float(day_obj.get("todayTotal", 0.0) or 0.0)
        month_obj = usage_data.get("month")
        if isinstance(month_obj, dict):
            monthly = float(month_obj.get("thisMonthTotal", month_obj.get("total", 0.0)) or 0.0)
        year_obj = usage_data.get("year")
        if isinstance(year_obj, dict):
            yearly = float(year_obj.get("thisYearTotal", year_obj.get("total", 0.0)) or 0.0)

        # Format 3: Array of data points {"data": [{"volume": ...}], ...}
        if daily == 0.0 and "data" in usage_data and isinstance(usage_data["data"], list):
            daily = sum(float(pt.get("volume", 0.0) or 0.0) for pt in usage_data["data"] if isinstance(pt, dict))

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
            try:
                usage_resp = self.client.get_water_usage(device_id)
                daily_usage, monthly_usage, yearly_usage = self._extract_usage(usage_resp)
            except Exception as err:
                _LOGGER.debug(
                    "Could not fetch detailed water usage for device %s: %s",
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

            devices_data[device_id] = StreamLabsDeviceData(
                device_id=device_id,
                device_name=dev.get("device_name") or f"StreamLabs {device_id}",
                location_id=loc_id or "unknown",
                location_name=dev.get("location_name") or "StreamLabs Location",
                connected=bool(dev.get("connected", True)),
                flowing=bool(dev.get("flowing", False)),
                mode=str(dev.get("mode", "home")),
                has_valve=bool(dev.get("has_valve", False)),
                valve_position=dev.get("valve_position"),
                daily_usage=daily_usage,
                monthly_usage=monthly_usage,
                yearly_usage=yearly_usage,
                gallons_today=gallons_today,
                raw_status=dev,
                room_temp=room_temp,
                room_humidity=room_humidity,
                water_pressure=water_pressure,
                water_temp=water_temp,
            )

        return devices_data
