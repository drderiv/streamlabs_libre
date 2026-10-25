"""Support for StreamLabs Libre Water Monitor and Valve devices."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .client import StreamLabsClient
from .const import CONF_LOCATIONS, DOMAIN
from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.VALVE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Entities that earlier versions created and which no longer exist
_OBSOLETE_ENTITY_SUFFIXES = ("_gallons_today", "_away_mode")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the StreamLabs Libre component."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> bool:
    """Set up StreamLabs Libre from a config entry."""
    client = await hass.async_add_executor_job(
        StreamLabsClient, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    coordinator = StreamlabsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _async_remove_stale_registry_entries(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.client.close)
    return unloaded


def _async_remove_stale_registry_entries(
    hass: HomeAssistant, entry: StreamlabsConfigEntry, coordinator: StreamlabsCoordinator
) -> None:
    """Drop devices that are no longer monitored, and entities that no longer exist."""
    dev_reg = dr.async_get(hass)
    for dev_entry in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        dev_ids = {ident for domain, ident in dev_entry.identifiers if domain == DOMAIN}
        if dev_ids and not dev_ids & coordinator.data.keys():
            # Removing the device also removes its entities
            dev_reg.async_remove_device(dev_entry.id)
            _LOGGER.info("Removed unmonitored StreamLabs device %s from registry", sorted(dev_ids))

    ent_reg = er.async_get(hass)
    for ent_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent_entry.unique_id.endswith(_OBSOLETE_ENTITY_SUFFIXES):
            ent_reg.async_remove(ent_entry.entity_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: StreamlabsConfigEntry, dev_entry: dr.DeviceEntry
) -> bool:
    """Let the user delete a device from the UI, which also stops monitoring its location."""
    coordinator = entry.runtime_data
    removed_locations = {
        coordinator.data[dev_id].location_id
        for domain, dev_id in dev_entry.identifiers
        if domain == DOMAIN and dev_id in coordinator.data
    }
    if not removed_locations:
        # Not currently provided by the integration, nothing to unmonitor
        return True

    monitored = coordinator.monitored_locations or set(coordinator.known_locations)
    remaining = monitored - removed_locations
    if not remaining:
        # Refuse to unmonitor the last location; remove the integration instead
        return False

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_LOCATIONS: sorted(remaining)}
    )
    _LOGGER.info("Updated monitored locations after device deletion to: %s", sorted(remaining))
    # Only the options flow reloads automatically; do it here so the device stops being polled
    hass.config_entries.async_schedule_reload(entry.entry_id)
    return True
