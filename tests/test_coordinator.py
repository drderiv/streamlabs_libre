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
    assert dev.monthly_history[-1] == 2927.0

    # Second poll: Endpoint #3 should NOT be called (cached), but current month increases to 2950.0
    mock_client.get_water_usage.reset_mock()

    def mock_get_water_usage_second_poll(device_id, date_str=None, period=None, rolling=None):
        if period is not None and rolling is True:
            pytest.fail("Endpoint #3 should not be called when cached within 1 hour")
        return {"today": 35.0, "thisMonth": 2950.0, "thisYear": 0.0}

    mock_client.get_water_usage.side_effect = mock_get_water_usage_second_poll

    data2 = coordinator._update_data()
    dev2 = data2["dev-01"]
    # Endpoint #2 was called, endpoint #3 was skipped:
    assert mock_client.get_water_usage.call_count == 1
    assert dev2.monthly_usage == 2950.0
    # Last element of monthly_history dynamically updated to 2950.0:
    assert dev2.monthly_history[-1] == 2950.0
    # Yearly usage dynamically updated from 39827.0 to 39850.0:
    assert dev2.yearly_usage == 39850.0


def test_coordinator_dynamic_intervals_and_flow_rate(mock_hass, mock_client):
    from datetime import timedelta
    from custom_components.streamlabs_libre.const import (
        CONF_WATER_OFF_INTERVAL,
        CONF_WATER_ON_INTERVAL,
    )

    entry = MagicMock()
    entry.options = {
        CONF_WATER_OFF_INTERVAL: 60,
        CONF_WATER_ON_INTERVAL: 10,
    }
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    assert coordinator.scan_interval_off == 60
    assert coordinator.scan_interval_on == 10
    assert coordinator.update_interval == timedelta(seconds=60)

    # 1. First poll: Water is OFF (flowing == False)
    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "device_id": "dev-01",
                "connected": True,
                "flowing": False,
                "gallons_today": 10.0,
            }
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 10.0, "thisMonth": 100.0, "thisYear": 500.0}
    mock_client.get_device.return_value = {"deviceId": "dev-01", "ambientTemp": {"currentValue": 70}}

    with patch("time.monotonic", return_value=1000.0):
        data1 = coordinator._update_data()

    assert data1["dev-01"].flowing is False
    assert data1["dev-01"].estimated_flow_rate == 0.0
    assert coordinator.update_interval == timedelta(seconds=60)
    assert mock_client.get_device.call_count == 1

    # 2. Second poll: Water turns ON (flowing == True) - First poll transition
    # Captures initial usage, reports 0.0 gpm; interval switches to 10s
    mock_client.get_status.return_value["devices"][0]["flowing"] = True
    mock_client.get_water_usage.return_value["today"] = 10.0

    with patch("time.monotonic", return_value=1060.0):
        data2 = coordinator._update_data()

    assert data2["dev-01"].flowing is True
    assert data2["dev-01"].estimated_flow_rate == 0.0  # Initial flow detected
    assert coordinator.update_interval == timedelta(seconds=10)
    # 60s elapsed since t=1000.0, so get_device was called again
    assert mock_client.get_device.call_count == 2

    # 3. Third poll: Cloud pre-sync backlog flushes (+2.0 gal jump)
    # Absorbs the backlog spike without calculating an erroneous spike rate; re-baselines here
    mock_client.get_water_usage.return_value["today"] = 12.0

    with patch("time.monotonic", return_value=1070.0):
        data3 = coordinator._update_data()

    assert data3["dev-01"].flowing is True
    assert data3["dev-01"].estimated_flow_rate == 0.0  # Backlog spike absorbed!
    assert coordinator.update_interval == timedelta(seconds=10)
    # Only 10s elapsed since t=1060.0 (< 60s waterOff interval), so get_device was CACHED!
    assert mock_client.get_device.call_count == 2

    # 4. Fourth poll: Water still ON 10s later; daily usage increased by 0.5 gal
    # delta_time = 10s = 0.1667 min. delta_gallons = 0.5 gal.
    # gpm = 0.5 / (10/60) = 3.0 gpm
    mock_client.get_water_usage.return_value["today"] = 12.5

    with patch("time.monotonic", return_value=1080.0):
        data4 = coordinator._update_data()

    assert data4["dev-01"].flowing is True
    assert data4["dev-01"].estimated_flow_rate == 3.0
    assert coordinator.update_interval == timedelta(seconds=10)

    # 5. Fifth poll: 10s later, steady flow +0.5 gal (now 2-poll moving window is active)
    # delta_time = 20s (2x waterOn interval). delta_gallons = 13.0 - 12.0 = 1.0 gal.
    # gpm = 1.0 / (20/60) = 3.0 gpm
    mock_client.get_water_usage.return_value["today"] = 13.0

    with patch("time.monotonic", return_value=1090.0):
        data5 = coordinator._update_data()

    assert data5["dev-01"].flowing is True
    assert data5["dev-01"].estimated_flow_rate == 3.0

    # 6. Sixth poll: Water turns OFF (flowing == False)
    mock_client.get_status.return_value["devices"][0]["flowing"] = False
    mock_client.get_water_usage.return_value["today"] = 13.0

    with patch("time.monotonic", return_value=1100.0):
        data6 = coordinator._update_data()

    assert data6["dev-01"].flowing is False
    assert data6["dev-01"].estimated_flow_rate == 0.0
    assert coordinator.update_interval == timedelta(seconds=60)


