"""Support for StreamLabs Water Shutoff Valve."""

from __future__ import annotations

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ValvePosition
from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator
from .entity import StreamlabsBaseEntity, async_setup_device_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs valve from a config entry."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id, data: (
            [StreamlabsValve(coordinator, device_id)]
            if data.has_valve or data.valve_position is not None
            else []
        ),
    )


class StreamlabsValve(StreamlabsBaseEntity, ValveEntity):
    """Representation of a StreamLabs water shutoff valve."""

    _attr_device_class = ValveDeviceClass.WATER
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
        actual = data.valve_position.lower() if data and data.valve_position else None
        if (position := self._resolve_optimistic(actual)) is None:
            return None
        return position == ValvePosition.CLOSE

    async def _async_set_valve(self, position: ValvePosition) -> None:
        await self.coordinator.async_client_call(
            self.coordinator.client.set_valve, self._device_id, position
        )
        self._set_optimistic(position)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_open_valve(self) -> None:
        """Open the water valve."""
        await self._async_set_valve(ValvePosition.OPEN)

    async def async_close_valve(self) -> None:
        """Close the water valve."""
        await self._async_set_valve(ValvePosition.CLOSE)
