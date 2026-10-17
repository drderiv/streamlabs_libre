"""Tests for Streamlabs Libre __init__.py setup and unload."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.streamlabs_libre import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.streamlabs_libre.const import CONF_LOCATIONS


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_async_setup(mock_hass):
    result = await async_setup(mock_hass, {})
    assert result is True
    assert mock_hass.services.async_register.call_count >= 1


@pytest.mark.asyncio
async def test_async_setup_entry(mock_hass):
    entry = MagicMock()
    entry.data = {
        "username": "user@example.com",
        "password": "secret_password",
        CONF_LOCATIONS: ["loc-1"],
    }

    with patch(
        "custom_components.streamlabs_libre.coordinator.StreamlabsCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ) as mock_refresh, patch(
        "custom_components.streamlabs_libre.client.Cognito"
    ):
        result = await async_setup_entry(mock_hass, entry)
        assert result is True
        mock_refresh.assert_called_once()
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once()
        assert entry.runtime_data is not None


@pytest.mark.asyncio
async def test_async_unload_entry(mock_hass):
    entry = MagicMock()
    result = await async_unload_entry(mock_hass, entry)
    assert result is True
    mock_hass.config_entries.async_unload_platforms.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_cleans_up_unmonitored_devices(mock_hass):
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    from custom_components.streamlabs_libre.const import DOMAIN
    from custom_components.streamlabs_libre import async_remove_config_entry_device

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "username": "user@example.com",
        "password": "secret_password",
        CONF_LOCATIONS: ["loc-1"],
    }

    mock_dev_reg = MagicMock()
    dr.async_get.return_value = mock_dev_reg

    mock_ent_reg = MagicMock()
    er.async_get.return_value = mock_ent_reg

    entry_monitored = MagicMock()
    entry_monitored.id = "reg_id_1"
    entry_monitored.identifiers = {(DOMAIN, "dev-1")}

    entry_stale = MagicMock()
    entry_stale.id = "reg_id_2"
    entry_stale.identifiers = {(DOMAIN, "dev-2")}

    dr.async_entries_for_config_entry.return_value = [entry_monitored, entry_stale]

    # Stale device has 2 entities in the entity registry
    stale_entity_1 = MagicMock()
    stale_entity_1.entity_id = "sensor.stale_flow_rate"
    stale_entity_2 = MagicMock()
    stale_entity_2.entity_id = "sensor.stale_daily_usage"
    er.async_entries_for_device.return_value = [stale_entity_1, stale_entity_2]

    async def mock_first_refresh(self):
        self.data = {"dev-1": MagicMock()}

    with patch(
        "custom_components.streamlabs_libre.coordinator.StreamlabsCoordinator.async_config_entry_first_refresh",
        new=mock_first_refresh,
    ), patch(
        "custom_components.streamlabs_libre.client.Cognito"
    ):
        result = await async_setup_entry(mock_hass, entry)
        assert result is True

        # Entities belonging to stale device must be purged
        assert mock_ent_reg.async_remove.call_count == 2
        mock_ent_reg.async_remove.assert_any_call("sensor.stale_flow_rate")
        mock_ent_reg.async_remove.assert_any_call("sensor.stale_daily_usage")

        # dev-2 (unchecked) must be removed from device registry
        mock_dev_reg.async_remove_device.assert_called_once_with("reg_id_2")

        # Verify async_remove_config_entry_device:
        # Manual UI deletion is allowed and pops device from coordinator data
        can_remove = await async_remove_config_entry_device(mock_hass, entry, entry_monitored)
        assert can_remove is True
        assert "dev-1" not in entry.runtime_data.data


@pytest.mark.asyncio
async def test_async_remove_config_entry_device_unmonitors_location(mock_hass):
    from custom_components.streamlabs_libre import async_remove_config_entry_device
    from custom_components.streamlabs_libre.const import CONF_LOCATIONS, DOMAIN

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {}

    mock_coordinator = MagicMock()
    dev_obj = MagicMock()
    dev_obj.location_id = "loc-np"
    dev_other = MagicMock()
    dev_other.location_id = "loc-pn"

    mock_coordinator.data = {"dev-np": dev_obj, "dev-pn": dev_other}
    mock_coordinator._cached_devices = {}
    mock_coordinator.monitored_locations = None
    mock_coordinator.client.get_status.return_value = {
        "locations_summary": [
            {"location_id": "loc-pn", "location_name": "PN"},
            {"location_id": "loc-np", "location_name": "NP"},
        ]
    }
    entry.runtime_data = mock_coordinator

    dev_entry = MagicMock()
    dev_entry.id = "ha_dev_np"
    dev_entry.identifiers = {(DOMAIN, "dev-np")}

    can_remove = await async_remove_config_entry_device(mock_hass, entry, dev_entry)
    assert can_remove is True
    assert "dev-np" not in mock_coordinator.data
    assert mock_coordinator.monitored_locations == {"loc-pn"}
    mock_hass.config_entries.async_update_entry.assert_called_once_with(
        entry, options={CONF_LOCATIONS: ["loc-pn"]}
    )

