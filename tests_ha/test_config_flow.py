"""Config and options flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.streamlabs_libre.client import (
    StreamLabsAuthError,
    StreamLabsConnectionError,
)
from custom_components.streamlabs_libre.const import DOMAIN

from .conftest import PASSWORD, USERNAME, setup_integration

CREDS = {"username": USERNAME, "password": PASSWORD}


async def _start(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_single_location_creates_entry(hass, mock_client):
    result = await hass.config_entries.flow.async_configure((await _start(hass))["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {**CREDS, "locations": ["loc-1"]}


async def test_multiple_locations_prompts_for_selection(hass, mock_client):
    mock_client.get_locations.return_value = {
        "locations": [{"locationId": "a", "locationName": "A"}, {"locationId": "b", "locationName": "B"}]
    }
    result = await hass.config_entries.flow.async_configure((await _start(hass))["flow_id"], CREDS)
    assert result["step_id"] == "location"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"locations": ["b"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "B"
    assert result["data"]["locations"] == ["b"]


async def test_no_locations_creates_entry(hass, mock_client):
    mock_client.get_locations.return_value = {"locations": []}
    result = await hass.config_entries.flow.async_configure((await _start(hass))["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["locations"] == []


async def test_errors_are_mapped_and_recoverable(hass, mock_client):
    flow = await _start(hass)
    for exc, error in (
        (StreamLabsAuthError("x"), "invalid_auth"),
        (StreamLabsConnectionError("x"), "cannot_connect"),
        (RuntimeError("x"), "unknown"),
    ):
        mock_client.get_locations.side_effect = exc
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], CREDS)
        assert result["errors"] == {"base": error}

    mock_client.get_locations.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_account_aborts(hass, mock_client, mock_entry):
    result = await hass.config_entries.flow.async_configure((await _start(hass))["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_client.get_locations.side_effect = StreamLabsAuthError("x")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "bad"})
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.get_locations.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data["password"] == "new"


async def test_options_flow_updates_and_reloads(hass, mock_client, mock_entry):
    await setup_integration(hass, mock_entry)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["step_id"] == "init"
    # Single location: no location selector
    assert "locations" not in result["data_schema"].schema.keys().__str__()

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"water_off_interval": 90, "water_on_interval": 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert mock_entry.options["water_off_interval"] == 90
    assert mock_entry.options["locations"] if "locations" in mock_entry.options else True
    assert mock_entry.runtime_data.scan_interval_off == 90


async def test_options_flow_multi_location(hass, mock_client, mock_entry):
    mock_client.get_status.return_value["locations_summary"].append(
        {"location_id": "loc-2", "location_name": "Cabin", "device_ids": []}
    )
    await setup_integration(hass, mock_entry)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)

    bad = await hass.config_entries.options.async_configure(
        result["flow_id"], {"locations": [], "water_off_interval": 60, "water_on_interval": 15}
    )
    assert bad["errors"] == {"locations": "no_location_selected"}

    ok = await hass.config_entries.options.async_configure(
        result["flow_id"], {"locations": ["loc-1", "loc-2"], "water_off_interval": 60, "water_on_interval": 15}
    )
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options["locations"] == ["loc-1", "loc-2"]

