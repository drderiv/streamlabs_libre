"""Services for StreamLabs Libre."""

from __future__ import annotations

from typing import Final

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, Mode, ValvePosition
from .coordinator import StreamlabsCoordinator

ATTR_AWAY_MODE: Final = "away_mode"
ATTR_DEVICE_ID: Final = "device_id"
ATTR_POSITION: Final = "position"

SERVICE_SET_AWAY_MODE: Final = "set_away_mode"
SERVICE_SET_VALVE: Final = "set_valve"
SERVICE_RUN_DRIP_DETECT: Final = "run_drip_detect"
SERVICE_CALIBRATE: Final = "calibrate"

SET_AWAY_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_AWAY_MODE): vol.In(list(Mode)),
    }
)

SET_VALVE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_POSITION): vol.In(list(ValvePosition)),
    }
)

DEVICE_ACTION_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})


def _resolve_target(call: ServiceCall) -> tuple[StreamlabsCoordinator, str]:
    """Map a device registry id to its coordinator and StreamLabs device id."""
    device = dr.async_get(call.hass).async_get(call.data[ATTR_DEVICE_ID])
    streamlabs_ids = {
        ident for domain, ident in (device.identifiers if device else ()) if domain == DOMAIN
    }
    if not device or not streamlabs_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="device_not_found"
        )

    for entry_id in device.config_entries:
        entry = call.hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data, next(iter(streamlabs_ids))
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")


async def async_set_away_mode(call: ServiceCall) -> None:
    """Set the monitoring mode (home/away)."""
    coordinator, device_id = _resolve_target(call)
    await coordinator.async_client_call(
        coordinator.client.set_mode, device_id, call.data[ATTR_AWAY_MODE]
    )
    await coordinator.async_request_refresh()


async def async_set_valve(call: ServiceCall) -> None:
    """Actuate the shutoff valve."""
    coordinator, device_id = _resolve_target(call)
    await coordinator.async_client_call(
        coordinator.client.set_valve, device_id, call.data[ATTR_POSITION]
    )
    await coordinator.async_request_refresh()


async def async_run_drip_detect(call: ServiceCall) -> None:
    """Trigger a diagnostic drip detect test."""
    coordinator, device_id = _resolve_target(call)
    await coordinator.async_client_call(
        coordinator.client.send_command, device_id, "run drip detect"
    )
    await coordinator.async_request_refresh()


async def async_calibrate(call: ServiceCall) -> None:
    """Trigger device calibration."""
    coordinator, device_id = _resolve_target(call)
    await coordinator.async_client_call(coordinator.client.send_command, device_id, "calibrate")
    await coordinator.async_request_refresh()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register StreamLabs Libre services."""
    hass.services.async_register(
        DOMAIN, SERVICE_SET_AWAY_MODE, async_set_away_mode, schema=SET_AWAY_MODE_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_SET_VALVE, async_set_valve, schema=SET_VALVE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_RUN_DRIP_DETECT, async_run_drip_detect, schema=DEVICE_ACTION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALIBRATE, async_calibrate, schema=DEVICE_ACTION_SCHEMA
    )