def test_coordinator_flow_rate_jitter_smoothing(mock_hass, mock_client):
    """Test that a 2-poll moving window (2x waterOn interval) smooths quantization jitter."""
    from custom_components.streamlabs_libre.const import (
        CONF_WATER_OFF_INTERVAL,
        CONF_WATER_ON_INTERVAL,
    )

    entry = MagicMock()
    entry.options = {
        CONF_WATER_OFF_INTERVAL: 60,
        CONF_WATER_ON_INTERVAL: 15,
    }
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "device_id": "dev-01",
                "connected": True,
                "flowing": True,
                "gallons_today": 100.0,
            }
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 100.0}
    mock_client.get_device.return_value = {"deviceId": "dev-01"}

    # 1. Flow starts, initial reading recorded
    with patch("time.monotonic", return_value=1000.0):
        d1 = coordinator._update_data()
    assert d1["dev-01"].estimated_flow_rate == 0.0

    # 2. Cloud sync backlog flushes: jumps from 100.0 to 103.3
    # Absorbed with 0.0 gpm; baseline established at 103.3
    mock_client.get_water_usage.return_value["today"] = 103.3
    with patch("time.monotonic", return_value=1015.0):
        d2 = coordinator._update_data()
    assert d2["dev-01"].estimated_flow_rate == 0.0

    # 3. First regular interval: +0.625 gal in 15s (2.5 gpm)
    mock_client.get_water_usage.return_value["today"] = 103.925
    with patch("time.monotonic", return_value=1030.0):
        d3 = coordinator._update_data()
    assert d3["dev-01"].estimated_flow_rate == 2.5

    # 4. Jitter poll 1: cloud buffer delays packet; only +0.475 gal arrives (single-poll would say 1.9 gpm)
    # But 2-poll window over 30s: (104.40 - 103.3) / 0.5 min = 1.1 / 0.5 = 2.2 gpm (smoothed!)
    mock_client.get_water_usage.return_value["today"] = 104.40
    with patch("time.monotonic", return_value=1045.0):
        d4 = coordinator._update_data()
    assert d4["dev-01"].estimated_flow_rate == 2.2

    # 5. Jitter poll 2: cloud catches up with remainder (+0.775 gal; single-poll would spike to 3.1 gpm)
    # But 2-poll window over 30s: (105.175 - 103.925) / 0.5 min = 1.25 / 0.5 = 2.5 gpm (exact steady rate!)
    mock_client.get_water_usage.return_value["today"] = 105.175
    with patch("time.monotonic", return_value=1060.0):
        d5 = coordinator._update_data()
    assert d5["dev-01"].estimated_flow_rate == 2.5


