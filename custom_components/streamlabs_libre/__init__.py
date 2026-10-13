"""Support for StreamLabs Libre Water Monitor and Valve devices."""

from __future__ import annotations

from .const import DOMAIN

try:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers.typing import ConfigType

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

    client = StreamLabsClient(username, password)
    coordinator = StreamlabsCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
