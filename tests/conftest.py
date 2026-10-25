"""Fixtures for the standalone (no Home Assistant) tests of the client, CLI and MQTT bridge.

The integration's package ``__init__`` imports Home Assistant, so register a bare package
object that lets ``custom_components.streamlabs_libre.client`` import without it. Tests
that need real Home Assistant live in ``tests_ha``.
"""

from pathlib import Path
import sys
import types

_ROOT = Path(__file__).resolve().parents[1] / "custom_components"

for _name, _path in (
    ("custom_components", _ROOT),
    ("custom_components.streamlabs_libre", _ROOT / "streamlabs_libre"),
):
    _module = types.ModuleType(_name)
    _module.__path__ = [str(_path)]
    sys.modules.setdefault(_name, _module)
