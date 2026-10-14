"""Constants for the StreamLabs Libre integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "streamlabs_libre"
LOGGER = logging.getLogger(__package__)

# Configuration keys
CONF_LOCATIONS: Final = "locations"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Scan interval bounds in seconds
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

# AWS Cognito & API defaults
COGNITO_USER_POOL_ID: Final = "us-east-1_AxkuzXSR6"
COGNITO_CLIENT_ID: Final = "3kjsjce1iubjvrobk143i4haj4"
COGNITO_REGION: Final = "us-east-1"
BASE_URL: Final = "https://api.platform.streamlabs.io"

# Modes
MODE_HOME: Final = "home"
MODE_AWAY: Final = "away"
VALID_MODES: Final = [MODE_HOME, MODE_AWAY]

# Valve Positions
VALVE_OPEN: Final = "open"
VALVE_CLOSE: Final = "close"
VALID_VALVE_POSITIONS: Final = [VALVE_OPEN, VALVE_CLOSE]
