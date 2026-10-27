"""Tests for StreamLabsClient."""

from unittest.mock import ANY, MagicMock, patch
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
    from pycognito import Cognito

    with patch("custom_components.streamlabs_libre.client.Cognito") as mock:
        # spec'd so calling a method pycognito doesn't have fails, as it would in production
        cog = MagicMock(spec=Cognito)
        mock.return_value = cog
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


def test_ensure_authenticated_error(client, mock_cognito):
    mock_cognito.id_token = None
    mock_cognito.authenticate.side_effect = _client_error("NotAuthorizedException")
    with pytest.raises(StreamLabsAuthError):
        client._ensure_authenticated()


def test_get_locations(client, mock_cognito):
    sample_resp = {"locations": [{"locationId": "loc-1", "locationName": "Main House"}]}
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = sample_resp
        
        result = client.get_locations()
        assert result == sample_resp
        assert mock_get.call_args[0][1] == "https://api.platform.streamlabs.io/locations"


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
    with patch.object(client.session, "request") as mock_post:
        mock_post.return_value.status_code = 200
        result = client.set_valve("dev-1", "open")
        assert result is True
        mock_post.assert_called_once_with(
            "POST",
            "https://api.platform.streamlabs.io/devices/dev-1/command",
            json={"command": "set valve", "parameters": {"position": "open"}},
            headers=ANY,
            timeout=20,
        )


def test_set_valve_invalid_pos(client):
    with pytest.raises(ValueError):
        client.set_valve("dev-1", "half-open")


def test_set_mode(client, mock_cognito):
    with patch.object(client.session, "request") as mock_put:
        mock_put.return_value.status_code = 204
        result = client.set_mode("dev-1", "away")
        assert result is True
        mock_put.assert_called_once_with(
            "PUT",
            "https://api.platform.streamlabs.io/devices/dev-1/settings",
            json={"mode": "away"},
            headers=ANY,
            timeout=15,
        )


def test_set_mode_invalid(client):
    with pytest.raises(ValueError):
        client.set_mode("dev-1", "vacation")


def test_get_water_usage(client, mock_cognito):
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"today": 15.0}
        result = client.get_water_usage("dev-1", "2026-10-13")
        assert result == {"today": 15.0}
        mock_get.assert_called_once_with(
            "GET",
            "https://api.platform.streamlabs.io/devices/dev-1/water",
            params={"date": "2026-10-13"},
            headers=ANY,
            timeout=15,
        )


def test_get_water_usage_no_date(client, mock_cognito):
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"day": {"todayTotal": 15.0}}
        result = client.get_water_usage("dev-1")
        assert result == {"day": {"todayTotal": 15.0}}
        mock_get.assert_called_once_with(
            "GET",
            "https://api.platform.streamlabs.io/devices/dev-1/water",
            params=None,
            headers=ANY,
            timeout=15,
        )


def test_get_water_usage_rolling_history(client, mock_cognito):
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "tz": "America/Los_Angeles",
            "unit": "gal",
            "interval": "month",
            "data": [2500.0, 3100.0, 4227.0],
        }
        result = client.get_water_usage_history("dev-1", "2026", rolling=True)
        assert result["interval"] == "month"
        assert sum(result["data"]) == 9827.0
        mock_get.assert_called_once_with(
            "GET",
            "https://api.platform.streamlabs.io/devices/dev-1/water/2026",
            params={"rolling": "true"},
            headers=ANY,
            timeout=15,
        )



def test_send_command(client, mock_cognito):
    with patch.object(client.session, "request") as mock_post:
        mock_post.return_value.status_code = 200
        result = client.send_command("dev-1", "run drip detect")
        assert result is True
        mock_post.assert_called_once_with(
            "POST",
            "https://api.platform.streamlabs.io/devices/dev-1/command",
            json={"command": "run drip detect"},
            headers=ANY,
            timeout=20,
        )


def test_get_device(client, mock_cognito):
    device_json = {
        "deviceId": "dev-01",
        "ambientTemp": {"currentValue": 72},
        "humidity": {"currentValue": 45},
        "waterPressure": {"currentValue": 55},
        "waterTemp": {"currentValue": 68},
    }
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = device_json
        result = client.get_device("dev-01")
        assert result == device_json
        mock_get.assert_called_once_with(
            "GET",
            "https://api.platform.streamlabs.io/devices/dev-01",
            headers=ANY,
            timeout=15,
        )


def test_extract_reading_value():
    from custom_components.streamlabs_libre.client import extract_reading_value

    assert extract_reading_value(72) == 72.0
    assert extract_reading_value(45.5) == 45.5
    assert extract_reading_value({"currentValue": 70}) == 70.0
    assert extract_reading_value({"iCurrentValue": 55}) == 55.0
    assert extract_reading_value({"value": 68.2}) == 68.2

    # Sentinel error values <= -1000 should be filtered to None
    assert extract_reading_value(-1000) is None
    assert extract_reading_value(-10000) is None
    assert extract_reading_value({"currentValue": -10000}) is None
    assert extract_reading_value({"iCurrentValue": -1000}) is None

    # Missing or invalid
    assert extract_reading_value(None) is None
    assert extract_reading_value({}) is None
    assert extract_reading_value({"currentValue": "invalid"}) is None
    assert extract_reading_value("not_a_number") is None


