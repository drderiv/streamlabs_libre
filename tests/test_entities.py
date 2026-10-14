"""Tests for Streamlabs Libre entities."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.streamlabs_libre.binary_sensor import (
    BINARY_SENSORS,
    StreamlabsBinarySensor,
)
from custom_components.streamlabs_libre.const import (
    MODE_AWAY,
    MODE_HOME,
    VALVE_CLOSE,
    VALVE_OPEN,
)
from custom_components.streamlabs_libre.coordinator import StreamLabsDeviceData
from custom_components.streamlabs_libre.select import StreamlabsModeSelect
from custom_components.streamlabs_libre.sensor import SENSORS, StreamlabsSensor
from custom_components.streamlabs_libre.valve import StreamlabsValve


@pytest.fixture
def mock_coordinator():
    coord = MagicMock()
    coord.last_update_success = True
    coord.client = MagicMock()
    coord.async_request_refresh = AsyncMock()

    device_data = StreamLabsDeviceData(
        device_id="dev-test",
        device_name="Test Valve Device",
        location_id="loc-test",
        location_name="Test Location",
        connected=True,
        flowing=True,
        mode="home",
        has_valve=True,
        valve_position="open",
        daily_usage=12.5,
        monthly_usage=150.0,
        yearly_usage=1800.0,
        gallons_today=12.5,
        raw_status={},
        room_temp=72.5,
        room_humidity=45.0,
        water_pressure=55.2,
        water_temp=68.0,
    )
    coord.data = {"dev-test": device_data}
    return coord


def test_valve_properties(mock_coordinator):
    valve = StreamlabsValve(mock_coordinator, "dev-test")
    assert valve.is_closed is False
    assert valve.icon == "mdi:valve-open"
    assert valve.available is True

    # Test closed state
    mock_coordinator.data["dev-test"].valve_position = "close"
    assert valve.is_closed is True
    assert valve.icon == "mdi:valve-closed"


@pytest.mark.asyncio
async def test_valve_actions(mock_coordinator):
    valve = StreamlabsValve(mock_coordinator, "dev-test")
    valve.hass = MagicMock()
    valve.hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    await valve.async_close_valve()
    mock_coordinator.client.set_valve.assert_called_with("dev-test", VALVE_CLOSE)
    mock_coordinator.async_request_refresh.assert_called()

    await valve.async_open_valve()
    mock_coordinator.client.set_valve.assert_called_with("dev-test", VALVE_OPEN)


def test_mode_select_properties(mock_coordinator):
    mode_sel = StreamlabsModeSelect(mock_coordinator, "dev-test")
    assert mode_sel.current_option == "Home"
    assert mode_sel.icon == "mdi:home"

    mock_coordinator.data["dev-test"].mode = "away"
    assert mode_sel.current_option == "Away"
    assert mode_sel.icon == "mdi:home-export-outline"


@pytest.mark.asyncio
async def test_mode_select_action(mock_coordinator):
    mode_sel = StreamlabsModeSelect(mock_coordinator, "dev-test")
    mode_sel.hass = MagicMock()
    mode_sel.hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    await mode_sel.async_select_option("Away")
    mock_coordinator.client.set_mode.assert_called_with("dev-test", "away")
    mock_coordinator.async_request_refresh.assert_called()


def test_sensors(mock_coordinator):
    sensors_by_key = {desc.key: desc for desc in SENSORS}

    daily = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["daily_usage"])
    assert daily.native_value == 12.5
    assert daily.available is True

    monthly = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["monthly_usage"])
    assert monthly.native_value == 150.0

    yearly = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["yearly_usage"])
    assert yearly.native_value == 1800.0

    gallons_today = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["gallons_today"])
    assert gallons_today.native_value == 12.5

    room_humidity = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["room_humidity"])
    assert room_humidity.native_value == 45.0
    assert room_humidity.available is True

    room_temp = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["room_temp"])
    assert room_temp.native_value == 72.5
    assert room_temp.available is True

    water_pressure = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["water_pressure"])
    assert water_pressure.native_value == 55.2
    assert water_pressure.available is True

    water_temp = StreamlabsSensor(mock_coordinator, "dev-test", sensors_by_key["water_temp"])
    assert water_temp.native_value == 68.0
    assert water_temp.available is True

    # Test unavailable when sensor reading is None
    mock_coordinator.data["dev-test"].room_temp = None
    assert room_temp.native_value is None
    assert room_temp.available is False


def test_binary_sensors(mock_coordinator):
    bin_by_key = {desc.key: desc for desc in BINARY_SENSORS}

    flowing = StreamlabsBinarySensor(mock_coordinator, "dev-test", bin_by_key["flowing"])
    assert flowing.is_on is True

    conn = StreamlabsBinarySensor(mock_coordinator, "dev-test", bin_by_key["connectivity"])
    assert conn.is_on is True

    away = StreamlabsBinarySensor(mock_coordinator, "dev-test", bin_by_key["away_mode"])
    assert away.is_on is False

    # away_mode should be disabled by default to avoid duplication with mode select
    assert bin_by_key["away_mode"].entity_registry_enabled_default is False
    assert bin_by_key["flowing"].entity_registry_enabled_default is True
