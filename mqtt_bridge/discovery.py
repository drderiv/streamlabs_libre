"""Home Assistant MQTT Discovery payload builder."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple


def build_discovery_payloads(
    device_info: Dict[str, Any],
    discovery_prefix: str = "homeassistant",
    topic_prefix: str = "streamlabs",
) -> List[Tuple[str, str]]:
    """
    Generate list of (discovery_topic, json_payload) tuples for a StreamLabs device.
    """
    device_id = device_info["device_id"]
    device_name = device_info.get("device_name") or f"StreamLabs {device_id}"
    location_name = device_info.get("location_name") or "StreamLabs Location"
    has_valve = bool(device_info.get("has_valve", False))

    device_payload = {
        "identifiers": [f"streamlabs_{device_id}"],
        "name": device_name,
        "manufacturer": "StreamLabs",
        "model": "Streamlabs Control" if has_valve else "Streamlabs Monitor",
        "suggested_area": location_name,
    }

    state_topic = f"{topic_prefix}/{device_id}/state"
    avail_topic = f"{topic_prefix}/{device_id}/availability"

    configs: List[Tuple[str, Dict[str, Any]]] = []

    # 1. Shutoff Valve (if device has valve)
    if has_valve or device_info.get("valve_position") is not None:
        configs.append(
            (
                f"{discovery_prefix}/valve/streamlabs_{device_id}/shutoff_valve/config",
                {
                    "name": "Water valve",
                    "unique_id": f"streamlabs_{device_id}_shutoff_valve",
                    "device": device_payload,
                    "device_class": "water",
                    "state_topic": state_topic,
                    "value_template": "{{ value_json.valve }}",
                    "command_topic": f"{topic_prefix}/{device_id}/valve/set",
                    "payload_open": "open",
                    "payload_close": "close",
                    "state_open": "open",
                    "state_closed": "close",
                    "availability_topic": avail_topic,
                    "icon": "mdi:pipe-valve",
                },
            )
        )

    # 2. Monitoring Mode Select (home / away)
    configs.append(
        (
            f"{discovery_prefix}/select/streamlabs_{device_id}/mode/config",
            {
                "name": "Monitoring mode",
                "unique_id": f"streamlabs_{device_id}_mode",
                "device": device_payload,
                "state_topic": state_topic,
                "value_template": "{{ value_json.mode }}",
                "command_topic": f"{topic_prefix}/{device_id}/mode/set",
                "options": ["home", "away"],
                "availability_topic": avail_topic,
                "icon": "mdi:home",
            },
        )
    )

    # 3. Water Consumption Sensors
    sensors = [
        (
            "daily_usage",
            "Daily water usage",
            "{{ value_json.daily_usage }}",
            "gal",
            "water",
            "total_increasing",
        ),
        (
            "monthly_usage",
            "Monthly water usage",
            "{{ value_json.monthly_usage }}",
            "gal",
            "water",
            "total",
        ),
        (
            "yearly_usage",
            "Yearly water usage",
            "{{ value_json.yearly_usage }}",
            "gal",
            "water",
            "total",
        ),
        (
            "gallons_today",
            "Gallons today",
            "{{ value_json.gallons_today }}",
            "gal",
            "water",
            "total_increasing",
        ),
    ]

    for key, name, v_tpl, unit, dev_class, state_class in sensors:
        configs.append(
            (
                f"{discovery_prefix}/sensor/streamlabs_{device_id}/{key}/config",
                {
                    "name": name,
                    "unique_id": f"streamlabs_{device_id}_{key}",
                    "device": device_payload,
                    "state_topic": state_topic,
                    "value_template": v_tpl,
                    "unit_of_measurement": unit,
                    "device_class": dev_class,
                    "state_class": state_class,
                    "suggested_display_precision": 1,
                    "availability_topic": avail_topic,
                },
            )
        )

    # 4. Binary Sensors (flowing, connectivity, away_mode)
    bin_sensors = [
        ("flowing", "Water flowing", "{{ value_json.flowing }}", None, "mdi:water-pump"),
        ("connected", "Connectivity", "{{ value_json.connected }}", "connectivity", None),
        ("away_mode", "Away mode", "{{ value_json.away_mode }}", None, "mdi:home-export-outline"),
    ]

    for key, name, v_tpl, dev_class, icon in bin_sensors:
        cfg: Dict[str, Any] = {
            "name": name,
            "unique_id": f"streamlabs_{device_id}_{key}",
            "device": device_payload,
            "state_topic": state_topic,
            "value_template": v_tpl,
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability_topic": avail_topic,
        }
        if dev_class:
            cfg["device_class"] = dev_class
        if icon:
            cfg["icon"] = icon

        configs.append(
            (
                f"{discovery_prefix}/binary_sensor/streamlabs_{device_id}/{key}/config",
                cfg,
            )
        )

    return [(topic, json.dumps(payload)) for topic, payload in configs]
