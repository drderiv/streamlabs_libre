"""Support for the StreamLabs Home / Away monitoring mode select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Mode
from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator
from .entity import StreamlabsBaseEntity, async_setup_device_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs select entities from a config entry."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id, _data: [StreamlabsModeSelect(coordinator, device_id)],
    )


class StreamlabsModeSelect(StreamlabsBaseEntity, SelectEntity):
    """Select entity for StreamLabs Home / Away monitoring mode."""

    _attr_translation_key = "monitoring_mode"
    _attr_options = list(Mode)

    def __init__(self, coordinator: StreamlabsCoordinator, device_id: str) -> None:
        """Initialize the mode select entity."""
        super().__init__(coordinator, device_id, "monitoring_mode")

    @property
    def current_option(self) -> str | None:
        """Return the current monitoring mode."""
        data = self.device_data
        actual = data.mode.lower() if data and data.mode else None
        return self._resolve_optimistic(actual)

    async def async_select_option(self, option: str) -> None:
        """Change the monitoring mode."""
        await self.coordinator.async_client_call(
            self.coordinator.client.set_mode, self._device_id, option
        )
        self._set_optimistic(option)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
