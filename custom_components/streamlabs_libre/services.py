"""Services for StreamLabs Libre."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    LOGGER,
    MODE_AWAY,
    MODE_HOME,
    VALID_MODES,
    VALID_VALVE_POSITIONS,
    VALVE_CLOSE,
    VALVE_OPEN,
)

ATTR_AWAY_MODE = "away_mode"
ATTR_DEVICE_ID = "device_id"
ATTR_POSITION = "position"

SERVICE_SET_AWAY_MODE = "set_away_mode"
SERVICE_SET_VALVE = "set_valve"
SERVICE_RUN_DRIP_DETECT = "run_drip_detect"
SERVICE_CALIBRATE = "calibrate"

SET_AWAY_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_AWAY_MODE): vol.In(VALID_MODES),
        vol.Optional(ATTR_DEVICE_ID): cv.string,
    }
)

SET_VALVE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_POSITION): vol.In(VALID_VALVE_POSITIONS),
        vol.Optional(ATTR_DEVICE_ID): cv.string,
    }
)

DEVICE_ACTION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): cv.string,
    }
)


def _get_target_device_id(call: ServiceCall) -> tuple[Any, str]:
    """Helper to locate coordinator and target device id."""
    entries = call.hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("No StreamLabs Libre config entries found.")

    entry = entries[0]
    coordinator = entry.runtime_data
    device_id = call.data.get(ATTR_DEVICE_ID)

    if not device_id:
        if not coordinator.data:
            raise ValueError("No StreamLabs devices available.")
        device_id = next(iter(coordinator.data.keys()))

    return coordinator, device_id


async def async_set_away_mode(call: ServiceCall) -> None:
    """Set the monitoring mode (home/away)."""
    coordinator, device_id = _get_target_device_id(call)
    mode = call.data[ATTR_AWAY_MODE]
    await call.hass.async_add_executor_job(coordinator.client.set_mode, device_id, mode)
    await coordinator.async_request_refresh()


async def async_set_valve(call: ServiceCall) -> None:
    """Actuate the shutoff valve."""
    coordinator, device_id = _get_target_device_id(call)
    position = call.data[ATTR_POSITION]
    await call.hass.async_add_executor_job(coordinator.client.set_valve, device_id, position)
    await coordinator.async_request_refresh()


async def async_run_drip_detect(call: ServiceCall) -> None:
    """Trigger a diagnostic drip detect test."""
    coordinator, device_id = _get_target_device_id(call)
    await call.hass.async_add_executor_job(
        coordinator.client.send_command, device_id, "run drip detect"
    )
    await coordinator.async_request_refresh()


async def async_calibrate(call: ServiceCall) -> None:
    """Trigger device calibration."""
    coordinator, device_id = _get_target_device_id(call)
    await call.hass.async_add_executor_job(
        coordinator.client.send_command, device_id, "calibrate"
    )
    await coordinator.async_request_refresh()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register StreamLabs Libre services."""
    hass.services.async_register(
        DOMAIN, SERVICE_SET_AWAY_MODE, async_set_away_mode, schema=SET_AWAY_MODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_VALVE, async_set_valve, schema=SET_VALVE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RUN_DRIP_DETECT, async_run_drip_detect, schema=DEVICE_ACTION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALIBRATE, async_calibrate, schema=DEVICE_ACTION_SCHEMA
    )
