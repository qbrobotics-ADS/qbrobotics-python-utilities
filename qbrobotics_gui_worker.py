"""Single-owner serial worker used by the desktop GUI; no Tk calls in this module."""

from __future__ import annotations

from dataclasses import dataclass
import math
import queue
import threading
from typing import Any

import qbrobotics_commands as commands
import qbrobotics_serial_utils as transport

PROFILES = {profile.name: profile for profile in (
    commands.RESEARCH_PROFILE, commands.LEGACY_PROFILE, commands.REPOSITORY_PROFILE,
)}


@dataclass(frozen=True)
class ConnectionSettings:
    port: str
    device_id: int = 1
    baudrate: int = 2000000
    timeout: float = 0.5
    profile: str = "research"

    def __post_init__(self) -> None:
        if not self.port.strip():
            raise ValueError("Select a serial port.")
        transport.validate_integer(self.device_id, "ID", 1, 255)
        transport.validate_integer(self.baudrate, "baudrate", 1, 2147483647)
        if isinstance(self.timeout, bool) or not math.isfinite(self.timeout) or not 0.05 <= self.timeout <= 10:
            raise ValueError("Timeout must be between 0.05 and 10 seconds.")
        if self.profile not in PROFILES:
            raise ValueError("Unknown firmware profile.")


@dataclass(frozen=True)
class ReferenceLimits:
    minimum_1: int
    maximum_1: int
    minimum_2: int
    maximum_2: int

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            transport.validate_integer(value, name, -32768, 32767)
        if self.minimum_1 > self.maximum_1 or self.minimum_2 > self.maximum_2:
            raise ValueError("Each minimum limit must be less than or equal to its maximum.")

    def validate(self, first: int, second: int) -> None:
        transport.validate_integer(first, "Reference 1", self.minimum_1, self.maximum_1)
        transport.validate_integer(second, "Reference 2", self.minimum_2, self.maximum_2)


@dataclass(frozen=True)
class WorkerEvent:
    kind: str
    action: str = ""
    value: Any = None
    error: str = ""


class _Cancelled(Exception):
    pass


