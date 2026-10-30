"""Read-only command-line example for qbrobotics serial devices."""

from __future__ import annotations

import argparse
import logging
import math
from typing import Optional, Sequence

from qbrobotics_commands import (
    LEGACY_PROFILE, REPOSITORY_PROFILE, RESEARCH_PROFILE, qb_cmd_get_activate,
    qb_cmd_get_currents, qb_cmd_get_info, qb_cmd_get_inputs, qb_cmd_get_measurements,
    qb_cmd_ping,
)
from qbrobotics_serial_utils import (
    DEFAULT_TIMEOUT, QbError, choose_com_port, close_serial_connection, open_serial_connection,
)


def _device_id(value: str) -> int:
    result = int(value)
    if not 1 <= result <= 255:
        raise argparse.ArgumentTypeError("Device ID must be between 1 and 255")
    return result


def _timeout(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Timeout must be positive and finite")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Serial port; omit to select interactively")
    parser.add_argument("--id", type=_device_id, default=1, help="Device ID (1..255)")
    parser.add_argument("--baudrate", type=int, default=2000000)
    parser.add_argument("--timeout", type=_timeout, default=DEFAULT_TIMEOUT, help="Response timeout in seconds")
    parser.add_argument("--command", choices=("ping", "inputs", "measurements", "currents", "activate-status", "info"), default="ping")
    parser.add_argument("--profile", choices=("research", "legacy", "repository"), default="research")
    parser.add_argument("--verbose", action="store_true", help="Log raw packets")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    profiles = {profile.name: profile for profile in (RESEARCH_PROFILE, LEGACY_PROFILE, REPOSITORY_PROFILE)}
    commands = {
        "ping": qb_cmd_ping, "inputs": qb_cmd_get_inputs,
        "measurements": qb_cmd_get_measurements, "currents": qb_cmd_get_currents,
        "activate-status": qb_cmd_get_activate,
    }
    connection = None
    exit_code = 0
    try:
        port = args.port if args.port is not None else choose_com_port()
        if port is None:
            return 0
        connection = open_serial_connection(port, baudrate=args.baudrate, timeout=args.timeout)
        if args.command == "info":
            print(qb_cmd_get_info(args.id, connection, profile=profiles[args.profile]))
        else:
            result = commands[args.command](args.id, connection)
            if args.command == "ping":
                print(f"Device {result.device_id} responded; serial number: {result.serial_number}")
            else:
                print(result)
    except (QbError, ValueError) as exc:
        logging.error("%s", exc)
        exit_code = 1
    except (KeyboardInterrupt, EOFError):
        exit_code = 130
    finally:
        if connection is not None:
            try:
                close_serial_connection(connection)
            except QbError as exc:
                logging.error("Could not close connection: %s", exc)
                if exit_code == 0:
                    exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
