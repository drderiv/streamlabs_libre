"""Support for StreamLabs Water Consumption Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator, StreamLabsDeviceData
from .entity import StreamlabsBaseEntity


@dataclass(frozen=True, kw_only=True)
class StreamlabsSensorEntityDescription(SensorEntityDescription):
    """Streamlabs sensor entity description."""

    value_fn: Callable[[StreamLabsDeviceData], StateType]


SENSORS: tuple[StreamlabsSensorEntityDescription, ...] = (
    StreamlabsSensorEntityDescription(
        key="daily_usage",
        translation_key="daily_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: data.daily_usage,
    ),
    StreamlabsSensorEntityDescription(
        key="monthly_usage",
        translation_key="monthly_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda data: data.monthly_usage,
    ),
    StreamlabsSensorEntityDescription(
        key="yearly_usage",
        translation_key="yearly_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda data: data.yearly_usage,
    ),
    StreamlabsSensorEntityDescription(
        key="gallons_today",
        translation_key="gallons_today",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: data.gallons_today,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamlabsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up StreamLabs water sensors from a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        StreamlabsSensor(coordinator, device_id, entity_description)
        for device_id in coordinator.data
        for entity_description in SENSORS
    )


class StreamlabsSensor(StreamlabsBaseEntity, SensorEntity):
    """Monitors StreamLabs volumetric water usage."""

    entity_description: StreamlabsSensorEntityDescription

    def __init__(
        self,
        coordinator: StreamlabsCoordinator,
        device_id: str,
        entity_description: StreamlabsSensorEntityDescription,
    ) -> None:
        """Initialize the water usage sensor."""
        super().__init__(coordinator, device_id, entity_description.key)
        self.entity_description = entity_description

    @property
    def native_value(self) -> StateType:
        """Return the current sensor value."""
        data = self.device_data
        if not data:
            return None
        return self.entity_description.value_fn(data)
