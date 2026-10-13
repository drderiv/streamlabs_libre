"""Configuration parser for StreamLabs MQTT Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from typing import Any, Dict, List, Optional
import yaml

_LOGGER = logging.getLogger(__name__)


@dataclass
class BridgeConfig:
    """MQTT Bridge Configuration."""

    streamlabs_user: str
    streamlabs_pass: str
    streamlabs_locations: List[str] = field(default_factory=list)
    poll_interval: int = 60

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_client_id: str = "streamlabs_bridge"
    mqtt_tls: bool = False

    discovery_prefix: str = "homeassistant"
    topic_prefix: str = "streamlabs"
    log_level: str = "INFO"

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> BridgeConfig:
        """Load configuration from file and/or environment variables."""
        file_data: Dict[str, Any] = {}

        if config_path and os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                if config_path.endswith((".yaml", ".yml")):
                    file_data = yaml.safe_load(f) or {}
                elif config_path.endswith(".json"):
                    file_data = json.load(f) or {}

        # Environment variable overrides
        user = os.getenv("STREAMLABS_USER", file_data.get("streamlabs_user", ""))
        password = os.getenv("STREAMLABS_PASS", file_data.get("streamlabs_pass", ""))

        if not user or not password:
            raise ValueError(
                "Missing required credentials: STREAMLABS_USER and STREAMLABS_PASS "
                "must be specified in environment variables or configuration file."
            )

        locations_raw = os.getenv("STREAMLABS_LOCATIONS")
        if locations_raw:
            locations = [loc.strip() for loc in locations_raw.split(",") if loc.strip()]
        else:
            locations = file_data.get("streamlabs_locations", [])

        poll_interval = int(
            os.getenv("STREAMLABS_POLL_INTERVAL", file_data.get("poll_interval", 60))
        )

        mqtt_host = os.getenv("MQTT_BROKER", os.getenv("MQTT_HOST", file_data.get("mqtt_host", "localhost")))
        mqtt_port = int(os.getenv("MQTT_PORT", file_data.get("mqtt_port", 1883)))
        mqtt_username = os.getenv("MQTT_USERNAME", file_data.get("mqtt_username"))
        mqtt_password = os.getenv("MQTT_PASSWORD", file_data.get("mqtt_password"))
        mqtt_client_id = os.getenv("MQTT_CLIENT_ID", file_data.get("mqtt_client_id", "streamlabs_bridge"))
        mqtt_tls = os.getenv("MQTT_TLS", str(file_data.get("mqtt_tls", "false"))).lower() in ("true", "1", "yes")

        discovery_prefix = os.getenv("MQTT_DISCOVERY_PREFIX", file_data.get("discovery_prefix", "homeassistant"))
        topic_prefix = os.getenv("MQTT_TOPIC_PREFIX", file_data.get("topic_prefix", "streamlabs"))
        log_level = os.getenv("LOG_LEVEL", file_data.get("log_level", "INFO")).upper()

        return cls(
            streamlabs_user=user,
            streamlabs_pass=password,
            streamlabs_locations=locations,
            poll_interval=poll_interval,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_username=mqtt_username,
            mqtt_password=mqtt_password,
            mqtt_client_id=mqtt_client_id,
            mqtt_tls=mqtt_tls,
            discovery_prefix=discovery_prefix,
            topic_prefix=topic_prefix,
            log_level=log_level,
        )
