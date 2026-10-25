"""Base entity for StreamLabs Libre integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import time

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, OPTIMISTIC_TTL
from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator, StreamLabsDeviceData


class StreamlabsBaseEntity(CoordinatorEntity[StreamlabsCoordinator]):
    """Defines a base StreamLabs entity."""

    _attr_has_entity_name = True

    # Entities that report on the disconnection itself must stay available while offline
    _available_when_disconnected = False

    def __init__(
        self,
        coordinator: StreamlabsCoordinator,
        device_id: str,
        key: str,
    ) -> None:
        """Initialize the StreamLabs base entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"
        self._optimistic: tuple[str, float] | None = None

        data = coordinator.data[device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=data.device_name,
            manufacturer="StreamLabs",
            model="Streamlabs Control" if data.has_valve else "Streamlabs Monitor",
            suggested_area=data.location_name,
        )

    @property
    def device_data(self) -> StreamLabsDeviceData | None:
        """Return the device data object from coordinator."""
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True if the device is present and (usually) connected."""
        if not super().available or (data := self.device_data) is None:
            return False
        return data.connected or self._available_when_disconnected

    def _set_optimistic(self, value: str) -> None:
        """Remember a just-commanded state until the cloud reports it (or the TTL lapses)."""
        self._optimistic = (value, time.monotonic())

    def _resolve_optimistic(self, actual: str | None) -> str | None:
        """Return the optimistic value while it is pending, else the actual one."""
        if self._optimistic is not None:
            value, started = self._optimistic
            if actual == value or time.monotonic() - started > OPTIMISTIC_TTL:
                self._optimistic = None
            else:
                return value
        return actual


@callback
def async_setup_device_entities(
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[StreamlabsCoordinator, str, StreamLabsDeviceData], Iterable[Entity]],
) -> None:
    """Create entities for each device now, and for devices that appear later.

    ``factory`` may return nothing for a device (e.g. a valve platform on a monitor
    without a valve); it is asked again on later updates until it returns entities.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_devices() -> None:
        new: list[Entity] = []
        for device_id, data in coordinator.data.items():
            if device_id in known:
                continue
            if entities := list(factory(coordinator, device_id, data)):
                known.add(device_id)
                new.extend(entities)
        if new:
            async_add_entities(new)

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))
