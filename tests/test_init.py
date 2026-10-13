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
