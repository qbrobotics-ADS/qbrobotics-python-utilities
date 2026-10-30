# serial_utils.py
"""Binary qbrobotics transport with bounded request/reply operations."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import operator
import sys
import threading
import time
from typing import Iterable, Optional
import weakref

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)

######################################################################################
########################## Funzioni Gestione Connessione Seriali #####################
######################################################################################

# COMMANDS
CMD_PING = 0
CMD_GET_INFO = 6
CMD_BOOTLOADER = 9
CMD_ACTIVATE = 128
CMD_GET_ACTIVATE = 129
CMD_SET_INPUTS = 130
CMD_GET_INPUTS = 131
CMD_GET_MEASUREMENTS = 132
CMD_GET_CURRENTS = 133
CMD_SET_BAUDRATE = 144
CMD_ACTIVATE_ACK = 147
CMD_SET_INPUTS_ACK = 147  # Public research API; repository firmware uses 148 (see profiles).
CMD_GET_MOTOR_COMMANDS = 149

DEFAULT_TIMEOUT = 0.5
HEADER = b"::"


class QbError(Exception):
    """Base class for communication failures."""


class QbConnectionError(QbError):
    """The connection is closed, unavailable, or failed during I/O."""


class QbTimeoutError(QbError, TimeoutError):
    """A read or write did not finish before its deadline."""


class QbProtocolError(QbError):
    """The reply does not match the expected protocol or device."""


class QbChecksumError(QbProtocolError):
    """The received checksum does not match the packet body."""


@dataclass(frozen=True)
class Packet:
    """Validated frame; payload excludes command and checksum."""

    device_id: int
    command: int
    payload: bytes
    raw: bytes

    @property
    def serial_number(self) -> Optional[int]:
        """Four-byte big-endian ping serial number, if supplied by firmware."""
        if self.command == CMD_PING and len(self.payload) == 4:
            return int.from_bytes(self.payload, "big")
        return None


_registry_lock = threading.Lock()
_connection_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_managed_connections: weakref.WeakSet = weakref.WeakSet()


def connection_lock(serial_connection: serial.SerialBase):
    """Return the shared reentrant lock for a connection, including external ones."""
    if serial_connection is None:
        raise QbConnectionError("Serial connection not available")
    with _registry_lock:
        lock = _connection_locks.get(serial_connection)
        if lock is None:
            lock = threading.RLock()
            _connection_locks[serial_connection] = lock
        return lock


def _require_open(serial_connection: serial.SerialBase) -> None:
    if serial_connection is None or not serial_connection.is_open:
        raise QbConnectionError("Serial connection not available or closed")


def validate_integer(value: int, name: str, minimum: int, maximum: int) -> int:
    """Accept integer-like values without silently truncating floats or booleans."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer, not bool")
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _duration(value: float, name: str = "timeout") -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be positive and finite")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def _response_timeout(serial_connection: serial.SerialBase, timeout: Optional[float]) -> float:
    if timeout is not None:
        return _duration(timeout)
    configured = serial_connection.timeout
    return _duration(configured) if configured not in (None, 0) else DEFAULT_TIMEOUT


def _restore_setting(serial_connection: serial.SerialBase, name: str, value) -> None:
    """Restore settings without hiding the original failure if a device was unplugged."""
    failing = sys.exc_info()[0] is not None
    try:
        setattr(serial_connection, name, value)
    except (serial.SerialException, OSError) as exc:
        if not failing:
            raise QbConnectionError(f"Could not restore serial {name}: {exc}") from exc
        logger.debug("Could not restore %s after I/O failure", name, exc_info=True)


def close_all_serial_ports() -> int:
    """Close only connections opened by open_serial_connection(), never other ports."""
    with _registry_lock:
        connections = list(_managed_connections)
    closed = 0
    for connection in connections:
        try:
            closed += int(close_serial_connection(connection))
        except QbConnectionError:
            logger.exception("Could not close serial port %s", connection.port)
    return closed


def list_com_ports() -> list[str]:
    """Restituisce una lista delle porte COM disponibili."""
    return [port.device for port in serial.tools.list_ports.comports()]


