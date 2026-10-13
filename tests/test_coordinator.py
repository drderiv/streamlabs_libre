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
