#!/bin/sh
""":"
if [ -n "$BASH_VERSION" ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then
    python3 "${BASH_SOURCE[0]}" "$@"
    return $? 2>/dev/null || exit $?
fi
exec python3 "$0" "$@"
"""

# StreamLabs Libre CLI
# Standalone client and CLI for StreamLabs Water Monitor & Valve Control.
# Compatible with Home Assistant via shell_command, REST commands, or cron automation.

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

# Support importing client from custom_components regardless of where/how script is invoked
_script_path = os.path.realpath(__file__)
_script_dir = os.path.dirname(_script_path)
_repo_root = os.path.dirname(_script_dir) if os.path.basename(_script_dir) == "cli" else _script_dir
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from custom_components.streamlabs_libre.client import StreamLabsClient, StreamLabsError


def main() -> None:
    parser = argparse.ArgumentParser(description="StreamLabs Libre CLI Controller")
    parser.add_argument(
        "--user",
        default=os.getenv("STREAMLABS_USER"),
        help="StreamLabs Email (or env STREAMLABS_USER)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("STREAMLABS_PASS"),
        help="StreamLabs Password (or env STREAMLABS_PASS)",
    )
    parser.add_argument(
        "--device",
        default=os.getenv("STREAMLABS_DEVICE_ID"),
        help="StreamLabs Device ID (or env STREAMLABS_DEVICE_ID)",
    )

    subparsers = parser.add_subparsers(dest="action", required=True)

    # Subcommand: status
    subparsers.add_parser("status", help="Get real-time device/location status JSON")

    # Subcommand: locations
    subparsers.add_parser("locations", help="Get raw locations hierarchy JSON")

    # Subcommand: valve
    valve_parser = subparsers.add_parser("valve", help="Set shutoff valve position")
    valve_parser.add_argument(
        "position", choices=["open", "close"], help="Target valve state ('open' or 'close')"
    )

    # Subcommand: mode
    mode_parser = subparsers.add_parser("mode", help="Set monitoring mode")
    mode_parser.add_argument(
        "mode", choices=["home", "away"], help="Target monitoring mode ('home' or 'away')"
    )

    # Subcommand: usage
    usage_parser = subparsers.add_parser("usage", help="Get water usage breakdown")
    usage_parser.add_argument(
        "--date", default=None, help="Date in YYYY-MM-DD format (defaults to today)"
    )

    # Subcommand: command (advanced diagnostics)
    cmd_parser = subparsers.add_parser("command", help="Send arbitrary command to device")
    cmd_parser.add_argument("cmd_name", help="Command name (e.g. 'run drip detect', 'calibrate')")

    args = parser.parse_args()

    if not args.user or not args.password:
        sys.exit(
            "Error: Credentials must be supplied via CLI arguments (--user, --password) "
            "or STREAMLABS_USER / STREAMLABS_PASS environment variables."
        )

    client = StreamLabsClient(args.user, args.password)

    try:
        if args.action == "locations":
            data = client.get_locations()
            print(json.dumps(data, indent=2))

        elif args.action == "status":
            data = client.get_status(args.device)
            print(json.dumps(data, indent=2))

        elif args.action == "valve":
            if not args.device:
                sys.exit("Error: --device must be specified for valve control.")
            success = client.set_valve(args.device, args.position)
            print(json.dumps({"success": success, "valve": args.position}))

        elif args.action == "mode":
            if not args.device:
                sys.exit("Error: --device must be specified for mode control.")
            success = client.set_mode(args.device, args.mode)
            print(json.dumps({"success": success, "mode": args.mode}))

        elif args.action == "usage":
            if not args.device:
                sys.exit("Error: --device must be specified for water usage.")
            usage = client.get_water_usage(args.device, args.date)
            print(json.dumps(usage, indent=2))

        elif args.action == "command":
            if not args.device:
                sys.exit("Error: --device must be specified for device commands.")
            success = client.send_command(args.device, args.cmd_name)
            print(json.dumps({"success": success, "command": args.cmd_name}))

    except StreamLabsError as err:
        sys.exit(f"StreamLabs Error: {err}")
    except Exception as err:
        sys.exit(f"Unexpected error: {err}")


if __name__ == "__main__":
    main()
