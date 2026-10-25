"""Constants for the StreamLabs Libre integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "streamlabs_libre"

# Configuration keys
CONF_LOCATIONS: Final = "locations"
CONF_SCAN_INTERVAL: Final = "scan_interval"  # Legacy single-interval key for backwards compatibility
CONF_WATER_OFF_INTERVAL: Final = "water_off_interval"
CONF_WATER_ON_INTERVAL: Final = "water_on_interval"

# Scan interval bounds in seconds
DEFAULT_SCAN_INTERVAL: Final = 60
DEFAULT_WATER_OFF_INTERVAL: Final = 60
DEFAULT_WATER_ON_INTERVAL: Final = 15
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

# Rolling yearly usage cache duration in seconds (1 hour)
YEARLY_CACHE_INTERVAL: Final = 3600

# Consecutive failed polls for which the last known state is still served before
# entities are marked unavailable
MAX_STALE_POLLS: Final = 5

# How long a just-commanded state is shown while the cloud catches up (seconds)
OPTIMISTIC_TTL: Final = 30.0

# AWS Cognito & API defaults
COGNITO_USER_POOL_ID: Final = "us-east-1_AxkuzXSR6"
COGNITO_CLIENT_ID: Final = "3kjsjce1iubjvrobk143i4haj4"
COGNITO_REGION: Final = "us-east-1"
BASE_URL: Final = "https://api.platform.streamlabs.io"


class Mode(StrEnum):
    """Monitoring modes."""

    HOME = "home"
    AWAY = "away"


class ValvePosition(StrEnum):
    """Shutoff valve positions as understood by the StreamLabs API."""

    OPEN = "open"
    CLOSE = "close"


MODE_HOME: Final = Mode.HOME
MODE_AWAY: Final = Mode.AWAY
VALVE_OPEN: Final = ValvePosition.OPEN
VALVE_CLOSE: Final = ValvePosition.CLOSE