def choose_com_port() -> Optional[str]:
    """Select a port interactively; return None if absent or cancelled."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("Nessuna porta COM trovata.")
        return None
    print("\nPorte COM disponibili:")
    for idx, port in enumerate(ports):
        # Se vuoi più info: descrizione, ecc.:
        # print(f"[{idx}] {port.device} - {port.description}")
        print(f"[{idx}] {port.device} - {port.description}")
    while True:
        choice = input("Seleziona l'indice della porta COM (o premi Invio per annullare): ").strip()
        if not choice:
            return None
        try:
            idx = int(choice)
        except ValueError:
            print("Input non valido. Inserisci un numero intero.")
            continue
        if 0 <= idx < len(ports):
            return ports[idx].device
        print(f"Indice fuori range. Inserisci un numero tra 0 e {len(ports) - 1}.")


def open_serial_connection(
    port: Optional[str], baudrate: int = 2000000, bytesize: int = 8,
    parity: str = "N", timeout: Optional[float] = DEFAULT_TIMEOUT,
    *, write_timeout: float = DEFAULT_TIMEOUT,
) -> Optional[serial.Serial]:
    """Open and register one serial port. None means selection was cancelled."""
    if port is None:
        return None
    read_timeout = DEFAULT_TIMEOUT if timeout is None else _duration(timeout)
    write_timeout = _duration(write_timeout, "write_timeout")
    try:
        connection = serial.Serial(
            port=port, baudrate=baudrate, bytesize=bytesize, parity=parity,
            timeout=read_timeout, write_timeout=write_timeout,
        )
    except (serial.SerialException, OSError) as exc:
        raise QbConnectionError(f"Could not open serial port {port}: {exc}") from exc
    with _registry_lock:
        _managed_connections.add(connection)
    logger.info("Opened %s at %s baud", port, baudrate)
    return connection


def close_serial_connection(serial_connection: Optional[serial.SerialBase]) -> bool:
    """Chiude la connessione seriale fornita se è aperta."""
    if serial_connection is None:
        return False
    with connection_lock(serial_connection):
        try:
            was_open = serial_connection.is_open
            if was_open:
                serial_connection.close()
        except (serial.SerialException, OSError) as exc:
            raise QbConnectionError(f"Could not close serial port: {exc}") from exc
        with _registry_lock:
            _managed_connections.discard(serial_connection)
        return was_open


######################################################################################
########################### Funzioni per Invio e Ricezione Pacchetti #################
######################################################################################

def build_packet(device_id: int, pkt: Iterable[int]) -> bytes:
    """Build a frame from command plus parameters. ID zero is transmit-only broadcast."""
    device_id = validate_integer(device_id, "device_id", 0, 255)
    body = bytes(validate_integer(value, "packet byte", 0, 255) for value in pkt)
    if not 1 <= len(body) <= 254:
        raise ValueError("Packet body must contain 1 to 254 bytes, including the command")
    # Header: ':', ':', ID
    p_send = [58, 58, device_id]  # 58 refers to ':'
    # Payload length + LRC
    p_send.append(len(body) + 1)
    p_send.extend(body)
    p_send.append(LRC(body))
    return bytes(p_send)


def _write_packet(serial_connection: serial.SerialBase, packet: bytes) -> bool:
    with connection_lock(serial_connection):
        _require_open(serial_connection)
        original_timeout = serial_connection.write_timeout
        timeout = DEFAULT_TIMEOUT if original_timeout in (None, 0) else _duration(original_timeout)
        deadline = time.monotonic() + timeout
        try:
            offset = 0
            while offset < len(packet):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise QbTimeoutError("Timed out writing serial packet")
                serial_connection.write_timeout = remaining
                written = serial_connection.write(packet[offset:])
                if written is None or written <= 0:
                    raise QbConnectionError("Serial write made no progress")
                offset += written
        except QbError:
            raise
        except serial.SerialTimeoutException as exc:
            raise QbTimeoutError("Timed out writing serial packet") from exc
        except (serial.SerialException, OSError) as exc:
            raise QbConnectionError(f"Serial write failed: {exc}") from exc
        finally:
            _restore_setting(serial_connection, "write_timeout", original_timeout)
        # Do not call flush(): some drivers can wait indefinitely for hardware drain.
        logger.debug("TX %s: %s", serial_connection.port, packet.hex(" "))
        return True


def send_packet(device_id: int, serial_connection: serial.SerialBase, pkt: Iterable[int]) -> bool:
    """Send one validated frame. True confirms transmission, not device execution."""
    return _write_packet(serial_connection, build_packet(device_id, pkt))


def send_packet_reverse(device_id: int, serial_connection: serial.SerialBase, pkt: Iterable[int]) -> bool:
    """Diagnostic only: reverse the entire frame; this is not normal protocol traffic."""
    # Costruzione pacchetto originale
    packet = build_packet(device_id, pkt)
    # Inversione dell'ordine del pacchetto
    p_send_reversed = packet[::-1]  # Giriamo tutta la lista
    # Invio del pacchetto invertito
    return _write_packet(serial_connection, p_send_reversed)


def _length_scale(value: int) -> int:
    value = validate_integer(value, "length_scale", 1, 32)
    if value not in (1, 32):
        raise ValueError("length_scale must be 1 or 32")
    return value


def parse_packet(
    raw: bytes, *, device_id: Optional[int] = None, command: Optional[int] = None,
    length_scale: int = 1,
) -> Packet:
    """Validate exactly one complete frame before exposing its payload."""
    if device_id is not None:
        device_id = validate_integer(device_id, "device_id", 1, 255)
    if command is not None:
        command = validate_integer(command, "command", 0, 255)
    length_scale = _length_scale(length_scale)
    raw = bytes(raw)
    if len(raw) < 6 or raw[:2] != HEADER:
        raise QbProtocolError("Missing header or truncated packet")
    if raw[2] == 0:
        raise QbProtocolError("A device reply cannot have broadcast ID zero")
    if length_scale != 1 and raw[4] != CMD_GET_INFO:
        raise QbProtocolError("Scaled lengths are supported only for GET_INFO")
    if raw[3] * length_scale < 2 or len(raw) != 4 + raw[3] * length_scale:
        raise QbProtocolError("Packet length does not match its length byte")
    if LRC(raw[4:-1]) != raw[-1]:
        raise QbChecksumError("Packet checksum mismatch")
    if device_id is not None and raw[2] != device_id:
        raise QbProtocolError(f"Expected device {device_id}, received {raw[2]}")
    if command is not None and raw[4] != command:
        raise QbProtocolError(f"Expected command {command}, received {raw[4]}")
    # PARSE THE PAYLOAD
    return Packet(raw[2], raw[4], raw[5:-1], raw)


def _read_exact(serial_connection: serial.SerialBase, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QbTimeoutError(f"Timed out receiving packet ({len(data)}/{size} bytes in current field)")
        serial_connection.timeout = remaining
        chunk = serial_connection.read(size - len(data))
        if chunk:
            data.extend(chunk)
        else:
            # Avoid a busy loop for backends which return before their configured timeout.
            time.sleep(min(0.001, max(0, deadline - time.monotonic())))
    return bytes(data)


def receive_packet(
    serial_connection: serial.SerialBase, command: Optional[int],
    device_id: Optional[int] = None, *, timeout: Optional[float] = None,
    length_scale: int = 1,
) -> Packet:
    """Read one frame by length, preserving any following frame in the serial buffer."""
    length_scale = _length_scale(length_scale)
    if command is not None:
        command = validate_integer(command, "command", 0, 255)
    if device_id is not None:
        device_id = validate_integer(device_id, "device_id", 1, 255)
    with connection_lock(serial_connection):
        _require_open(serial_connection)
        deadline = time.monotonic() + _response_timeout(serial_connection, timeout)
        original_timeout = serial_connection.timeout
        try:
            matched = 0
            while matched < len(HEADER):
                byte = _read_exact(serial_connection, 1, deadline)
                matched = matched + 1 if byte == b":" else 0
            fields = _read_exact(serial_connection, 2, deadline)
            length = fields[1] * length_scale
            if length < 2:
                raise QbProtocolError("Packet length must include command and checksum")
            body = _read_exact(serial_connection, length, deadline)
            packet = parse_packet(
                HEADER + fields + body, device_id=device_id, command=command,
                length_scale=length_scale,
            )
        except QbError:
            raise
        except (serial.SerialException, OSError) as exc:
            raise QbConnectionError(f"Serial read failed: {exc}") from exc
        finally:
            _restore_setting(serial_connection, "timeout", original_timeout)
        logger.debug("RX %s: %s", serial_connection.port, packet.raw.hex(" "))
        return packet


def request_packet(
    device_id: int, serial_connection: serial.SerialBase, pkt: Iterable[int], *,
    timeout: Optional[float] = None, response_command: Optional[int] = None,
    reverse: bool = False, length_scale: int = 1,
) -> Packet:
    """Serialize a request/reply transaction; broadcast replies are ambiguous."""
    length_scale = _length_scale(length_scale)
    device_id = validate_integer(device_id, "device_id", 1, 255)
    packet = build_packet(device_id, pkt)
    expected = packet[4] if response_command is None else validate_integer(response_command, "response_command", 0, 255)
    if length_scale != 1 and expected != CMD_GET_INFO:
        raise ValueError("Scaled lengths are supported only for GET_INFO")
    with connection_lock(serial_connection):
        _require_open(serial_connection)
        # Validate the deadline before transmitting commands which can move hardware.
        duration = _response_timeout(serial_connection, timeout)
        _write_packet(serial_connection, packet[::-1] if reverse else packet)
        return receive_packet(
            serial_connection, expected, device_id, timeout=duration, length_scale=length_scale,
        )


def receive_text(
    serial_connection: serial.SerialBase, *, timeout: Optional[float] = None,
    idle_timeout: float = 0.05, max_bytes: int = 65536,
) -> str:
    """Read legacy unframed GET_INFO text until NUL or an inter-byte idle period.

    A total deadline and size limit bound the operation. Firmware must guarantee
    gaps shorter than idle_timeout; use framed mode when available.
    """
    idle_timeout = _duration(idle_timeout, "idle_timeout")
    max_bytes = validate_integer(max_bytes, "max_bytes", 1, 1048576)
    with connection_lock(serial_connection):
        _require_open(serial_connection)
        deadline = time.monotonic() + _response_timeout(serial_connection, timeout)
        original_timeout = serial_connection.timeout
        data = bytearray()
        last_byte_at = None
        try:
            while True:
                now = time.monotonic()
                remaining = deadline - now
                if remaining <= 0:
                    raise QbTimeoutError("Timed out receiving complete info text")
                idle_remaining = idle_timeout if last_byte_at is None else idle_timeout - (now - last_byte_at)
                if last_byte_at is not None and idle_remaining <= 0:
                    break
                serial_connection.timeout = min(remaining, idle_remaining) if data else remaining
                chunk = serial_connection.read(1)
                if not chunk:
                    time.sleep(min(0.001, max(0, deadline - time.monotonic())))
                    continue
                if chunk == b"\0":
                    break
                if len(data) >= max_bytes:
                    raise QbProtocolError("Info text exceeds size limit")
                data.extend(chunk)
                last_byte_at = time.monotonic()
            return data.decode("utf-8")
        except QbError:
            raise
        except UnicodeDecodeError as exc:
            raise QbProtocolError("Info text is not valid UTF-8") from exc
        except (serial.SerialException, OSError) as exc:
            raise QbConnectionError(f"Serial read failed: {exc}") from exc
        finally:
            _restore_setting(serial_connection, "timeout", original_timeout)


def request_text(
    device_id: int, serial_connection: serial.SerialBase, pkt: Iterable[int], *,
    timeout: Optional[float] = None, idle_timeout: float = 0.05,
) -> str:
    """Serialize a legacy GET_INFO request and its unframed text response."""
    device_id = validate_integer(device_id, "device_id", 1, 255)
    packet = build_packet(device_id, pkt)
    if packet[4] != CMD_GET_INFO:
        raise ValueError("Text replies are supported only for GET_INFO")
    idle_timeout = _duration(idle_timeout, "idle_timeout")
    with connection_lock(serial_connection):
        _require_open(serial_connection)
        duration = _response_timeout(serial_connection, timeout)
        _write_packet(serial_connection, packet)
        return receive_text(serial_connection, timeout=duration, idle_timeout=idle_timeout)


def drain_output(serial_connection: serial.SerialBase, *, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Wait for the output queue with a deadline before changing host baudrate."""
    duration = _duration(timeout)
    with connection_lock(serial_connection):
        _require_open(serial_connection)
        deadline = time.monotonic() + duration
        try:
            while serial_connection.out_waiting:
                if time.monotonic() >= deadline:
                    raise QbTimeoutError("Timed out draining serial output")
                time.sleep(0.001)
        except QbError:
            raise
        except (serial.SerialException, OSError) as exc:
            raise QbConnectionError(f"Could not drain serial output: {exc}") from exc


######################################################################################
########################### Funzione di Utilità ######################################
######################################################################################

# Calculating Checksum LRC: Longitudinal Redundancy Check
def LRC(pkt: Iterable[int]) -> int:
    """Calcola il checksum LRC (Longitudinal Redundancy Check) di un pacchetto."""
    lrc = 0
    for value in pkt:
        lrc ^= validate_integer(value, "packet byte", 0, 255)
    return lrc


__all__ = [name for name in globals() if name.startswith("CMD_")] + [
    "DEFAULT_TIMEOUT", "Packet", "QbError", "QbConnectionError", "QbTimeoutError",
    "QbProtocolError", "QbChecksumError", "close_all_serial_ports", "list_com_ports",
    "choose_com_port", "open_serial_connection", "close_serial_connection", "build_packet",
    "send_packet", "send_packet_reverse", "parse_packet", "receive_packet", "request_packet",
    "receive_text", "request_text", "drain_output", "connection_lock", "validate_integer", "LRC",
]
