"""Support for StreamLabs Monitoring Mode Select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MODE_AWAY, MODE_HOME, VALID_MODES
from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator
from .entity import StreamlabsBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs select entities from a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        StreamlabsModeSelect(coordinator, device_id)
        for device_id in coordinator.data
    )


class StreamlabsModeSelect(StreamlabsBaseEntity, SelectEntity):
    """Select entity for StreamLabs Home / Away monitoring mode."""

    _attr_translation_key = "monitoring_mode"
    _attr_options = VALID_MODES

    def __init__(self, coordinator: StreamlabsCoordinator, device_id: str) -> None:
        """Initialize the mode select entity."""
        super().__init__(coordinator, device_id, "monitoring_mode")

    @property
    def current_option(self) -> str | None:
        """Return the current monitoring mode."""
        data = self.device_data
        if not data:
            return None
        return data.mode

    @property
    def icon(self) -> str:
        """Return icon reflecting current mode."""
        if self.current_option == MODE_AWAY:
            return "mdi:home-export-outline"
        return "mdi:home"

    async def async_select_option(self, option: str) -> None:
        """Change the monitoring mode."""
        if option not in VALID_MODES:
            raise ValueError(f"Invalid mode selected: {option}")

        await self.hass.async_add_executor_job(
            self.coordinator.client.set_mode, self._device_id, option
        )
        await self.coordinator.async_request_refresh()