def test_validate_response_detects_error_payloads(client, mock_cognito):
    from custom_components.streamlabs_libre.client import StreamLabsError

    # 1. {"error": "..."}
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b'{"error": "Unauthorized device"}'
        mock_get.return_value.json.return_value = {"error": "Unauthorized device"}
        with pytest.raises(StreamLabsError, match="StreamLabs API returned error payload: Unauthorized device"):
            client.get_locations()

    # 2. {"errors": [{"message": "Rate limit exceeded"}]}
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b'{"errors": [{"message": "Rate limit exceeded"}]}'
        mock_get.return_value.json.return_value = {"errors": [{"message": "Rate limit exceeded"}]}
        with pytest.raises(StreamLabsError, match="StreamLabs API returned error payload: Rate limit exceeded"):
            client.get_device("dev-01")

    # 3. {"code": 500, "message": "Internal error"}
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b'{"code": 500, "message": "Internal error"}'
        mock_get.return_value.json.return_value = {"code": 500, "message": "Internal error"}
        with pytest.raises(StreamLabsError, match="StreamLabs API error \\(500\\): Internal error"):
            client.get_water_usage("dev-01")

    # 4. {"statusCode": 503, "message": "Service unavailable"}
    with patch.object(client.session, "request") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b'{"statusCode": 503, "message": "Service unavailable"}'
        mock_post.return_value.json.return_value = {"statusCode": 503, "message": "Service unavailable"}
        with pytest.raises(StreamLabsError, match="StreamLabs API error \\(503\\): Service unavailable"):
            client.set_valve("dev-01", "open")

    # 5. {"ErrorMessage": "Valve jammed", "ReturnCode": 10}
    with patch.object(client.session, "request") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b'{"ErrorMessage": "Valve jammed", "ReturnCode": 10}'
        mock_post.return_value.json.return_value = {"ErrorMessage": "Valve jammed", "ReturnCode": 10}
        with pytest.raises(StreamLabsError, match="StreamLabs API error: Valve jammed"):
            client.set_valve("dev-01", "close")


def test_http_500_raises_connection_error(client, mock_cognito):
    with patch.object(client.session, "request") as mock_get:
        mock_get.return_value.status_code = 500
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        with pytest.raises(StreamLabsConnectionError, match="HTTP request failed \\(500\\)"):
            client.get_locations()



def _client_error(code):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": "x"}}, "InitiateAuth")


def test_bad_credentials_are_auth_errors(client, mock_cognito):
    mock_cognito.id_token = None
    mock_cognito.authenticate.side_effect = _client_error("NotAuthorizedException")
    with pytest.raises(StreamLabsAuthError):
        client._ensure_authenticated()


def test_network_failure_is_connection_error_not_auth(client, mock_cognito):
    from botocore.exceptions import EndpointConnectionError

    mock_cognito.id_token = None
    mock_cognito.authenticate.side_effect = EndpointConnectionError(endpoint_url="https://x")
    with pytest.raises(StreamLabsConnectionError):
        client._ensure_authenticated()

    mock_cognito.authenticate.side_effect = _client_error("InternalErrorException")
    with pytest.raises(StreamLabsConnectionError):
        client._ensure_authenticated()


def test_token_expiry_taken_from_jwt(client, mock_cognito):
    import base64
    import json
    import time

    exp = time.time() + 7200
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    mock_cognito.id_token = None

    def _auth(password):
        mock_cognito.id_token = f"h.{payload}.s"

    mock_cognito.authenticate.side_effect = _auth
    client._ensure_authenticated()
    assert client.token_expiry == pytest.approx(exp - 60)


def test_rejected_token_triggers_one_reauth_and_retry(client, mock_cognito):
    rejected = MagicMock(status_code=401)
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"locations": []}
    with patch.object(client.session, "request", side_effect=[rejected, ok]) as mock_req:
        assert client.get_locations() == {"locations": []}
    assert mock_req.call_count == 2
    mock_cognito.authenticate.assert_called()


def test_persistent_401_is_auth_error(client, mock_cognito):
    rejected = MagicMock(status_code=403)
    with patch.object(client.session, "request", return_value=rejected):
        with pytest.raises(StreamLabsAuthError):
            client.get_locations()


def test_get_status_missing_location_id_is_none(client, mock_cognito):
    with patch.object(client.session, "request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"locations": [{"locationName": "X", "devices": []}]}
        summary = client.get_status()["locations_summary"]
    assert summary[0]["location_id"] is None


def test_expired_token_is_renewed_with_refresh_token(client, mock_cognito):
    client.token_expiry = 0.0  # expired
    client._ensure_authenticated()
    mock_cognito.renew_access_token.assert_called_once_with()
    mock_cognito.authenticate.assert_not_called()


def test_failed_renewal_falls_back_to_full_authentication(client, mock_cognito):
    client.token_expiry = 0.0
    mock_cognito.renew_access_token.side_effect = _client_error("NotAuthorizedException")
    client._ensure_authenticated()
    mock_cognito.authenticate.assert_called_once_with(password="secretpassword")
