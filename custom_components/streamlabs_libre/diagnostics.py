"""Diagnostics support for StreamLabs Libre."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_LOCATIONS
from .coordinator import StreamlabsConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_LOCATIONS,
    "unique_id",
    "title",
    "device_id",
    "device_name",
    "location_id",
    "location_name",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: StreamlabsConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "update_interval": str(coordinator.update_interval),
        "last_update_success": coordinator.last_update_success,
        "monitored_locations": len(coordinator.monitored_locations or coordinator.known_locations),
        "devices": [async_redact_data(asdict(dev), TO_REDACT) for dev in coordinator.data.values()],
    }
