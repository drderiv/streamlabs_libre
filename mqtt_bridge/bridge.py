"""StreamLabs MQTT Bridge daemon with Home Assistant MQTT Auto-Discovery."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

# Ensure root is in path to import StreamLabsClient
_script_dir = os.path.dirname(os.path.realpath(__file__))
_repo_root = os.path.dirname(_script_dir)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from custom_components.streamlabs_libre.client import (
    StreamLabsClient,
    StreamLabsError,
    extract_reading_value,
)
from mqtt_bridge.config import BridgeConfig
from mqtt_bridge.discovery import build_discovery_payloads

_LOGGER = logging.getLogger("streamlabs_mqtt")


class StreamLabsMQTTBridge:
    """MQTT Bridge translating StreamLabs cloud API to Home Assistant MQTT topics."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.running = False
        self.client = StreamLabsClient(config.streamlabs_user, config.streamlabs_pass)

        # Setup MQTT client (supports paho-mqtt v2 and v1)
        try:
            self.mqtt = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=config.mqtt_client_id,
            )
        except AttributeError:
            self.mqtt = mqtt.Client(client_id=config.mqtt_client_id)

        if config.mqtt_username and config.mqtt_password:
            self.mqtt.username_pw_set(config.mqtt_username, config.mqtt_password)

        if config.mqtt_tls:
            self.mqtt.tls_set()

        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.on_disconnect = self._on_disconnect

        # Set LWT (Last Will and Testament)
        lwt_topic = f"{self.config.topic_prefix}/bridge/state"
        self.mqtt.will_set(lwt_topic, "offline", qos=1, retain=True)

        self._discovered_devices: set[str] = set()

    def _on_connect(
        self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, *args: Any
    ) -> None:
        """MQTT connect callback."""
        rc_code = getattr(rc, "value", rc)
        if rc_code == 0:
            _LOGGER.info("Connected successfully to MQTT broker %s:%d", self.config.mqtt_host, self.config.mqtt_port)
            # Publish bridge availability
            client.publish(f"{self.config.topic_prefix}/bridge/state", "online", qos=1, retain=True)

            # Subscribe to command topics for all devices
            valve_sub = f"{self.config.topic_prefix}/+/valve/set"
            mode_sub = f"{self.config.topic_prefix}/+/mode/set"
            cmd_sub = f"{self.config.topic_prefix}/+/command/set"

            client.subscribe([(valve_sub, 1), (mode_sub, 1), (cmd_sub, 1)])
            _LOGGER.info("Subscribed to command topics: %s, %s, %s", valve_sub, mode_sub, cmd_sub)
        else:
            _LOGGER.error("Failed to connect to MQTT broker, return code: %s", rc_code)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, *args: Any) -> None:
        """MQTT disconnect callback."""
        _LOGGER.warning("Disconnected from MQTT broker")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Handle incoming MQTT command messages."""
        topic = msg.topic
        payload = msg.payload.decode("utf-8").strip()
        _LOGGER.info("Received MQTT message on %s: %s", topic, payload)

        parts = topic.split("/")
        # Expected: <prefix>/<device_id>/<target>/set
        if len(parts) < 4:
            return

        device_id = parts[1]
        target = parts[2]

        try:
            if target == "valve":
                pos = payload.lower()
                if pos in ("open", "close"):
                    _LOGGER.info("Actuating valve for device %s to %s", device_id, pos)
                    self.client.set_valve(device_id, pos)  # type: ignore[arg-type]
                    self.poll_and_publish()
                else:
                    _LOGGER.warning("Invalid valve payload: %s", payload)

            elif target == "mode":
                mode = payload.lower()
                if mode in ("home", "away"):
                    _LOGGER.info("Setting monitoring mode for device %s to %s", device_id, mode)
                    self.client.set_mode(device_id, mode)  # type: ignore[arg-type]
                    self.poll_and_publish()
                else:
                    _LOGGER.warning("Invalid mode payload: %s", payload)

            elif target == "command":
                _LOGGER.info("Sending command '%s' to device %s", payload, device_id)
                self.client.send_command(device_id, payload)
                self.poll_and_publish()

        except Exception as err:
            _LOGGER.error("Error executing MQTT command on %s: %s", topic, err)

    def _extract_usage(self, usage_data: Dict[str, Any]) -> tuple[float, float, float]:
        """Extract daily, monthly, and yearly consumption."""
        daily = 0.0
        monthly = 0.0
        yearly = 0.0

        if not usage_data:
            return daily, monthly, yearly

        if "today" in usage_data:
            daily = float(usage_data.get("today", 0.0) or 0.0)
            monthly = float(usage_data.get("thisMonth", 0.0) or 0.0)
            yearly = float(usage_data.get("thisYear", 0.0) or 0.0)
            return daily, monthly, yearly

        day_obj = usage_data.get("day")
        if isinstance(day_obj, dict):
            daily = float(day_obj.get("todayTotal", 0.0) or 0.0)
        month_obj = usage_data.get("month")
        if isinstance(month_obj, dict):
            monthly = float(month_obj.get("thisMonthTotal", month_obj.get("total", 0.0)) or 0.0)
        year_obj = usage_data.get("year")
        if isinstance(year_obj, dict):
            yearly = float(year_obj.get("thisYearTotal", year_obj.get("total", 0.0)) or 0.0)

        if daily == 0.0 and "data" in usage_data and isinstance(usage_data["data"], list):
            daily = sum(float(pt.get("volume", 0.0) or 0.0) for pt in usage_data["data"] if isinstance(pt, dict))

        return daily, monthly, yearly

    def poll_and_publish(self) -> None:
        """Fetch latest telemetry from StreamLabs API and publish to MQTT."""
        try:
            status = self.client.get_status()
            devices: List[Dict[str, Any]] = status.get("devices", [])
        except StreamLabsError as err:
            _LOGGER.error("Failed to poll StreamLabs status: %s", err)
            return
        except Exception as err:
            _LOGGER.exception("Unexpected error querying StreamLabs: %s", err)
            return

        for dev in devices:
            loc_id = dev.get("location_id")
            if self.config.streamlabs_locations and loc_id not in self.config.streamlabs_locations:
                continue

            device_id = dev.get("device_id")
            if not device_id:
                continue

            # Publish HA Discovery if not yet published this run
            if device_id not in self._discovered_devices:
                discovery_entries = build_discovery_payloads(
                    dev,
                    discovery_prefix=self.config.discovery_prefix,
                    topic_prefix=self.config.topic_prefix,
                )
                for topic, payload in discovery_entries:
                    self.mqtt.publish(topic, payload, qos=1, retain=True)
                self._discovered_devices.add(device_id)
                _LOGGER.info("Published %d MQTT Discovery entities for device %s", len(discovery_entries), device_id)

            # Fetch detailed water usage
            daily = 0.0
            monthly = 0.0
            yearly = 0.0
            try:
                usage_resp = self.client.get_water_usage(device_id)
                daily, monthly, yearly = self._extract_usage(usage_resp)
            except Exception as err:
                _LOGGER.debug("Could not fetch water usage for %s: %s", device_id, err)

            gallons_today = float(dev.get("gallons_today") or 0.0)
            if daily == 0.0 and gallons_today > 0.0:
                daily = gallons_today

            # Fetch detailed device telemetry (room temp, humidity, water pressure, water temp)
            dev_detail: Dict[str, Any] = {}
            try:
                dev_detail = self.client.get_device(device_id)
            except Exception as err:
                _LOGGER.debug("Could not fetch device detail for %s: %s", device_id, err)

            raw_ambient = (
                dev_detail.get("ambientTemp")
                or dev_detail.get("ambient_temp")
                or dev_detail.get("roomTemp")
                or dev.get("ambient_temp")
                or dev.get("ambientTemp")
            )
            raw_humidity = (
                dev_detail.get("humidity")
                or dev_detail.get("roomHumidity")
                or dev.get("humidity")
            )
            raw_pressure = (
                dev_detail.get("waterPressure")
                or dev_detail.get("water_pressure")
                or dev_detail.get("pressure")
                or dev.get("water_pressure")
                or dev.get("waterPressure")
            )
            raw_water_temp = (
                dev_detail.get("waterTemp")
                or dev_detail.get("water_temp")
                or dev.get("water_temp")
                or dev.get("waterTemp")
            )

            room_temp = extract_reading_value(raw_ambient)
            room_humidity = extract_reading_value(raw_humidity)
            water_pressure = extract_reading_value(raw_pressure)
            water_temp = extract_reading_value(raw_water_temp)

            # Build state payload
            state_data = {
                "device_id": device_id,
                "device_name": dev.get("device_name"),
                "location_id": loc_id,
                "valve": dev.get("valve_position") or "unknown",
                "mode": dev.get("mode") or "home",
                "flowing": "ON" if dev.get("flowing") else "OFF",
                "connected": "ON" if dev.get("connected") else "OFF",
                "away_mode": "ON" if dev.get("mode") == "away" else "OFF",
                "daily_usage": round(daily, 2),
                "monthly_usage": round(monthly, 2),
                "yearly_usage": round(yearly, 2),
                "gallons_today": round(gallons_today, 2),
                "room_humidity": room_humidity,
                "room_temp": room_temp,
                "water_pressure": water_pressure,
                "water_temp": water_temp,
            }

            state_topic = f"{self.config.topic_prefix}/{device_id}/state"
            avail_topic = f"{self.config.topic_prefix}/{device_id}/availability"

            # Publish availability and state
            is_connected = dev.get("connected", True)
            self.mqtt.publish(avail_topic, "online" if is_connected else "offline", qos=1, retain=True)
            self.mqtt.publish(state_topic, json.dumps(state_data), qos=1, retain=True)
            _LOGGER.debug("Published state to %s: %s", state_topic, state_data)

    def start(self) -> None:
        """Start the bridge event loop."""
        self.running = True
        _LOGGER.info("Starting StreamLabs MQTT Bridge...")
        _LOGGER.info("Connecting to MQTT broker %s:%d...", self.config.mqtt_host, self.config.mqtt_port)

        self.mqtt.connect(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
        self.mqtt.loop_start()

        # Handle process signals
        def handle_signal(sig: int, frame: Any) -> None:
            _LOGGER.info("Received signal %s, stopping bridge...", sig)
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        # Main polling loop
        while self.running:
            self.poll_and_publish()
            # Sleep in small increments for responsive shutdown
            for _ in range(self.config.poll_interval):
                if not self.running:
                    break
                time.sleep(1)

        _LOGGER.info("StreamLabs MQTT Bridge stopped.")

    def stop(self) -> None:
        """Stop the bridge and disconnect cleanly."""
        self.running = False
        lwt_topic = f"{self.config.topic_prefix}/bridge/state"
        self.mqtt.publish(lwt_topic, "offline", qos=1, retain=True)
        self.mqtt.loop_stop()
        self.mqtt.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="StreamLabs MQTT Bridge")
    parser.add_argument("--config", "-c", help="Path to config file (yaml or json)")
    args = parser.parse_args()

    config = BridgeConfig.load(args.config)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bridge = StreamLabsMQTTBridge(config)
    bridge.start()


if __name__ == "__main__":
    main()