@pytest.mark.asyncio
async def test_coordinator_initial_failure_raises_update_failed(mock_hass, mock_client):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)
    mock_client.get_status.side_effect = StreamLabsError("Initial connection failure")

    with pytest.raises(UpdateFailed, match="Error communicating with StreamLabs API"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_preserves_state_on_transient_error(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    # First poll succeeds
    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "device_id": "dev-01",
                "device_name": "Main Water Monitor",
                "connected": True,
                "flowing": False,
                "gallons_today": 15.0,
            }
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 15.0, "thisMonth": 150.0, "thisYear": 1500.0}
    mock_client.get_device.return_value = {"deviceId": "dev-01", "ambientTemp": {"currentValue": 72}}

    data = await coordinator._async_update_data()
    assert "dev-01" in data
    assert data["dev-01"].daily_usage == 15.0
    assert "dev-01" in coordinator._cached_devices

    # Second poll encounters upstream outage (e.g. HTTP 500 or ConnectionError)
    mock_client.get_status.side_effect = StreamLabsError("500 Internal Server Error")

    data_during_outage = await coordinator._async_update_data()
    # State MUST be preserved, not wiped or flapped!
    assert "dev-01" in data_during_outage
    assert data_during_outage["dev-01"].daily_usage == 15.0
    assert data_during_outage["dev-01"].device_name == "Main Water Monitor"


@pytest.mark.asyncio
async def test_coordinator_preserves_state_on_empty_payload(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    # First poll succeeds
    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "device_id": "dev-01",
                "connected": True,
                "flowing": False,
                "gallons_today": 20.0,
            }
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 20.0, "thisMonth": 200.0, "thisYear": 2000.0}
    mock_client.get_device.return_value = {"deviceId": "dev-01"}

    data = await coordinator._async_update_data()
    assert "dev-01" in data

    # Cloud returns empty devices list
    mock_client.get_status.return_value = {"devices": []}
    data_empty = await coordinator._async_update_data()

    # Must preserve cached device state
    assert "dev-01" in data_empty
    assert data_empty["dev-01"].daily_usage == 20.0


@pytest.mark.asyncio
async def test_coordinator_log_spam_throttling_and_recovery(mock_hass, mock_client):
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    # Initial successful poll to populate cache
    mock_client.get_status.return_value = {
        "devices": [{"location_id": "loc-1", "device_id": "dev-01", "connected": True, "flowing": False}]
    }
    mock_client.get_water_usage.return_value = {"today": 5.0}
    mock_client.get_device.return_value = {"deviceId": "dev-01"}
    await coordinator._async_update_data()

    # Outage starts
    mock_client.get_status.side_effect = StreamLabsError("Gateway timeout")

    with patch("custom_components.streamlabs_libre.coordinator.LOGGER") as mock_logger:
        # Attempt 1: Warning
        await coordinator._async_update_data()
        assert coordinator._consecutive_failures == 1
        assert mock_logger.warning.call_count == 1

        # Attempt 2: Warning
        await coordinator._async_update_data()
        assert coordinator._consecutive_failures == 2
        assert mock_logger.warning.call_count == 2

        # Attempt 3: Warning
        await coordinator._async_update_data()
        assert coordinator._consecutive_failures == 3
        assert mock_logger.warning.call_count == 3

        # Attempt 4: Suppressed to DEBUG, warning count unchanged!
        await coordinator._async_update_data()
        assert coordinator._consecutive_failures == 4
        assert mock_logger.warning.call_count == 3
        assert any("StreamLabs API outage ongoing" in str(c[0][0]) for c in mock_logger.debug.call_args_list)

        # Attempt 5: Still throttled
        await coordinator._async_update_data()
        assert coordinator._consecutive_failures == 5
        assert mock_logger.warning.call_count == 3

        # Outage recovers!
        mock_client.get_status.side_effect = None
        await coordinator._async_update_data()
        assert coordinator._consecutive_failures == 0
        assert any(
            "StreamLabs cloud connection restored after %d failed attempt(s)" in str(c[0][0]) and c[0][1] == 5
            for c in mock_logger.info.call_args_list
        )


