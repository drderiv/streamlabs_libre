"""Support for StreamLabs Binary Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator, StreamLabsDeviceData
from .entity import StreamlabsBaseEntity


@dataclass(frozen=True, kw_only=True)
class StreamlabsBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Streamlabs binary sensor entity description."""

    is_on_fn: Callable[[StreamLabsDeviceData], bool]


BINARY_SENSORS: tuple[StreamlabsBinarySensorEntityDescription, ...] = (
    StreamlabsBinarySensorEntityDescription(
        key="flowing",
        name="Water flowing",
        translation_key="flowing",
        icon="mdi:water-pump",
        is_on_fn=lambda data: data.flowing,
    ),
    StreamlabsBinarySensorEntityDescription(
        key="connectivity",
        name="Connectivity",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda data: data.connected,
    ),
    StreamlabsBinarySensorEntityDescription(
        key="away_mode",
        name="Away mode",
        translation_key="away_mode",
        icon="mdi:home-export-outline",
        entity_registry_enabled_default=False,
        is_on_fn=lambda data: data.mode == "away",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs binary sensors from a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        StreamlabsBinarySensor(coordinator, device_id, entity_description)
        for device_id in coordinator.data
        for entity_description in BINARY_SENSORS
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

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is on."""
        data = self.device_data
        if not data:
            return False
        return self.entity_description.is_on_fn(data)
