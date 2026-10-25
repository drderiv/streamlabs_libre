"""Support for StreamLabs Binary Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator, StreamLabsDeviceData
from .entity import StreamlabsBaseEntity, async_setup_device_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class StreamlabsBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Streamlabs binary sensor entity description."""

    is_on_fn: Callable[[StreamLabsDeviceData], bool]
    available_when_disconnected: bool = False


BINARY_SENSORS: tuple[StreamlabsBinarySensorEntityDescription, ...] = (
    StreamlabsBinarySensorEntityDescription(
        key="flowing",
        translation_key="flowing",
        is_on_fn=lambda data: data.flowing,
    ),
    StreamlabsBinarySensorEntityDescription(
        key="connectivity",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda data: data.connected,
        available_when_disconnected=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs binary sensors from a config entry."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id, _data: [
            StreamlabsBinarySensor(coordinator, device_id, description)
            for description in BINARY_SENSORS
        ],
    )


class StreamlabsBinarySensor(StreamlabsBaseEntity, BinarySensorEntity):
    """Binary sensor for StreamLabs devices."""

    entity_description: StreamlabsBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: StreamlabsCoordinator,
        device_id: str,
        entity_description: StreamlabsBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_id, entity_description.key)
        self.entity_description = entity_description
        self._available_when_disconnected = entity_description.available_when_disconnected
        self._update_attrs()

    def _update_attrs(self) -> None:
        if (data := self.device_data) is not None:
            self._attr_is_on = self.entity_description.is_on_fn(data)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_attrs()
        super()._handle_coordinator_update()
