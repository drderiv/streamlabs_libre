"""Tests for StreamLabs MQTT Bridge."""

import json
import os
from unittest.mock import MagicMock, patch
import pytest

from mqtt_bridge.config import BridgeConfig
from mqtt_bridge.discovery import build_discovery_payloads
from mqtt_bridge.bridge import StreamLabsMQTTBridge


def test_bridge_config_load(monkeypatch):
    monkeypatch.setenv("STREAMLABS_USER", "env_user@example.com")
    monkeypatch.setenv("STREAMLABS_PASS", "env_pass")
    monkeypatch.setenv("MQTT_BROKER", "192.168.1.50")
    monkeypatch.setenv("MQTT_PORT", "1884")
    monkeypatch.setenv("STREAMLABS_LOCATIONS", "loc1, loc2")

    config = BridgeConfig.load()
    assert config.streamlabs_user == "env_user@example.com"
    assert config.streamlabs_pass == "env_pass"
    assert config.mqtt_host == "192.168.1.50"
    assert config.mqtt_port == 1884
    assert config.streamlabs_locations == ["loc1", "loc2"]


def test_discovery_payload_generation():
    device = {
        "device_id": "dev-456",
        "device_name": "Main Shutoff Valve",
        "location_name": "Main House",
        "has_valve": True,
        "valve_position": "open",
    }

    entries = build_discovery_payloads(device)
    topics = [t for t, _ in entries]

    # Verify valve discovery
    assert "homeassistant/valve/streamlabs_dev-456/shutoff_valve/config" in topics
    # Verify select mode discovery
    assert "homeassistant/select/streamlabs_dev-456/mode/config" in topics
    # Verify sensors
    assert "homeassistant/sensor/streamlabs_dev-456/daily_usage/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/monthly_usage/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/yearly_usage/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/gallons_today/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/room_humidity/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/room_temp/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/water_pressure/config" in topics
    assert "homeassistant/sensor/streamlabs_dev-456/water_temp/config" in topics
    # Verify binary sensors
    assert "homeassistant/binary_sensor/streamlabs_dev-456/flowing/config" in topics
    assert "homeassistant/binary_sensor/streamlabs_dev-456/connected/config" in topics
    assert "homeassistant/binary_sensor/streamlabs_dev-456/away_mode/config" in topics

    # Inspect valve JSON payload
    valve_entry = next(p for t, p in entries if "valve" in t and "config" in t)
    valve_json = json.loads(valve_entry)
    assert valve_json["name"] == "Water valve"
    assert valve_json["command_topic"] == "streamlabs/dev-456/valve/set"
    assert valve_json["state_topic"] == "streamlabs/dev-456/state"


def test_discovery_monitor_without_valve():
    device = {
        "device_id": "dev-monitor",
        "device_name": "Basement Monitor",
        "location_name": "Basement",
        "has_valve": False,
        "valve_position": None,
    }

    entries = build_discovery_payloads(device)
    topics = [t for t, _ in entries]
    # Monitor without valve should NOT generate a valve entity
    assert not any("valve" in t and "config" in t for t in topics)
    # But should generate sensors
    assert any("sensor" in t for t in topics)


@pytest.fixture
def mock_bridge():
    config = BridgeConfig(
        streamlabs_user="test@example.com",
        streamlabs_pass="pass",
        mqtt_host="localhost",
    )
    with patch("mqtt_bridge.bridge.StreamLabsClient") as mock_client_cls, \
         patch("mqtt_bridge.bridge.mqtt.Client"):
        bridge = StreamLabsMQTTBridge(config)
        bridge.client = mock_client_cls.return_value
        bridge.mqtt = MagicMock()
        return bridge


def test_bridge_on_message_valve(mock_bridge):
    msg = MagicMock()
    msg.topic = "streamlabs/dev-123/valve/set"
    msg.payload = b"close"

    with patch.object(mock_bridge, "poll_and_publish") as mock_poll:
        mock_bridge._on_message(mock_bridge.mqtt, None, msg)
        mock_bridge.client.set_valve.assert_called_once_with("dev-123", "close")
        mock_poll.assert_called_once()


def test_bridge_on_message_mode(mock_bridge):
    msg = MagicMock()
    msg.topic = "streamlabs/dev-123/mode/set"
    msg.payload = b"away"

    with patch.object(mock_bridge, "poll_and_publish") as mock_poll:
        mock_bridge._on_message(mock_bridge.mqtt, None, msg)
        mock_bridge.client.set_mode.assert_called_once_with("dev-123", "away")
        mock_poll.assert_called_once()


def test_bridge_poll_and_publish(mock_bridge):
    mock_bridge.client.get_status.return_value = {
        "devices": [
            {
                "location_id": "loc-1",
                "location_name": "Home",
                "device_id": "dev-01",
                "device_name": "Main Valve",
                "connected": True,
                "flowing": False,
                "mode": "home",
                "has_valve": True,
                "valve_position": "open",
                "gallons_today": 18.2,
            }
        ]
    }
    mock_bridge.client.get_water_usage.return_value = {
        "today": 18.2,
        "thisMonth": 150.0,
        "thisYear": 1800.0,
    }
    mock_bridge.client.get_device.return_value = {
        "deviceId": "dev-01",
        "ambientTemp": {"currentValue": 71},
        "humidity": {"currentValue": 43},
        "waterPressure": {"currentValue": 52},
        "waterTemp": {"currentValue": 66},
    }

    mock_bridge.poll_and_publish()

    # Verify discovery was published
    assert "dev-01" in mock_bridge._discovered_devices
    # Verify state topic published
    published_topics = [call[0][0] for call in mock_bridge.mqtt.publish.call_args_list]
    assert "streamlabs/dev-01/state" in published_topics
    assert "streamlabs/dev-01/availability" in published_topics

    # Check payload of state topic
    state_call = next(call for call in mock_bridge.mqtt.publish.call_args_list if call[0][0] == "streamlabs/dev-01/state")
    payload = json.loads(state_call[0][1])
    assert payload["valve"] == "open"
    assert payload["flowing"] == "OFF"
    assert payload["daily_usage"] == 18.2
    assert payload["mode"] == "home"
    assert payload["room_temp"] == 71.0
    assert payload["room_humidity"] == 43.0
    assert payload["water_pressure"] == 52.0
    assert payload["water_temp"] == 66.0