class SerialWorker(threading.Thread):
    """Own one connection and run bounded serial calls outside the GUI thread.

    Only one normal command is accepted at a time. Disconnect/close cancel queued
    commands. Deactivation takes priority after the current bounded serial call,
    including when a snapshot consists of multiple requests.
    """

    ACTIONS = frozenset({
        "ports", "connect", "ping", "snapshot", "info", "motor_commands",
        "activate", "deactivate", "set_inputs",
    })

    def __init__(self) -> None:
        super().__init__(name="qbrobotics-serial", daemon=True)
        self.events: queue.Queue[WorkerEvent] = queue.Queue()
        self._jobs: queue.Queue = queue.Queue(maxsize=1)
        self._guard = threading.Lock()
        self._busy = False
        self._shutdown_requested = threading.Event()
        self._disconnect_requested = threading.Event()
        self._deactivate_requested = threading.Event()
        self._connection = None
        self._settings = None

    @property
    def busy(self) -> bool:
        with self._guard:
            return self._busy or self._disconnect_requested.is_set() or self._deactivate_requested.is_set()

    def submit(self, action: str, **arguments) -> bool:
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown GUI command: {action}")
        with self._guard:
            if self._shutdown_requested.is_set() or self._disconnect_requested.is_set():
                return False
            if action == "deactivate":
                self._deactivate_requested.set()
                return True
            if self._busy or self._deactivate_requested.is_set():
                return False
            self._busy = True
            self._jobs.put_nowait((action, arguments))
            return True

    def disconnect(self) -> None:
        self._disconnect_requested.set()

    def shutdown(self) -> None:
        self._shutdown_requested.set()

    def _cancel_point(self) -> None:
        if self._shutdown_requested.is_set() or self._disconnect_requested.is_set() or self._deactivate_requested.is_set():
            raise _Cancelled()

    def _discard_pending(self) -> None:
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break
        with self._guard:
            self._busy = False

    def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        self._settings = None
        if connection is not None:
            transport.close_serial_connection(connection)

    def _perform(self, action: str, arguments: dict):
        if action == "ports":
            return transport.list_com_ports()
        if action == "connect":
            if self._connection is not None:
                raise ValueError("A connection is already open.")
            settings = arguments["settings"]
            if not isinstance(settings, ConnectionSettings):
                raise TypeError("Invalid connection settings.")
            self._connection = transport.open_serial_connection(
                settings.port, baudrate=settings.baudrate, timeout=settings.timeout,
                write_timeout=settings.timeout,
            )
            self._settings = settings
            self._cancel_point()
            packet = commands.qb_cmd_ping(settings.device_id, self._connection)
            return {"settings": settings, "packet": packet}
        if self._connection is None or self._settings is None:
            raise transport.QbConnectionError("No device connected.")
        settings, connection = self._settings, self._connection
        profile = PROFILES[settings.profile]
        device_id = settings.device_id
        if action == "ping":
            return commands.qb_cmd_ping(device_id, connection)
        if action == "snapshot":
            values = {}
            for name, function in (
                ("measurements", commands.qb_cmd_get_measurements),
                ("currents", commands.qb_cmd_get_currents),
                ("activation", commands.qb_cmd_get_activate),
                ("inputs", commands.qb_cmd_get_inputs),
            ):
                self._cancel_point()
                values[name] = function(device_id, connection)
            return values
        if action == "info":
            return commands.qb_cmd_get_info(device_id, connection, profile=profile)
        if action == "motor_commands":
            return commands.qb_cmd_get_motor_commands(device_id, connection, profile=profile)
        if action == "activate":
            return commands.qb_cmd_activate(device_id, connection, mask=arguments["mask"])
        if action == "deactivate":
            return commands.qb_cmd_deactivate(device_id, connection)
        if action == "set_inputs":
            first, second, limits = arguments["first"], arguments["second"], arguments["limits"]
            if not isinstance(limits, ReferenceLimits):
                raise ValueError("Define the device reference limits before sending references.")
            limits.validate(first, second)
            if arguments.get("ack", False):
                return commands.qb_cmd_set_inputs_ack(device_id, first, second, connection, profile=profile)
            return commands.qb_cmd_set_inputs(device_id, first, second, connection)
        raise ValueError(f"Unsupported command: {action}")

    def _execute(self, action: str, arguments: dict) -> None:
        try:
            value = self._perform(action, arguments)
            if action == "deactivate" or not (
                self._shutdown_requested.is_set() or self._disconnect_requested.is_set()
                or self._deactivate_requested.is_set()
            ):
                self.events.put(WorkerEvent("result", action, value))
        except _Cancelled:
            pass
        except Exception as exc:
            # A failed transaction may leave delayed replies; require a fresh session.
            error = f"{type(exc).__name__}: {exc}"
            try:
                self._close_connection()
            except Exception as close_error:
                error += f"; closing port: {close_error}"
            self.events.put(WorkerEvent("error", action, error=error))
        finally:
            with self._guard:
                self._busy = False

    def run(self) -> None:
        try:
            while True:
                if self._deactivate_requested.is_set():
                    self._discard_pending()
                    self._execute("deactivate", {})
                    self._deactivate_requested.clear()
                if self._shutdown_requested.is_set():
                    break
                if self._disconnect_requested.is_set():
                    self._discard_pending()
                    try:
                        self._close_connection()
                        self.events.put(WorkerEvent("disconnected"))
                    except Exception as exc:
                        self.events.put(WorkerEvent("error", "disconnect", error=str(exc)))
                    self._disconnect_requested.clear()
                    continue
                try:
                    action, arguments = self._jobs.get(timeout=0.05)
                except queue.Empty:
                    continue
                if self._shutdown_requested.is_set() or self._disconnect_requested.is_set() or self._deactivate_requested.is_set():
                    continue
                self._execute(action, arguments)
        finally:
            self._discard_pending()
            try:
                self._close_connection()
            except Exception as exc:
                self.events.put(WorkerEvent("error", "disconnect", error=str(exc)))
            self.events.put(WorkerEvent("stopped"))
