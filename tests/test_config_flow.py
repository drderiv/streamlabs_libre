"""Tests for StreamlabsConfigFlow."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.streamlabs_libre.client import (
    StreamLabsAuthError,
    StreamLabsConnectionError,
)
from custom_components.streamlabs_libre.config_flow import StreamlabsConfigFlow
from custom_components.streamlabs_libre.const import CONF_LOCATIONS


@pytest.fixture
def flow():
    f = StreamlabsConfigFlow()
    f.hass = MagicMock()
    f.hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    f.async_set_unique_id = AsyncMock()
    f._abort_if_unique_id_configured = MagicMock()
    return f


@pytest.mark.asyncio
async def test_flow_user_single_location(flow):
    mock_resp = {
        "locations": [
            {"locationId": "loc-single", "locationName": "Only Home"}
        ]
    }
    with patch(
        "custom_components.streamlabs_libre.config_flow.StreamLabsClient.get_locations",
        return_value=mock_resp,
    ):
        result = await flow.async_step_user(
            {"username": "user@example.com", "password": "pass"}
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Only Home"
        assert result["data"]["username"] == "user@example.com"
        assert result["data"][CONF_LOCATIONS] == ["loc-single"]


@pytest.mark.asyncio
async def test_flow_user_multiple_locations(flow):
    mock_resp = {
        "locations": [
            {"locationId": "loc-1", "locationName": "Primary Home"},
            {"locationId": "loc-2", "locationName": "Lake House"},
        ]
    }
    with patch(
        "custom_components.streamlabs_libre.config_flow.StreamLabsClient.get_locations",
        return_value=mock_resp,
    ):
        result = await flow.async_step_user(
            {"username": "user@example.com", "password": "pass"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "location"

        # Now submit the location step
        loc_result = await flow.async_step_location({CONF_LOCATIONS: ["loc-2"]})
        assert loc_result["type"] == "create_entry"
        assert loc_result["title"] == "Lake House"
        assert loc_result["data"][CONF_LOCATIONS] == ["loc-2"]


@pytest.mark.asyncio
async def test_flow_auth_error(flow):
    with patch(
        "custom_components.streamlabs_libre.config_flow.StreamLabsClient.get_locations",
        side_effect=StreamLabsAuthError("Unauthorized"),
    ):
        result = await flow.async_step_user(
            {"username": "wrong@example.com", "password": "bad"}
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_flow_connection_error(flow):
    with patch(
        "custom_components.streamlabs_libre.config_flow.StreamLabsClient.get_locations",
        side_effect=StreamLabsConnectionError("Timeout"),
    ):
        result = await flow.async_step_user(
            {"username": "user@example.com", "password": "pass"}
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_options_flow():
    from custom_components.streamlabs_libre.config_flow import StreamlabsOptionsFlowHandler
    from custom_components.streamlabs_libre.const import CONF_SCAN_INTERVAL

    mock_entry = MagicMock()
    mock_entry.options = {CONF_SCAN_INTERVAL: 45}
    mock_entry.data = {}

    options_flow = StreamlabsOptionsFlowHandler()
    options_flow.config_entry = mock_entry

    # Test showing options form
    form_result = await options_flow.async_step_init()
    assert form_result["type"] == "form"
    assert form_result["step_id"] == "init"

    # Test submitting options form
    submit_result = await options_flow.async_step_init({CONF_SCAN_INTERVAL: 20})
    assert submit_result["type"] == "create_entry"
    assert submit_result["data"][CONF_SCAN_INTERVAL] == 20


def test_async_get_options_flow():
    from custom_components.streamlabs_libre.config_flow import StreamlabsOptionsFlowHandler

    mock_entry = MagicMock()
    handler = StreamlabsConfigFlow.async_get_options_flow(mock_entry)
    assert isinstance(handler, StreamlabsOptionsFlowHandler)

