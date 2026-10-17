"""Support for StreamLabs Libre Water Monitor and Valve devices."""

from __future__ import annotations

from .client import StreamLabsClient
from .const import DOMAIN

try:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import config_validation as cv, device_registry as dr

    from .const import DOMAIN, LOGGER
    from .coordinator import StreamlabsConfigEntry, StreamlabsCoordinator
    from .services import async_setup_services

    PLATFORMS: list[Platform] = [
        Platform.BINARY_SENSOR,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.VALVE,
    ]

    CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
except ImportError:
    # Allows importing client.py standalone without requiring Home Assistant
    PLATFORMS = []  # type: ignore[assignment]
    CONFIG_SCHEMA = None  # type: ignore[assignment]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the StreamLabs Libre component."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> bool:
    """Set up StreamLabs Libre from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    client = await hass.async_add_executor_job(StreamLabsClient, username, password)
    coordinator = StreamlabsCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Remove stale/unmonitored devices from device registry
    try:
        dev_reg = dr.async_get(hass)
        for dev_entry in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            for domain, dev_id in dev_entry.identifiers:
                if domain == DOMAIN and dev_id not in coordinator.data:
                    dev_reg.async_remove_device(dev_entry.id)
                    LOGGER.info("Removed unmonitored StreamLabs device %s from registry", dev_id)
                    break
    except Exception as err:
        LOGGER.debug("Could not clean up stale devices: %s", err)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> None:
    """Reload integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
