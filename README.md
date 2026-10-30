# qbrobotics Python Serial Utilities

Python utilities for binary serial communication with qbrobotics devices. Includes
validated framing, typed command results, bounded I/O, and a read-only CLI example.
Requires Python 3.9+ and pyserial 3.5. Hardware behavior depends on device and firmware;
the automated tests use simulated devices and pyserial's real `loop://` backend.

## Installation

```bash
git clone https://github.com/qbrobotics-ADS/qbrobotics-python-utilities.git
cd qbrobotics-python-utilities
python -m venv .venv
```

Activate the environment (`.venv\Scripts\Activate.ps1` on Windows PowerShell,
`source .venv/bin/activate` on Linux/macOS), then install:

```bash
python -m pip install -e .
```

For script-only use, `python -m pip install -r requirements.txt` also works.
Default connection settings are 2,000,000 baud, 8N1, and 0.5-second read/write timeouts.
No startup sleep or automatic probing of unrelated serial ports is performed.

## Quick start

```bash
qbrobotics-test --port COM3 --id 1
qbrobotics-test --port COM3 --id 1 --command measurements
qbrobotics-test --port COM3 --id 1 --command currents --timeout 1
qbrobotics-test --port COM3 --id 1 --command info --profile legacy
```

`python qbrobotics-modules-test.py` and `python -m qbrobotics_cli` are equivalent
entry points. Without `--port`, the CLI offers interactive selection. Press Enter
to cancel. Linux ports can be specified as `/dev/ttyUSB0`.

The CLI exposes read commands only, closes its connection on errors or interruption,
and returns status 0 on success/cancellation, 1 on communication errors, or 130 on
interruption. `--verbose` enables raw packet logging. Importing modules never opens
a port or prompts for input.

## Python API

```python
from qbrobotics_commands import qb_cmd_get_currents, qb_cmd_get_measurements, qb_cmd_ping
from qbrobotics_serial_utils import open_serial_connection, close_serial_connection, QbError

connection = open_serial_connection("COM3", timeout=0.5)
try:
    ping = qb_cmd_ping(1, connection)
    print(ping.device_id, ping.serial_number)  # None for legacy firmware without S/N
    positions = qb_cmd_get_measurements(1, connection)
    currents = qb_cmd_get_currents(1, connection)
    print(positions, currents)
except QbError as error:
    print(f"Communication failed: {error}")
finally:
    close_serial_connection(connection)
```

`Packet` is an immutable result with `device_id`, `command`, `payload`, and `raw`.
Its payload excludes the command and checksum. `serial_number` decodes four-byte
big-endian ping serial numbers; legacy ping responses may have an empty payload.

| Function | Result / behavior |
|---|---|
| `qb_cmd_ping(ID, connection)` | Validated `Packet`, optional `serial_number` |
| `qb_cmd_get_info(ID, connection, profile=...)` | UTF-8 information string |
| `qb_cmd_get_activate(ID, connection)` | Activation bitmask, 0..3 |
| `qb_cmd_get_inputs(ID, connection)` | Tuple of two signed references |
| `qb_cmd_get_measurements(ID, connection)` | Tuple of signed encoder readings, in firmware ticks |
| `qb_cmd_get_currents(ID, connection)` | Tuple of signed currents, in mA |
| `qb_cmd_activate(ID, connection, mask=3)` | Send only; `True` on completed write |
| `qb_cmd_deactivate(ID, connection)` | Send mask zero; no response expected |
| `qb_cmd_set_inputs(ID, input_1, input_2, connection)` | Send both references; no response expected |
| `qb_cmd_set_inputs_ack(ID, input_1, input_2, connection, profile=...)` | Validated acknowledgment `Packet` |
| `qb_cmd_activate_ack(ID, connection, mask=1, profile=...)` | Firmware-specific acknowledgment `Packet` |
| `qb_cmd_get_motor_commands(ID, connection, profile=...)` | Firmware-specific tuple of signed values |
| `qb_cmd_set_baudrate(ID, connection, clk_div)` | Send one integer divider byte |
| `qb_cmd_boot(ID, connection, profile=...)` | Enter bootloader and validate acknowledgment |

Reply-producing wrappers accept `timeout=`. Input references must be integers in
`[-32768, 32767]` and are encoded as big-endian signed int16. Floating-point values,
strings and booleans are rejected. Device-specific reference limits and control modes
remain the caller's responsibility; numeric wire limits are not physical motion limits.

Activation uses bits 0 and 1; mask 3 selects both motors, zero deactivates them.
The ACK variant retains the original default mask 1. Select the mask deliberately
for the target device. A completed send-only write does not confirm device execution.

## Firmware profiles and compatibility changes

