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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator, StreamLabsDeviceData
from .entity import StreamlabsBaseEntity


@dataclass(frozen=True, kw_only=True)
class StreamlabsSensorEntityDescription(SensorEntityDescription):
    """Streamlabs sensor entity description."""

    value_fn: Callable[[StreamLabsDeviceData], StateType]
    extra_attributes_fn: Optional[Callable[[StreamLabsDeviceData], Optional[Dict[str, Any]]]] = None


SENSORS: tuple[StreamlabsSensorEntityDescription, ...] = (
    StreamlabsSensorEntityDescription(
        key="daily_usage",
        name="Daily water usage",
        translation_key="daily_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: data.daily_usage,
    ),
    StreamlabsSensorEntityDescription(
        key="monthly_usage",
        name="Monthly water usage",
        translation_key="monthly_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda data: data.monthly_usage,
    ),
    StreamlabsSensorEntityDescription(
        key="yearly_usage",
        name="Yearly water usage",
        translation_key="yearly_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda data: data.yearly_usage,
        extra_attributes_fn=lambda data: {
            k: v
            for k, v in {
                "used_since": data.yearly_used_since,
                "monthly_history": data.monthly_history,
            }.items()
            if v is not None
        } or None,
    ),

    StreamlabsSensorEntityDescription(
        key="gallons_today",
        name="Gallons today",
        translation_key="gallons_today",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: data.gallons_today,
    ),
    StreamlabsSensorEntityDescription(
        key="room_humidity",
        name="Room humidity",
        translation_key="room_humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.room_humidity,
    ),
    StreamlabsSensorEntityDescription(
        key="room_temp",
        name="Room temp",
        translation_key="room_temp",
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.room_temp,
    ),
    StreamlabsSensorEntityDescription(
        key="water_pressure",
        name="Water pressure",
        translation_key="water_pressure",
        native_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.water_pressure,
    ),
    StreamlabsSensorEntityDescription(
        key="water_temp",
        name="Water temp",
        translation_key="water_temp",
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.water_temp,
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
    """Monitors StreamLabs volumetric water usage and environmental telemetry."""

    entity_description: StreamlabsSensorEntityDescription

    def __init__(
        self,
        coordinator: StreamlabsCoordinator,
        device_id: str,
        entity_description: StreamlabsSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, entity_description.key)
        self.entity_description = entity_description

    @property
    def available(self) -> bool:
        """Return True if entity is available and has a valid reading."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> StateType:
        """Return the current sensor value."""
        data = self.device_data
        if not data:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return extra state attributes."""
        if not self.entity_description.extra_attributes_fn:
            return None
        data = self.device_data
        if not data:
            return None
        return self.entity_description.extra_attributes_fn(data)

