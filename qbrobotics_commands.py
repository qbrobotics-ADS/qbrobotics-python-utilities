#######################################################################################
####################    Python libraries for qbrobotics devices    ####################
#######################################################################################
"""Typed command wrappers. Select a firmware profile for commands with differing IDs."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Optional

import serial

from qbrobotics_serial_utils import (
    CMD_PING, CMD_GET_INFO, CMD_BOOTLOADER, CMD_ACTIVATE, CMD_GET_ACTIVATE,
    CMD_SET_INPUTS, CMD_GET_INPUTS, CMD_GET_MEASUREMENTS, CMD_GET_CURRENTS,
    CMD_SET_BAUDRATE, CMD_ACTIVATE_ACK, CMD_SET_INPUTS_ACK, CMD_GET_MOTOR_COMMANDS,
    DEFAULT_TIMEOUT, Packet, QbConnectionError, QbProtocolError, connection_lock,
    drain_output, request_packet, request_text, send_packet, validate_integer,
)

######################################################################################
# WITHOUT PAYLOAD THE CHECKSUM IS EQUAL TO COMMAND
# PACKAGE LENGTH INCLUDES COMMAND, PAYLOAD AND CHECKSUM
######################################################################################


class QbUnsupportedCommandError(QbProtocolError):
    """The selected firmware profile does not define this command."""


class QbDeviceError(QbProtocolError):
    """The device returned an unsuccessful acknowledgment."""


@dataclass(frozen=True)
class CommandProfile:
    """Firmware-specific command IDs and GET_INFO framing.

    None means unsupported, not a command to probe automatically. The repository
    profile preserves the original experimental IDs; verify them against firmware.
    """

    name: str
    set_inputs_ack: Optional[int] = CMD_SET_INPUTS_ACK
    activate_ack: Optional[int] = None
    get_motor_commands: Optional[int] = None
    info_format: str = "framed"
    info_length_scale: int = 32
    bootloader_ack_command: int = CMD_BOOTLOADER

    def __post_init__(self) -> None:
        validate_integer(self.bootloader_ack_command, "bootloader_ack_command", 0, 255)
        for field in ("set_inputs_ack", "activate_ack", "get_motor_commands", "bootloader_ack_command"):
            value = getattr(self, field)
            if value is not None:
                validate_integer(value, field, 0, 255)
        if self.info_format not in ("framed", "text"):
            raise ValueError("info_format must be 'framed' or 'text'")
        validate_integer(self.info_length_scale, "info_length_scale", 1, 32)
        if self.info_length_scale not in (1, 32):
            raise ValueError("info_length_scale must be 1 or 32")


RESEARCH_PROFILE = CommandProfile("research")
LEGACY_PROFILE = CommandProfile(
    "legacy", set_inputs_ack=None, info_format="text", info_length_scale=1,
    bootloader_ack_command=1,
)
REPOSITORY_PROFILE = CommandProfile(
    "repository", set_inputs_ack=148, activate_ack=CMD_ACTIVATE_ACK,
    get_motor_commands=CMD_GET_MOTOR_COMMANDS, info_length_scale=1,
)


def _profile_command(command: Optional[int], name: str, profile: CommandProfile) -> int:
    if command is None:
        raise QbUnsupportedCommandError(f"{name} is not defined by profile {profile.name!r}")
    return command


def _inputs(input_1: int, input_2: int) -> bytes:
    first = validate_integer(input_1, "input_1", -32768, 32767)
    second = validate_integer(input_2, "input_2", -32768, 32767)
    return struct.pack(">hh", first, second)


def _int16_values(packet: Packet, expected_count: Optional[int] = None) -> tuple[int, ...]:
    payload = packet.payload
    # Calcola il numero di encoder (misure) disponibili
    count = len(payload) // 2
    if not payload or len(payload) % 2 or (expected_count is not None and count != expected_count):
        raise QbProtocolError(f"Invalid int16 payload length: {len(payload)}")
    # Loop per leggere i valori di payload e calcolare meas
    return struct.unpack(f">{count}h", payload)


def _ack(packet: Packet) -> Packet:
    # Current firmware echoes the command; the optional ACK payload is 1 on success.
    # Legacy bootloader ACKs may carry ACK_OK as the command and no payload.
    if packet.payload not in (b"", b"\x01"):
        raise QbDeviceError(f"Device rejected command {packet.command}: {packet.payload.hex()}")
    return packet


### CMD_PING ###
# cmd = 0 # 0 --> CMD_PING
# NO PAYLOAD
def qb_cmd_ping(ID: int, serial_connection: serial.SerialBase, *, timeout: Optional[float] = None) -> Packet:
    """Return a ping Packet, supporting both empty legacy replies and four-byte S/N."""
    packet = request_packet(ID, serial_connection, [CMD_PING], timeout=timeout)
    if len(packet.payload) not in (0, 4):
        raise QbProtocolError("Ping payload must be empty or contain a four-byte serial number")
    return packet


def qb_cmd_ping_reverse(ID: int, serial_connection: serial.SerialBase, *, timeout: Optional[float] = None) -> Packet:
    """Diagnostic only: transmit a reversed frame and wait for a normal framed reply."""
    return request_packet(ID, serial_connection, [CMD_PING], timeout=timeout, reverse=True)


### CMD_GET_INFO ###
# cmd = 6 # 6 --> CMD_GET_INFO, NEED PARAMS
# PAYLOAD: 0 , 0
# [ : : , ID , 4 , 6 , 0 , 0 , 6 ]
def qb_cmd_get_info(
    ID: int, serial_connection: serial.SerialBase, *, info_type: int = 0,
    profile: CommandProfile = RESEARCH_PROFILE, timeout: Optional[float] = None,
    idle_timeout: float = 0.05,
) -> str:
    """Read framed/scaled modern info, or explicitly selected legacy text."""
    info_type = validate_integer(info_type, "info_type", 0, 65535)
    pkt = bytes([CMD_GET_INFO]) + struct.pack(">H", info_type)
    if profile.info_format == "text":
        return request_text(ID, serial_connection, pkt, timeout=timeout, idle_timeout=idle_timeout)
    packet = request_packet(
        ID, serial_connection, pkt, timeout=timeout, length_scale=profile.info_length_scale,
    )
    try:
        return packet.payload.rstrip(b"\0").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise QbProtocolError("Info text is not valid UTF-8") from exc


### CMD_BOOTLOADER ###
# cmd = 9 # 9 --> CMD_BOOTLOADER
# NO PAYLOAD
def qb_cmd_boot(
    ID: int, serial_connection: serial.SerialBase, *, profile: CommandProfile = RESEARCH_PROFILE,
    timeout: Optional[float] = None,
) -> Packet:
    """Enter the bootloader and validate its acknowledgment; never retried automatically."""
    return _ack(request_packet(
        ID, serial_connection, [CMD_BOOTLOADER], timeout=timeout,
        response_command=profile.bootloader_ack_command,
    ))


### CMD_ACTIVATE ###
# cmd = 128 # 128 --> CMD_ACTIVATE, NEED PARAMS
def qb_cmd_activate(ID: int, serial_connection: serial.SerialBase, mask: int = 0x03) -> bool:
    """Send activation bitmask 0..3. Zero deactivates; no ACK is expected."""
    mask = validate_integer(mask, "mask", 0, 3)
    return send_packet(ID, serial_connection, [CMD_ACTIVATE, mask])


def qb_cmd_deactivate(ID: int, serial_connection: serial.SerialBase) -> bool:
    """Deactivate both motors without expecting a reply."""
    return qb_cmd_activate(ID, serial_connection, mask=0)


### CMD_ACTIVATE_ACK ###
def qb_cmd_activate_ack(
    ID: int, serial_connection: serial.SerialBase, mask: int = 0x01, *,
    profile: CommandProfile = RESEARCH_PROFILE, timeout: Optional[float] = None,
) -> Packet:
    """Activate with ACK only on firmware explicitly defining this command."""
    cmd = _profile_command(profile.activate_ack, "ACTIVATE_ACK", profile)
    mask = validate_integer(mask, "mask", 0, 3)
    return _ack(request_packet(ID, serial_connection, [cmd, mask], timeout=timeout))


### CMD_GET_ACTIVATE ###
# cmd = 129 # 129 --> CMD_GET_ACTIVATE
# NO PAYLOAD
def qb_cmd_get_activate(ID: int, serial_connection: serial.SerialBase, *, timeout: Optional[float] = None) -> int:
    """Return the raw motor activation bitmask, preserving partial activation states."""
    packet = request_packet(ID, serial_connection, [CMD_GET_ACTIVATE], timeout=timeout)
    if len(packet.payload) != 1 or packet.payload[0] > 3:
        raise QbProtocolError("Activation reply must contain one bitmask in range 0..3")
    return packet.payload[0]


### CMD_SET_INPUTS ###
# cmd = 130 # 130 --> CMD_SET_INPUTS, NEED PARAMS
def qb_cmd_set_inputs(ID: int, input_1: int, input_2: int, serial_connection: serial.SerialBase) -> bool:
    """Send both signed 16-bit references, in network byte order; no ACK is expected."""
    pkt = bytes([CMD_SET_INPUTS]) + _inputs(input_1, input_2)
    return send_packet(ID, serial_connection, pkt)


def qb_cmd_set_inputs_ack(
    ID: int, input_1: int, input_2: int, serial_connection: serial.SerialBase, *,
    profile: CommandProfile = RESEARCH_PROFILE, timeout: Optional[float] = None,
) -> Packet:
    """Send references and validate the firmware-specific acknowledgment."""
    cmd = _profile_command(profile.set_inputs_ack, "SET_INPUTS_ACK", profile)
    pkt = bytes([cmd]) + _inputs(input_1, input_2)
    return _ack(request_packet(ID, serial_connection, pkt, timeout=timeout))


### CMD_GET_INPUTS ###
def qb_cmd_get_inputs(ID: int, serial_connection: serial.SerialBase, *, timeout: Optional[float] = None) -> tuple[int, ...]:
    """Return the two signed input references."""
    return _int16_values(request_packet(ID, serial_connection, [CMD_GET_INPUTS], timeout=timeout), 2)


### CMD_GET_MEASUREMENTS ###
def qb_cmd_get_measurements(ID: int, serial_connection: serial.SerialBase, *, timeout: Optional[float] = None) -> tuple[int, ...]:
    """Return all signed encoder readings in firmware ticks (count depends on device)."""
    return _int16_values(request_packet(ID, serial_connection, [CMD_GET_MEASUREMENTS], timeout=timeout))


### CMD_GET_CURRENTS ###
def qb_cmd_get_currents(ID: int, serial_connection: serial.SerialBase, *, timeout: Optional[float] = None) -> tuple[int, ...]:
    """Return signed motor currents in mA; count depends on device firmware."""
    return _int16_values(request_packet(ID, serial_connection, [CMD_GET_CURRENTS], timeout=timeout))


### CMD_SET_BAUDRATE ###
# cmd = 144 # 144 --> CMD_SET_BAUDRATE, NEED PARAMS
# PARAMS: CLOCK_DIVIDER
# [ : : , ID , 3 , 144 , PARAM , CRC ]
def qb_cmd_set_baudrate(
    ID: int, serial_connection: serial.SerialBase, clk_div: int, *,
    new_baudrate: Optional[int] = None, timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Send a single divider byte. Optionally change host baud after draining output.

    Divider-to-baud mapping is firmware-specific and is never guessed here.
    """
    clk_div = validate_integer(clk_div, "clk_div", 0, 255)
    if new_baudrate is not None:
        new_baudrate = validate_integer(new_baudrate, "new_baudrate", 1, 2147483647)
    # Validate drain timeout before changing device settings.
    if isinstance(timeout, bool) or not 0 < timeout < float("inf"):
        raise ValueError("timeout must be positive and finite")
    with connection_lock(serial_connection):
        result = send_packet(ID, serial_connection, [CMD_SET_BAUDRATE, clk_div])
        if new_baudrate is not None:
            drain_output(serial_connection, timeout=timeout)
            try:
                serial_connection.baudrate = new_baudrate
            except (serial.SerialException, OSError, ValueError) as exc:
                raise QbConnectionError("Device baud command sent, but host reconfiguration failed") from exc
        return result


### CMD_GET_MOTOR_COMMANDS ###
def qb_cmd_get_motor_commands(
    ID: int, serial_connection: serial.SerialBase, *, profile: CommandProfile = RESEARCH_PROFILE,
    timeout: Optional[float] = None,
) -> tuple[int, ...]:
    """Read firmware-specific motor commands only when the selected profile defines them."""
    cmd = _profile_command(profile.get_motor_commands, "GET_MOTOR_COMMANDS", profile)
    return _int16_values(request_packet(ID, serial_connection, [cmd], timeout=timeout))


### CMD_PING ###
# cmd = 0 # 0 --> CMD_PING
# NO PAYLOAD
def qb_cmd_test(ID: int, serial_connection: serial.SerialBase) -> bool:
    """Transmit a ping without receiving a reply (diagnostic compatibility helper)."""
    return send_packet(ID, serial_connection, [CMD_PING])


__all__ = [name for name in globals() if name.startswith(("CMD_", "qb_cmd_"))] + [
    "CommandProfile", "RESEARCH_PROFILE", "LEGACY_PROFILE", "REPOSITORY_PROFILE",
    "QbUnsupportedCommandError", "QbDeviceError",
]
