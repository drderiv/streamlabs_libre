"""Fixtures for tests that run against a real Home Assistant (see Dockerfile)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.streamlabs_libre.const import CONF_LOCATIONS, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

USERNAME = "user@example.com"
PASSWORD = "secret"


def make_status(*, connected=True, flowing=False, mode="home", valve="open", loc="loc-1", dev="dev-1"):
    """Build the flattened structure StreamLabsClient.get_status() returns."""
    return {
        "devices": [
            {
                "location_id": loc,
                "location_name": "Home",
                "device_id": dev,
                "device_name": "Shutoff",
                "connected": connected,
                "flowing": flowing,
                "mode": mode,
                "has_valve": True,
                "valve_position": valve,
                "gallons_today": 12.0,
                "ambient_temp": None,
                "humidity": None,
                "water_pressure": None,
                "water_temp": None,
            }
        ],
        "locations_summary": [{"location_id": loc, "location_name": "Home", "device_ids": [dev]}],
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from /custom_components."""
    yield


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch the StreamLabsClient class used by the integration and the config flow."""
    with (
        patch("custom_components.streamlabs_libre.StreamLabsClient") as cls,
        patch("custom_components.streamlabs_libre.config_flow.StreamLabsClient", cls),
    ):
        client = cls.return_value
        client.get_status.return_value = make_status()
        client.get_locations.return_value = {
            "locations": [{"locationId": "loc-1", "locationName": "Home"}]
        }
        client.get_water_usage.return_value = {"day": {"todayTotal": 5.0}, "month": {"total": 50.0}}
        client.get_device.return_value = {"waterPressure": 0, "ambientTemp": 68.5, "humidity": 40}
        client.set_valve.return_value = True
        client.set_mode.return_value = True
        client.send_command.return_value = True
        yield client


@pytest.fixture
def mock_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=USERNAME,
        data={"username": USERNAME, "password": PASSWORD, CONF_LOCATIONS: ["loc-1"]},
    )
    entry.add_to_hass(hass)
    return entry


async def setup_integration(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
