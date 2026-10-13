"""Tests for StreamLabsClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from custom_components.streamlabs_libre.client import (
    StreamLabsAuthError,
    StreamLabsClient,
    StreamLabsConnectionError,
    StreamLabsDeviceNotFoundError,
)


@pytest.fixture
def mock_cognito():
    with patch("custom_components.streamlabs_libre.client.Cognito") as mock:
        cog = mock.return_value
        cog.id_token = "mock-id-token"
        yield cog


@pytest.fixture
def client(mock_cognito):
    return StreamLabsClient("test@example.com", "secretpassword")


def test_client_init(client):
    assert client.username == "test@example.com"
    assert client.password == "secretpassword"
    assert client.token_expiry == 0.0


def test_ensure_authenticated(client, mock_cognito):
    mock_cognito.id_token = None
    client._ensure_authenticated()
    mock_cognito.authenticate.assert_called_once_with(password="secretpassword")
    assert client.session.headers["Authorization"] == f"Bearer {mock_cognito.id_token}"


def test_ensure_authenticated_error(client, mock_cognito):
    mock_cognito.id_token = None
    mock_cognito.authenticate.side_effect = Exception("Auth failed")
    with pytest.raises(StreamLabsAuthError):
        client._ensure_authenticated()


def test_get_locations(client, mock_cognito):
    sample_resp = {"locations": [{"locationId": "loc-1", "locationName": "Main House"}]}
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = sample_resp
        
        result = client.get_locations()
        assert result == sample_resp
        assert mock_get.call_args[0][0] == "https://api.platform.streamlabs.io/locations"


def test_get_status_flattening(client, mock_cognito):
    sample_resp = {
        "locations": [
            {
                "locationId": "loc-123",
                "locationName": "Primary Home",
                "gallonsToday": 42.5,
                "devices": [
                    {
                        "deviceId": "dev-001",
                        "deviceName": "Main Water Control",
                        "connected": True,
                        "flowing": False,
                        "mode": "home",
                        "valve": {"position": "open"},
                    },
                    {
                        "deviceId": "dev-002",
                        "deviceName": "Basement Monitor",
                        "connected": True,
                        "flowing": True,
                        "mode": "home",
                    },
                ],
            }
        ]
    }
    with patch.object(client, "get_locations", return_value=sample_resp):
        status = client.get_status()
        assert len(status["devices"]) == 2
        dev1 = status["devices"][0]
        assert dev1["device_id"] == "dev-001"
        assert dev1["has_valve"] is True
        assert dev1["valve_position"] == "open"
        assert dev1["gallons_today"] == 42.5

        dev2 = status["devices"][1]
        assert dev2["device_id"] == "dev-002"
        assert dev2["has_valve"] is False
        assert dev2["valve_position"] is None
        assert dev2["flowing"] is True

        # Query single device
        single = client.get_status("dev-001")
        assert single["device_id"] == "dev-001"


def test_get_status_device_not_found(client, mock_cognito):
    with patch.object(client, "get_locations", return_value={"locations": []}):
        with pytest.raises(StreamLabsDeviceNotFoundError):
            client.get_status("nonexistent")


def test_set_valve(client, mock_cognito):
    with patch.object(client.session, "post") as mock_post:
        mock_post.return_value.status_code = 200
        result = client.set_valve("dev-1", "open")
        assert result is True
        mock_post.assert_called_once_with(
            "https://api.platform.streamlabs.io/devices/dev-1/command",
            json={"command": "set valve", "parameters": {"position": "open"}},
            timeout=20,
        )


def test_set_valve_invalid_pos(client):
    with pytest.raises(ValueError):
        client.set_valve("dev-1", "half-open")


def test_set_mode(client, mock_cognito):
    with patch.object(client.session, "put") as mock_put:
        mock_put.return_value.status_code = 204
        result = client.set_mode("dev-1", "away")
        assert result is True
        mock_put.assert_called_once_with(
            "https://api.platform.streamlabs.io/devices/dev-1/settings",
            json={"mode": "away"},
            timeout=15,
        )


def test_set_mode_invalid(client):
    with pytest.raises(ValueError):
        client.set_mode("dev-1", "vacation")


def test_get_water_usage(client, mock_cognito):
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"today": 15.0}
        result = client.get_water_usage("dev-1", "2026-10-13")
        assert result == {"today": 15.0}
        mock_get.assert_called_once_with(
            "https://api.platform.streamlabs.io/devices/dev-1/water",
            params={"date": "2026-10-13"},
            timeout=15,
        )


def test_send_command(client, mock_cognito):
    with patch.object(client.session, "post") as mock_post:
        mock_post.return_value.status_code = 200
        result = client.send_command("dev-1", "run drip detect")
        assert result is True
        mock_post.assert_called_once_with(
            "https://api.platform.streamlabs.io/devices/dev-1/command",
            json={"command": "run drip detect"},
            timeout=20,
        )
