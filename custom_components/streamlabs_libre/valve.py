"""Support for StreamLabs Water Shutoff Valve."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import VALVE_CLOSE, VALVE_OPEN
from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator
from .entity import StreamlabsBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs valve from a config entry."""
    coordinator = entry.runtime_data

    entities: list[StreamlabsValve] = []
    for device_id, device_data in coordinator.data.items():
        if device_data.has_valve or device_data.valve_position is not None:
            entities.append(StreamlabsValve(coordinator, device_id))

    async_add_entities(entities)


class StreamlabsValve(StreamlabsBaseEntity, ValveEntity):
    """Representation of a StreamLabs water shutoff valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_name = "Water valve"
    _attr_translation_key = "shutoff_valve"
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False

    def __init__(self, coordinator: StreamlabsCoordinator, device_id: str) -> None:
        """Initialize the valve entity."""
        super().__init__(coordinator, device_id, "shutoff_valve")

    @property
    def is_closed(self) -> bool | None:
        """Return True if valve is closed."""
        data = self.device_data
        if not data or not data.valve_position:
            return None
        return data.valve_position.lower() == VALVE_CLOSE

    @property
    def icon(self) -> str:
        """Return dynamic valve icon."""
        if self.is_closed:
            return "mdi:valve-closed"
        return "mdi:valve-open"

    async def async_open_valve(self) -> None:
        """Open the water valve."""
        if self.device_data:
            self.device_data.valve_position = VALVE_OPEN
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_valve, self._device_id, VALVE_OPEN
            )
        except Exception:
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
            raise

        await asyncio.sleep(1.0)
        await self.coordinator.async_request_refresh()

    async def async_close_valve(self) -> None:
        """Close the water valve."""
        if self.device_data:
            self.device_data.valve_position = VALVE_CLOSE
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_valve, self._device_id, VALVE_CLOSE
            )
        except Exception:
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
            raise

        await asyncio.sleep(1.0)
        await self.coordinator.async_request_refresh()
