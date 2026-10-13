"""Base entity for StreamLabs Libre integration."""

from __future__ import annotations

from typing import Optional

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import StreamlabsCoordinator, StreamLabsDeviceData


class StreamlabsBaseEntity(CoordinatorEntity[StreamlabsCoordinator]):
    """Defines a base StreamLabs entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: StreamlabsCoordinator,
        device_id: str,
        key: str,
    ) -> None:
        """Initialize the StreamLabs base entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = key
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def device_data(self) -> Optional[StreamLabsDeviceData]:
        """Return the device data object from coordinator."""
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self._device_id in self.coordinator.data
            and self.device_data is not None
            and self.device_data.connected
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for Home Assistant device registry."""
        data = self.device_data
        name = data.device_name if data else f"StreamLabs {self._device_id}"
        model = "Streamlabs Control" if (data and data.has_valve) else "Streamlabs Monitor"
        suggested_area = data.location_name if data else None

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=name,
            manufacturer="StreamLabs",
            model=model,
            suggested_area=suggested_area,
        )