Command IDs are not universal across qbrobotics firmware families. The public
[research command header](https://bitbucket.org/qbrobotics/qbrobotics-driver/src/production/libs/research/include/qbrobotics_research_api/qbrobotics_research_commands.h)
defines `SET_INPUTS_ACK = 147` and `GET_SYNERGIES = 149`. The original code in this
repository used `ACTIVATE_ACK = 147`, `SET_INPUTS_ACK = 148`, and
`GET_MOTOR_COMMANDS = 149`. Those mappings must not be mixed.

| Profile | SET_INPUTS_ACK | ACTIVATE_ACK | GET_MOTOR_COMMANDS | GET_INFO | Bootloader reply command |
|---|---:|---:|---:|---|---:|
| `RESEARCH_PROFILE` (default) | 147 | Unsupported | Unsupported | Framed; length in 32-byte units | 9 |
| `LEGACY_PROFILE` | Unsupported | Unsupported | Unsupported | Unframed text | 1 (`ACK_OK`) |
| `REPOSITORY_PROFILE` | 148 | 147 | 149 | Framed; length in bytes | 9 |

The research/legacy formats follow the public
[qbrobotics communication implementation](https://bitbucket.org/qbrobotics/qbrobotics-driver/src/production/libs/research/src/qbrobotics_research_api.cpp).
`REPOSITORY_PROFILE` preserves this repository's experimental mappings; it is not
evidence that a particular device supports them. Verify the target firmware first.
An unsupported wrapper raises `QbUnsupportedCommandError` before transmitting.

```python
from qbrobotics_commands import REPOSITORY_PROFILE, qb_cmd_get_motor_commands

# Use only after verifying that command 149 means motor commands on this firmware.
values = qb_cmd_get_motor_commands(1, connection, profile=REPOSITORY_PROFILE)
```

Use an explicit `CommandProfile`, or `dataclasses.replace()` on an existing profile,
for firmware with other mappings or a short framed info reply (`info_length_scale=1`).
Profiles do not automatically detect firmware, control mode, encoder count or units.
No command is retried automatically, including motion commands and bootloader entry.

Modern ACKs echo the command and may contain a one-byte status (`1` means success).
An empty ACK payload is accepted for firmware using command-only replies. Negative
or malformed ACK payloads are rejected. Legacy bootloader replies use command 1.

Legacy unframed info has no device ID, length or checksum to validate. It is read
until NUL or an inter-byte idle period (`idle_timeout=0.05` by default), within the
total timeout and a 65,536-byte limit. Increase `idle_timeout` for firmware with longer
gaps. Modern info uses the explicit length scale, preserves frame boundaries, checks
the checksum and removes trailing NUL padding before decoding.

Existing function names and positional arguments are retained. Intentional changes:

- Wrappers return usable values instead of only printing. Configure standard Python
  logging to inspect raw traffic.
- Communication failures raise exceptions instead of returning ambiguous `False`/`None`.
  Opening with `port=None` still returns `None` for cancelled selection.
- `close_all_serial_ports()` closes only connections opened by this library. It never
  enumerates or opens unrelated ports and cannot release ports held by another process.
- `CMD_SET_INPUTS_ACK` now follows the public research value 147. `CMD_ACTIVATE_ACK`
  and `CMD_GET_MOTOR_COMMANDS` remain repository-specific constants; prefer profiled wrappers.
- Broadcast ID 0 is allowed for send-only operations. Request/reply wrappers require
  IDs 1..255, because multiple broadcast replies cannot be correlated reliably.
- `timeout=None` or an external port configured nonblocking uses the finite default
  response deadline. Writes also use a finite deadline and handle partial writes.

## Baudrate changes

`clk_div` is one integer in `[0, 255]`, not a list or an iterable. Divider-to-baudrate
mapping depends on firmware and is not guessed. To also update the host:

```python
# divider and corresponding_baudrate must come from the target firmware specification.
qb_cmd_set_baudrate(1, connection, divider, new_baudrate=corresponding_baudrate)
```

The optional host update waits for the output queue with a deadline before changing
the serial baudrate. If it fails, the device may already have changed baudrate;
reconnect using its actual setting. Changing one device on a shared bus requires
coordinating all devices and the adapter.

## Low-level transport and errors

Outgoing frame: `b'::' + ID + LENGTH + COMMAND + PARAMETERS + CHECKSUM`.
For ordinary packets, `LENGTH = len(COMMAND + PARAMETERS) + 1`. The checksum is XOR
over command and parameters, excluding the header, ID and length. Ordinary outgoing
bodies contain 1..254 bytes. Incoming modern GET_INFO can use 32-byte length units.

`build_packet()` and `parse_packet()` operate on bytes. `receive_packet()` reads a
complete frame by length and leaves subsequent frames in the serial buffer. It checks
header, declared length and checksum; supply `device_id` and `command` to validate
correlation. `request_packet()` and every reply-producing wrapper always validate both
and hold one shared reentrant lock across transmission and reception.

The response deadline starts after transmission, while holding the connection lock.
All wrappers using the same serial object share the lock; direct external serial I/O
must use `connection_lock()` too. Calling `send_packet()` and `receive_packet()`
separately does not lock the interval between them; use `request_packet()` instead.

Catch `QbError`, or the more specific `QbConnectionError`, `QbTimeoutError`,
`QbProtocolError`, `QbChecksumError`, `QbDeviceError`, and `QbUnsupportedCommandError`.
Invalid caller arguments raise `ValueError`/`TypeError` before sending.

The protocol has no transaction sequence number. After a timeout, delayed replies
can remain in the bus or serial buffer. Re-establish synchronization before issuing
another command; the library does not silently flush pending data or retry commands.
`send_packet_reverse()` / `qb_cmd_ping_reverse()` are diagnostic compatibility helpers:
reversing a frame does not produce a valid normal qbrobotics request.

## Tests and build

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m build
```

Tests cover all byte values through pyserial `loop://`, fragmented and delayed replies,
concatenated frames, signed values, checksum/length/ID/command failures, read/write
deadlines, partial writes, firmware profiles, ACKs, shared-port concurrency and CLI
cleanup. CI runs the suite on Windows and Linux with Python 3.9, 3.11 and 3.13.
Tests never enumerate or command physical devices. Hardware validation on the target
device/firmware is still required.
