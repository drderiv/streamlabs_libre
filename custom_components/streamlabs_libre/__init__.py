"""Support for StreamLabs Libre Water Monitor and Valve devices."""

from __future__ import annotations

from .client import StreamLabsClient
from .const import DOMAIN

try:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import (
        config_validation as cv,
        device_registry as dr,
        entity_registry as er,
    )

    from .const import CONF_LOCATIONS, DOMAIN, LOGGER
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

    # Remove stale/unmonitored devices and associated entities from registries
    try:
        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)
        for dev_entry in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            for domain, dev_id in dev_entry.identifiers:
                if domain == DOMAIN and dev_id not in coordinator.data:
                    # Remove all entity registry entries belonging to this device
                    for ent_entry in er.async_entries_for_device(ent_reg, dev_entry.id):
                        ent_reg.async_remove(ent_entry.entity_id)
                        LOGGER.info(
                            "Removed unmonitored entity %s for device %s from registry",
                            ent_entry.entity_id,
                            dev_id,
                        )
                    dev_reg.async_remove_device(dev_entry.id)
                    LOGGER.info("Removed unmonitored StreamLabs device %s from registry", dev_id)
                    break
    except Exception as err:
        LOGGER.warning("Could not clean up stale devices: %s", err)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: StreamlabsConfigEntry, dev_entry: dr.DeviceEntry
) -> bool:
    """Allow user to remove a device directly from the UI and unmonitor its location."""
    coordinator = getattr(entry, "runtime_data", None)
    LOGGER.warning(
        "User manually requested deletion of device %s (identifiers=%s). Currently monitored devices: %s",
        dev_entry.id,
        dev_entry.identifiers,
        list(coordinator.data.keys()) if (coordinator and hasattr(coordinator, "data")) else None,
    )
    removed_loc_ids: set[str] = set()
    if coordinator and hasattr(coordinator, "data"):
        for domain, dev_id in dev_entry.identifiers:
            if domain == DOMAIN:
                dev_obj = coordinator.data.get(dev_id)
                if not dev_obj and hasattr(coordinator, "_cached_devices"):
                    dev_obj = coordinator._cached_devices.get(dev_id)
                if dev_obj and hasattr(dev_obj, "location_id") and dev_obj.location_id:
                    removed_loc_ids.add(str(dev_obj.location_id))
                coordinator.data.pop(dev_id, None)
                if hasattr(coordinator, "_cached_devices"):
                    coordinator._cached_devices.pop(dev_id, None)

    # If we identified which location this device belonged to, update entry.options so it remains unmonitored
    if coordinator and removed_loc_ids:
        all_account_locs: set[str] = set()
        if hasattr(coordinator, "client"):
            try:
                resp = await hass.async_add_executor_job(coordinator.client.get_status)
                for loc in resp.get("locations_summary", []):
                    raw_id = loc.get("location_id") or loc.get("locationId")
                    if raw_id:
                        all_account_locs.add(str(raw_id))
            except Exception:
                pass
        if not all_account_locs:
            for d in list(coordinator.data.values()) + list(getattr(coordinator, "_cached_devices", {}).values()):
                if hasattr(d, "location_id") and d.location_id:
                    all_account_locs.add(str(d.location_id))

        current_monitored = (
            set(coordinator.monitored_locations)
            if coordinator.monitored_locations is not None
            else all_account_locs
        )
        remaining_monitored = current_monitored - removed_loc_ids
        if remaining_monitored:
            coordinator.monitored_locations = remaining_monitored
            new_opts = dict(entry.options or {})
            new_opts[CONF_LOCATIONS] = list(remaining_monitored)
            hass.config_entries.async_update_entry(entry, options=new_opts)
            LOGGER.warning(
                "Updated monitored locations after device deletion to: %s",
                new_opts[CONF_LOCATIONS],
            )

    return True


async def update_listener(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> None:
    """Reload integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StreamlabsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
