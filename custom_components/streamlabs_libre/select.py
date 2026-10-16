import asyncio
import time

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
    added_devices: set[str] = set()

    def _check_and_add_selects() -> None:
        new_entities: list[StreamlabsModeSelect] = []
        for device_id in coordinator.data:
            if device_id not in added_devices:
                added_devices.add(device_id)
                new_entities.append(StreamlabsModeSelect(coordinator, device_id))
        if new_entities:
            async_add_entities(new_entities)

    _check_and_add_selects()
    if hasattr(coordinator, "async_add_listener"):
        entry.async_on_unload(coordinator.async_add_listener(_check_and_add_selects))


class StreamlabsModeSelect(StreamlabsBaseEntity, SelectEntity):
    """Select entity for StreamLabs Home / Away monitoring mode."""

    _attr_name = "Monitoring mode"
    _attr_translation_key = "monitoring_mode"
    _attr_options = ["Home", "Away"]

    def __init__(self, coordinator: StreamlabsCoordinator, device_id: str) -> None:
        """Initialize the mode select entity."""
        super().__init__(coordinator, device_id, "monitoring_mode")
        self._optimistic_mode: str | None = None
        self._optimistic_time: float = 0.0

    @property
    def current_option(self) -> str | None:
        """Return the current monitoring mode."""
        # Hold optimistic state for up to 5 seconds to absorb cloud replication lag
        if self._optimistic_mode and (time.time() - self._optimistic_time < 5.0):
            data = self.device_data
            if data and data.mode and data.mode.lower() == self._optimistic_mode.lower():
                self._optimistic_mode = None
            else:
                return "Away" if self._optimistic_mode.lower() == "away" else "Home"

        data = self.device_data
        if not data or not data.mode:
            return None
        return "Away" if data.mode.lower() == "away" else "Home"

    @property
    def icon(self) -> str:
        """Return icon reflecting current mode."""
        if self.current_option == "Away":
            return "mdi:home-export-outline"
        return "mdi:home"

    async def async_select_option(self, option: str) -> None:
        """Change the monitoring mode."""
        api_mode = option.lower()
        if api_mode not in ("home", "away"):
            raise ValueError(f"Invalid mode selected: {option}")

        # Optimistically update local data and trigger instant UI update
        self._optimistic_mode = api_mode
        self._optimistic_time = time.time()
        if self.device_data:
            self.device_data.mode = api_mode
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_mode, self._device_id, api_mode
            )
        except Exception:
            self._optimistic_mode = None
            if self.device_data:
                await self.coordinator.async_request_refresh()
            self.async_write_ha_state()
            raise

        # Allow cloud backend to settle before requesting coordinator refresh
        await asyncio.sleep(1.0)
        await self.coordinator.async_request_refresh()
