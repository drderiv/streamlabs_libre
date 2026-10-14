"""Test configuration and Home Assistant module mocks."""

from dataclasses import dataclass
import sys
from typing import Any
from unittest.mock import MagicMock

# Base class definitions for dataclass compatibility
@dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str
    name: str | None = None
    translation_key: str | None = None
    icon: str | None = None
    device_class: Any = None
    entity_registry_enabled_default: bool = True


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    native_unit_of_measurement: str | None = None
    state_class: Any = None
    suggested_display_precision: int | None = None


@dataclass(frozen=True, kw_only=True)
class BinarySensorEntityDescription(EntityDescription):
    pass


class Entity:
    _attr_has_entity_name = True
    _attr_unique_id = None
    _attr_device_info = None

    def async_write_ha_state(self) -> None:
        pass


class CoordinatorEntity(Entity):
    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator

    def __class_getitem__(cls, item: Any) -> type:
        return cls


class ValveEntity(Entity):
    pass


class SelectEntity(Entity):
    pass


class SensorEntity(Entity):
    pass


class BinarySensorEntity(Entity):
    pass


class DataUpdateCoordinator:
    def __init__(
        self,
        hass: Any,
        logger: Any,
        *,
        config_entry: Any = None,
        name: str = "",
        update_interval: Any = None,
    ) -> None:
        self.hass = hass
        self.logger = logger
        self.config_entry = config_entry
        self.name = name
        self.update_interval = update_interval
        self.data: Any = {}
        self.last_update_success = True

    def __class_getitem__(cls, item: Any) -> type:
        return cls

    async def async_config_entry_first_refresh(self) -> None:
        pass

    async def async_request_refresh(self) -> None:
        pass


class ConfigFlow:
    def __init_subclass__(cls, domain: str = "", **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._domain = domain

    async def async_set_unique_id(self, unique_id: str) -> None:
        pass

    def _abort_if_unique_id_configured(self) -> None:
        pass

    def async_create_entry(self, *, title: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: Any = None,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }


# Register modules in sys.modules
for mod in [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.valve",
    "homeassistant.components.select",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.typing",
    "homeassistant.helpers.update_coordinator",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Attach class types to mocks
sys.modules["homeassistant.components.sensor"].SensorEntityDescription = SensorEntityDescription
sys.modules["homeassistant.components.sensor"].SensorEntity = SensorEntity
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorDeviceClass.WATER = "water"
sys.modules["homeassistant.components.sensor"].SensorDeviceClass.TEMPERATURE = "temperature"
sys.modules["homeassistant.components.sensor"].SensorDeviceClass.HUMIDITY = "humidity"
sys.modules["homeassistant.components.sensor"].SensorDeviceClass.PRESSURE = "pressure"
sys.modules["homeassistant.components.sensor"].SensorStateClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorStateClass.TOTAL = "total"
sys.modules["homeassistant.components.sensor"].SensorStateClass.TOTAL_INCREASING = "total_increasing"
sys.modules["homeassistant.components.sensor"].SensorStateClass.MEASUREMENT = "measurement"

sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntityDescription = BinarySensorEntityDescription
sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntity = BinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass.CONNECTIVITY = "connectivity"

sys.modules["homeassistant.components.valve"].ValveEntity = ValveEntity
sys.modules["homeassistant.components.valve"].ValveDeviceClass = MagicMock()
sys.modules["homeassistant.components.valve"].ValveDeviceClass.WATER = "water"
sys.modules["homeassistant.components.valve"].ValveEntityFeature = MagicMock()
sys.modules["homeassistant.components.valve"].ValveEntityFeature.OPEN = 1
sys.modules["homeassistant.components.valve"].ValveEntityFeature.CLOSE = 2

sys.modules["homeassistant.components.select"].SelectEntity = SelectEntity
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = DataUpdateCoordinator

class UpdateFailed(Exception):
    pass

sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = UpdateFailed

sys.modules["homeassistant.config_entries"].ConfigFlow = ConfigFlow
sys.modules["homeassistant.config_entries"].ConfigFlowResult = dict[str, Any]
sys.modules["homeassistant.config_entries"].ConfigEntry = MagicMock
sys.modules["homeassistant.config_entries"].ConfigEntry.__class_getitem__ = lambda cls, item: cls

sys.modules["homeassistant.core"].callback = lambda func: func
cv_mock = sys.modules["homeassistant.helpers.config_validation"]
cv_mock.string = str
cv_mock.multi_select = lambda options: lambda val: val
cv_mock.config_entry_only_config_schema = lambda domain: MagicMock()

ha_const = sys.modules["homeassistant.const"]
ha_const.CONF_USERNAME = "username"
ha_const.CONF_PASSWORD = "password"
ha_const.CONF_API_KEY = "api_key"
ha_const.Platform = MagicMock()
ha_const.Platform.BINARY_SENSOR = "binary_sensor"
ha_const.Platform.SELECT = "select"
ha_const.Platform.SENSOR = "sensor"
ha_const.Platform.VALVE = "valve"
ha_const.PERCENTAGE = "%"
ha_const.UnitOfVolume = MagicMock()
ha_const.UnitOfVolume.GALLONS = "gal"
ha_const.UnitOfPressure = MagicMock()
ha_const.UnitOfPressure.PSI = "psi"
ha_const.UnitOfTemperature = MagicMock()
ha_const.UnitOfTemperature.FAHRENHEIT = "°F"
ha_const.UnitOfTemperature.CELSIUS = "°C"
