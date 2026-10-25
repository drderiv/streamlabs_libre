"""Integration tests against a real Home Assistant."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.streamlabs_libre.client import (
    StreamLabsAuthError,
    StreamLabsConnectionError,
)
from custom_components.streamlabs_libre.const import DOMAIN, MAX_STALE_POLLS

from .conftest import make_status, setup_integration

CONNECTIVITY = "binary_sensor.home_shutoff_connectivity"
FLOWING = "binary_sensor.home_shutoff_water_flowing"
DAILY = "sensor.home_shutoff_daily_water_usage"
PRESSURE = "sensor.home_shutoff_water_pressure"
VALVE = "valve.home_shutoff_water_valve"
MODE = "select.home_shutoff_monitoring_mode"


def _device(hass, device_id):
    devices = dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, device_id)})
    return devices[0] if devices else None


GALLON_IN_LITERS = 3.78541178


def _gallons(hass, entity_id):
    """State of a volume sensor in gallons (Home Assistant displays metric by default)."""
    return float(hass.states.get(entity_id).state) / GALLON_IN_LITERS


async def _refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_setup_creates_entities_and_unloads(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED

    assert _gallons(hass, DAILY) == pytest.approx(5.0)
    assert hass.states.get(VALVE).state == "open"
    assert hass.states.get(MODE).state == "home"
    assert hass.states.get(CONNECTIVITY).state == "on"
    assert hass.states.get(FLOWING).state == "off"
    # Zero is a real reading, not a missing one
    assert hass.states.get(PRESSURE).state == "0.0"
    # Entities that no longer exist
    assert hass.states.get("sensor.home_shutoff_gallons_today") is None
    assert hass.states.get("binary_sensor.home_shutoff_away_mode") is None

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.close.assert_called_once()


async def test_obsolete_registry_entities_are_removed(hass, mock_client, mock_entry):
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, "dev-1_gallons_today", config_entry=mock_entry, suggested_object_id="old"
    )
    await setup_integration(hass, mock_entry)
    assert ent_reg.async_get("sensor.old") is None


async def test_unmonitored_devices_are_removed(hass, mock_client, mock_entry):
    dev_reg = dr.async_get(hass)
    stale = dev_reg.async_get_or_create(
        config_entry_id=mock_entry.entry_id, identifiers={(DOMAIN, "gone")}
    )
    await setup_integration(hass, mock_entry)
    assert dev_reg.async_get(stale.id) is None
    assert _device(hass, "dev-1") is not None


async def test_auth_failure_starts_reauth(hass, mock_client, mock_entry):
    mock_client.get_status.side_effect = StreamLabsAuthError("bad")
    await setup_integration_unchecked(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


async def test_connection_failure_on_setup_retries(hass, mock_client, mock_entry):
    mock_client.get_status.side_effect = StreamLabsConnectionError("down")
    await setup_integration_unchecked(hass, mock_entry)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def setup_integration_unchecked(hass, entry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_outage_serves_stale_then_unavailable_then_recovers(hass, mock_client, mock_entry, caplog):
    await setup_integration(hass, mock_entry)
    mock_client.get_status.side_effect = StreamLabsConnectionError("down")

    for _ in range(MAX_STALE_POLLS):
        await _refresh(hass, mock_entry)
        assert _gallons(hass, DAILY) == pytest.approx(5.0)
    await _refresh(hass, mock_entry)
    assert hass.states.get(DAILY).state == STATE_UNAVAILABLE
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "serving last known" in r.message]
    assert len(warnings) == 1
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1

    mock_client.get_status.side_effect = None
    await _refresh(hass, mock_entry)
    assert _gallons(hass, DAILY) == pytest.approx(5.0)
    assert "connection restored" in caplog.text


async def test_auth_failure_after_setup_starts_reauth(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    mock_client.get_status.side_effect = StreamLabsAuthError("expired")
    await _refresh(hass, mock_entry)
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


async def test_connectivity_reports_off_when_disconnected(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    mock_client.get_status.return_value = make_status(connected=False)
    await _refresh(hass, mock_entry)

    assert hass.states.get(CONNECTIVITY).state == "off"
    assert hass.states.get(DAILY).state == STATE_UNAVAILABLE
    assert hass.states.get(VALVE).state == STATE_UNAVAILABLE


async def test_poll_interval_follows_flow(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    coordinator = mock_entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=60)

    mock_client.get_status.return_value = make_status(flowing=True)
    await _refresh(hass, mock_entry)
    assert hass.states.get(FLOWING).state == "on"
    assert coordinator.update_interval == timedelta(seconds=15)

    mock_client.get_status.return_value = make_status(flowing=False)
    await _refresh(hass, mock_entry)
    assert coordinator.update_interval == timedelta(seconds=60)


async def test_unmonitored_location_not_polled(hass, mock_client, mock_entry):
    hass.config_entries.async_update_entry(mock_entry, options={"locations": ["other"]})
    mock_client.get_status.return_value = make_status()
    # No devices at monitored locations on a non-empty account is a valid (empty) result
    await setup_integration(hass, mock_entry)
    assert hass.states.get(DAILY) is None
    mock_client.get_water_usage.assert_not_called()


async def test_options_are_read_from_real_config_entry(hass, mock_client, mock_entry):
    hass.config_entries.async_update_entry(
        mock_entry, options={"water_off_interval": 120, "water_on_interval": 20}
    )
    await setup_integration(hass, mock_entry)
    coordinator = mock_entry.runtime_data
    assert (coordinator.scan_interval_off, coordinator.scan_interval_on) == (120, 20)
    assert coordinator.update_interval == timedelta(seconds=120)


async def test_valve_actions(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)

    mock_client.get_status.return_value = make_status(valve="close")
    await hass.services.async_call("valve", "close_valve", {"entity_id": VALVE}, blocking=True)
    mock_client.set_valve.assert_called_once_with("dev-1", "close")
    assert hass.states.get(VALVE).state == "closed"


async def test_valve_failure_raises_home_assistant_error(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    mock_client.set_valve.side_effect = StreamLabsConnectionError("boom")
    with pytest.raises(HomeAssistantError, match="boom"):
        await hass.services.async_call("valve", "close_valve", {"entity_id": VALVE}, blocking=True)
    assert hass.states.get(VALVE).state == "open"


async def test_select_mode(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    assert hass.states.get(MODE).attributes["options"] == ["home", "away"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": MODE, "option": "away"}, blocking=True
    )
    mock_client.set_mode.assert_called_once_with("dev-1", "away")
    # Cloud still reports the old mode: the commanded one is shown meanwhile
    assert hass.states.get(MODE).state == "away"


async def test_services(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    device = _device(hass, "dev-1")

    await hass.services.async_call(
        DOMAIN, "set_valve", {"device_id": device.id, "position": "close"}, blocking=True
    )
    mock_client.set_valve.assert_called_with("dev-1", "close")
    await hass.services.async_call(
        DOMAIN, "set_away_mode", {"device_id": device.id, "away_mode": "away"}, blocking=True
    )
    mock_client.set_mode.assert_called_with("dev-1", "away")
    await hass.services.async_call(DOMAIN, "run_drip_detect", {"device_id": device.id}, blocking=True)
    mock_client.send_command.assert_called_with("dev-1", "run drip detect")
    await hass.services.async_call(DOMAIN, "calibrate", {"device_id": device.id}, blocking=True)
    mock_client.send_command.assert_called_with("dev-1", "calibrate")


async def test_service_validation_errors(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "calibrate", {"device_id": "nope"}, blocking=True)

    mock_client.send_command.side_effect = StreamLabsConnectionError("down")
    device = _device(hass, "dev-1")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "calibrate", {"device_id": device.id}, blocking=True)


async def test_device_removal_unmonitors_location(hass, mock_client, mock_entry):
    hass.config_entries.async_update_entry(mock_entry, options={"locations": ["loc-1", "loc-2"]})
    status = make_status()
    status["devices"].append({**status["devices"][0], "device_id": "dev-2", "location_id": "loc-2", "device_name": "Other"})
    mock_client.get_status.return_value = status
    await setup_integration(hass, mock_entry)

    from custom_components.streamlabs_libre import async_remove_config_entry_device

    dev_reg = dr.async_get(hass)
    other = _device(hass, "dev-2")
    assert await async_remove_config_entry_device(hass, mock_entry, other)
    assert mock_entry.options["locations"] == ["loc-1"]

    # The last remaining location cannot be removed
    await hass.async_block_till_done()
    first = _device(hass, "dev-1")
    assert not await async_remove_config_entry_device(hass, mock_entry, first)


async def test_diagnostics_redacts(hass, hass_client, mock_client, mock_entry):
    from custom_components.streamlabs_libre.diagnostics import async_get_config_entry_diagnostics

    await setup_integration(hass, mock_entry)
    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    text = str(diag)
    assert "secret" not in text
    assert "user@example.com" not in text
    assert "dev-1" not in text
    assert "Shutoff" not in text
    assert diag["devices"][0]["daily_usage"] == 5.0

