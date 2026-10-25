"""Support for StreamLabs Water Consumption Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator, StreamLabsDeviceData
from .entity import StreamlabsBaseEntity, async_setup_device_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class StreamlabsSensorEntityDescription(SensorEntityDescription):
    """Streamlabs sensor entity description."""

    value_fn: Callable[[StreamLabsDeviceData], StateType]
    extra_attributes_fn: Callable[[StreamLabsDeviceData], dict[str, Any] | None] | None = None


def _yearly_attributes(data: StreamLabsDeviceData) -> dict[str, Any] | None:
    attrs = {
        "used_since": data.yearly_used_since,
        "monthly_history": data.monthly_history,
    }
    return {k: v for k, v in attrs.items() if v is not None} or None


SENSORS: tuple[StreamlabsSensorEntityDescription, ...] = (
    StreamlabsSensorEntityDescription(
        key="estimated_flow_rate",
        translation_key="estimated_flow_rate",
        native_unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.estimated_flow_rate,
    ),
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
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: data.monthly_usage,
    ),
    # Rolling 13-month window: it can go down as well as up, so it is not a meter
    StreamlabsSensorEntityDescription(
        key="yearly_usage",
        translation_key="yearly_usage",
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        device_class=SensorDeviceClass.WATER,
        suggested_display_precision=1,
        value_fn=lambda data: data.yearly_usage,
        extra_attributes_fn=_yearly_attributes,
    ),
    StreamlabsSensorEntityDescription(
        key="room_humidity",
        translation_key="room_humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.room_humidity,
    ),
    StreamlabsSensorEntityDescription(
        key="room_temp",
        translation_key="room_temp",
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.room_temp,
    ),
    StreamlabsSensorEntityDescription(
        key="water_pressure",
        translation_key="water_pressure",
        native_unit_of_measurement=UnitOfPressure.PSI,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.water_pressure,
    ),
    StreamlabsSensorEntityDescription(
        key="water_temp",
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
    async_setup_device_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id, _data: [
            StreamlabsSensor(coordinator, device_id, description) for description in SENSORS
        ],
    )


class StreamlabsSensor(StreamlabsBaseEntity, SensorEntity):
    """Monitors StreamLabs volumetric water usage and environmental telemetry."""

    entity_description: StreamlabsSensorEntityDescription
    # Up to 13 values that change on every poll; keep them out of the recorder database
    _unrecorded_attributes = frozenset({"monthly_history"})

    def __init__(
        self,
        coordinator: StreamlabsCoordinator,
        device_id: str,
        entity_description: StreamlabsSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, entity_description.key)
        self.entity_description = entity_description
        self._update_attrs()

    def _update_attrs(self) -> None:
        if (data := self.device_data) is None:
            return
        description = self.entity_description
        self._attr_native_value = description.value_fn(data)
        if description.extra_attributes_fn:
            self._attr_extra_state_attributes = description.extra_attributes_fn(data)

    @property
    def available(self) -> bool:
        """Return True if entity is available and has a valid reading."""
        return super().available and self._attr_native_value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_attrs()
        super()._handle_coordinator_update()