def test_coordinator_deadlock_prevention_auxiliary_failure_backoff(mock_hass, mock_client):
    """Test that failure in auxiliary fetch (endpoint #3 / #4) backs off and does not starve routine polling."""
    entry = MagicMock()
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    mock_client.get_status.return_value = {
        "devices": [{"location_id": "loc-1", "device_id": "dev-01", "connected": True, "flowing": True}]
    }
    mock_client.get_water_usage.side_effect = [
        {"today": 10.0},  # endpoint #2 succeeds
        StreamLabsError("Endpoint #3 failed"),  # endpoint #3 fails
    ]
    mock_client.get_device.side_effect = StreamLabsError("Endpoint #4 failed")

    with patch("time.monotonic", return_value=1000.0):
        data = coordinator._update_data()

    assert "dev-01" in data
    # Both auxiliary endpoints must have had their last_fetched timestamp recorded to back off
    assert coordinator._yearly_cache["dev-01"]["last_fetched"] == 1000.0
    assert coordinator._telemetry_cache["dev-01"]["last_fetched"] == 1000.0

    # Next poll 10s later (within backoff window):
    # Auxiliary endpoints #3 and #4 MUST NOT be called again, allowing routine polling to proceed smoothly!
    mock_client.get_water_usage.reset_mock()
    mock_client.get_device.reset_mock()
    mock_client.get_water_usage.side_effect = None
    mock_client.get_water_usage.return_value = {"today": 10.1}

    with patch("time.monotonic", return_value=1010.0):
        data2 = coordinator._update_data()

    assert "dev-01" in data2
    # Only endpoint #2 was called; endpoint #3 and #4 were backed off!
    assert mock_client.get_water_usage.call_count == 1
    assert mock_client.get_device.call_count == 0


def test_coordinator_unselected_locations_are_not_polled(mock_hass, mock_client):
    """Verify that devices at unchecked locations generate NO auxiliary polling requests."""
    entry = MagicMock()
    # User checked only "loc-checked" in Configuration dialog
    entry.options = {CONF_LOCATIONS: ["loc-checked"]}
    entry.data = {}
    coordinator = StreamlabsCoordinator(mock_hass, entry, mock_client)

    # Cloud account has 3 leak detectors across 3 locations
    mock_client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-checked",
                "location_name": "Main Home",
                "device_id": "detector-checked",
                "device_name": "Main Monitor",
                "connected": True,
                "flowing": False,
                "gallons_today": 12.0,
            },
            {
                "location_id": "loc-unchecked-1",
                "location_name": "Beach House",
                "device_id": "detector-unchecked-1",
                "device_name": "Beach Monitor",
                "connected": True,
                "flowing": True,
                "gallons_today": 45.0,
            },
            {
                "location_id": "loc-unchecked-2",
                "location_name": "Rental Unit",
                "device_id": "detector-unchecked-2",
                "device_name": "Rental Monitor",
                "connected": True,
                "flowing": False,
                "gallons_today": 2.0,
            },
        ]
    }
    mock_client.get_water_usage.return_value = {"today": 12.0, "thisMonth": 100.0, "thisYear": 500.0}
    mock_client.get_device.return_value = {"deviceId": "detector-checked"}

    data = coordinator._update_data()

    # 1. Only the checked detector is in coordinator data
    assert len(data) == 1
    assert "detector-checked" in data
    assert "detector-unchecked-1" not in data
    assert "detector-unchecked-2" not in data

    # 2. Auxiliary polling endpoints were ONLY called for the checked detector!
    usage_called_ids = [call[0][0] for call in mock_client.get_water_usage.call_args_list]
    device_called_ids = [call[0][0] for call in mock_client.get_device.call_args_list]

    assert all(d_id == "detector-checked" for d_id in usage_called_ids)
    assert all(d_id == "detector-checked" for d_id in device_called_ids)

    # ZERO auxiliary calls made for unchecked detectors
    assert "detector-unchecked-1" not in usage_called_ids
    assert "detector-unchecked-2" not in usage_called_ids
    assert "detector-unchecked-1" not in device_called_ids
    assert "detector-unchecked-2" not in device_called_ids



