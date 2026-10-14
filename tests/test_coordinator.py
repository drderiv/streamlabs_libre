"""Tests for StreamlabsCoordinator."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.streamlabs_libre.client import StreamLabsClient, StreamLabsError
from custom_components.streamlabs_libre.const import CONF_LOCATIONS
from custom_components.streamlabs_libre.coordinator import (
    StreamlabsCoordinator,
    StreamLabsDeviceData,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


@pytest.fixture
def mock_client():
    client = MagicMock(spec=StreamLabsClient)
    return client


def test_coordinator_extract_usage(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    # Format 1: Direct summary
    d, m, y = coordinator._extract_usage({"today": 10.5, "thisMonth": 100.2, "thisYear": 1200.0})
    assert d == 10.5
    assert m == 100.2
    assert y == 1200.0

    # Format 2: Comparative
    d, m, y = coordinator._extract_usage({
        "day": {"todayTotal": 7.8},
        "month": {"thisMonthTotal": 85.0},
        "year": {"thisYearTotal": 950.0},
    })
    assert d == 7.8
    assert m == 85.0
    assert y == 950.0

    # Format 3: Array of data points
    d, m, y = coordinator._extract_usage({"data": [{"volume": 2.1}, {"volume": 3.4}]})
    assert abs(d - 5.5) < 0.001
    assert m == 0.0
    assert y == 0.0

    # Format 4: Flat comparative keys
    d, m, y = coordinator._extract_usage({"todayTotal": 8.0, "thisMonthTotal": 80.0, "thisYearTotal": 800.0})
    assert d == 8.0
    assert m == 80.0
    assert y == 800.0

    # Format 5: Logical fallback when year is 0.0 but month is positive
    d, m, y = coordinator._extract_usage({"today": 5.0, "thisMonth": 50.0, "thisYear": 0.0})
    assert d == 5.0
    assert m == 50.0
    assert y == 50.0


def test_coordinator_update_data_filtering(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {CONF_LOCATIONS: ["loc-allowed"]}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-allowed",
                "location_name": "Main Home",
                "device_id": "dev-01",
                "device_name": "Control Valve",
                "connected": True,
                "flowing": False,
                "mode": "home",
                "has_valve": True,
                "valve_position": "open",
                "gallons_today": 25.0,
            },
            {
                "location_id": "loc-ignored",
                "location_name": "Vacation Home",
                "device_id": "dev-02",
                "device_name": "Ignored Device",
                "connected": True,
                "flowing": False,
                "mode": "away",
                "has_valve": False,
                "valve_position": None,
                "gallons_today": 5.0,
            },
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 25.0, "thisMonth": 200.0, "thisYear": 1000.0}

    data = coordinator._update_data()
    assert len(data) == 1
    assert "dev-01" in data
    assert "dev-02" not in data
    dev_data = data["dev-01"]
    assert dev_data.device_name == "Control Valve"
    assert dev_data.daily_usage == 25.0
    assert dev_data.valve_position == "open"
    assert dev_data.has_valve is True


def test_coordinator_update_data_fallback_gallons_today(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "location_name": "Main Home",
                "device_id": "dev-01",
                "device_name": "Monitor",
                "connected": True,
                "flowing": True,
                "mode": "home",
                "has_valve": False,
                "valve_position": None,
                "gallons_today": 33.3,
            }
        ]
    }
    mock_client.get_water_usage.side_effect = StreamLabsError("Endpoint unavailable")

    data = coordinator._update_data()
    assert "dev-01" in data
    assert data["dev-01"].daily_usage == 33.3
    assert data["dev-01"].flowing is True


def test_coordinator_environmental_telemetry(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "location_name": "Main Home",
                "device_id": "dev-01",
                "device_name": "Main Valve",
                "connected": True,
                "flowing": False,
                "mode": "home",
                "has_valve": True,
                "valve_position": "open",
                "gallons_today": 10.0,
            }
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 10.0}
    mock_client.get_device.return_value = {
        "deviceId": "dev-01",
        "ambientTemp": {"currentValue": 74},
        "humidity": {"currentValue": 48},
        "waterPressure": {"currentValue": 58},
        "waterTemp": {"currentValue": 65},
    }

    data = coordinator._update_data()
    assert "dev-01" in data
    dev = data["dev-01"]
    assert dev.room_temp == 74.0
    assert dev.room_humidity == 48.0
    assert dev.water_pressure == 58.0
    assert dev.water_temp == 65.0


def test_coordinator_rolling_yearly_usage(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "location_name": "Main Home",
                "device_id": "dev-01",
                "device_name": "Main Valve",
                "connected": True,
                "flowing": False,
                "mode": "home",
                "has_valve": True,
                "valve_position": "open",
                "gallons_today": 12.0,
            }
        ]
    }
    mock_client.get_device.return_value = {"deviceId": "dev-01"}

    def mock_get_water_usage(device_id, date_str=None, period=None, rolling=None):
        if period is not None and rolling is True:
            return {
                "tz": "America/Los_Angeles",
                "unit": "gal",
                "startTime": 1728864000,
                "interval": "month",
                "data": [
                    3000.0, 3100.0, 3200.0, 2900.0, 3050.0, 3150.0,
                    3300.0, 3100.0, 3000.0, 3200.0, 3100.0, 2800.0, 2927.0,
                ],
            }
        return {"today": 12.0, "thisMonth": 2927.0, "thisYear": 0.0}

    mock_client.get_water_usage.side_effect = mock_get_water_usage

    data = coordinator._update_data()
    assert "dev-01" in data
    dev = data["dev-01"]
    assert dev.daily_usage == 12.0
    assert dev.monthly_usage == 2927.0
    # Sum of 13 months is exactly 39827.0 (matching the app's value!)
    assert dev.yearly_usage == 39827.0
    assert dev.yearly_used_since is not None
    assert len(dev.monthly_history) == 13


