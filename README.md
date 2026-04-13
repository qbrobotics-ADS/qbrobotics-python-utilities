# qbrobotics Python Serial Utilities

Python utilities for low-level serial communication with qbrobotics devices.

This repository contains a small set of scripts to test and inspect communication with qbrobotics devices over a serial port. It includes functions for serial port discovery and selection, serial connection management, packet construction and transmission, packet reception and basic parsing, plus a simple example script to test device communication.

The project is meant as a practical starting point for:
- low-level debugging
- command testing
- protocol inspection
- quick bring-up of qbrobotics serial communication in Python

---

## Features

- List available serial ports
- Select a COM port interactively
- Open and close a serial connection
- Build and send qbrobotics packets
- Compute packet LRC checksum
- Receive and parse basic replies
- Test several qbrobotics commands from Python
- Use a ready-to-run example script for quick validation

---

## Repository structure

```text
.
├── qbrobotics_serial_utils.py
├── qbrobotics_commands.py
└── qbrobotics-modules-test.py
```

### `qbrobotics_serial_utils.py`
Utility functions for serial communication:
- close all serial ports
- list available COM ports
- choose a COM port interactively
- open a serial connection
- close a serial connection
- send a packet
- send a reversed packet
- receive and parse a packet
- compute LRC checksum

### `qbrobotics_commands.py`
Command wrappers for qbrobotics devices, including:
- `CMD_PING`
- `CMD_GET_INFO`
- `CMD_BOOTLOADER`
- `CMD_ACTIVATE`
- `CMD_GET_ACTIVATE`
- `CMD_SET_INPUTS`
- `CMD_GET_INPUTS`
- `CMD_GET_MEASUREMENTS`
- `CMD_GET_CURRENTS`
- `CMD_GET_MOTOR_COMMANDS`
- `CMD_SET_BAUDRATE`

### `qbrobotics-modules-test.py`
Example script that:
1. closes any serial ports that may be open
2. lists the available serial ports
3. asks the user to select one
4. opens the selected serial connection
5. sends a `CMD_PING` to the selected device
6. closes the serial connection

---

## Requirements

- Python 3.x
- `pyserial`

Install dependencies with:

```bash
pip install pyserial
```

A minimal `requirements.txt` can be:

```txt
pyserial
```

---

## How it works

The communication flow is based on manual packet construction and parsing.

### Packet format

Outgoing packets are built in this form:

```text
: : , DEVICE_ID , LENGTH , PAYLOAD..., LRC
```

Where:
- `:` `:` is the packet header
- `DEVICE_ID` is the target device ID
- `LENGTH` is `len(payload) + 1`
- `PAYLOAD` includes the command byte and any command parameters
- `LRC` is the checksum calculated as XOR over the payload bytes

In the current implementation, the packet is assembled as:

```python
[58, 58, device_id, len(pkt) + 1, ...pkt..., LRC(pkt)]
```

where `58` is the ASCII value of `:`.

### Checksum

The checksum is an LRC computed as XOR over all bytes in the payload:

```python
def LRC(pkt):
    lrc = 0
    for i in pkt:
        lrc = (lrc ^ i)
    return lrc
```

### Receiving packets

Incoming data is read from the selected serial port and then parsed.  
The current receive logic includes specific parsing for:
- ping response
- measurements response
- current response

For example:
- `CMD_PING` extracts and prints the device serial number
- `CMD_GET_MEASUREMENTS` extracts encoder values
- `CMD_GET_CURRENTS` extracts motor current values

---

## Default serial settings

The serial connection is opened with the following default settings:

- baudrate: `2000000`
- bytesize: `8`
- parity: `N`
- timeout: `None`

These defaults are defined in:

```python
open_serial_connection(port, baudrate=2000000, bytesize=8, parity='N', timeout=None)
```

You can change them directly if your setup requires different serial parameters.

---

## Supported commands

The current code defines the following command IDs:

| Command | Value |
|---|---:|
| `CMD_PING` | `0` |
| `CMD_GET_INFO` | `6` |
| `CMD_BOOTLOADER` | `9` |
| `CMD_ACTIVATE` | `128` |
| `CMD_GET_ACTIVATE` | `129` |
| `CMD_SET_INPUTS` | `130` |
| `CMD_GET_INPUTS` | `131` |
| `CMD_GET_MEASUREMENTS` | `132` |
| `CMD_GET_CURRENTS` | `133` |
| `CMD_SET_BAUDRATE` | `144` |
| `CMD_ACTIVATE_ACK` | `147` |
| `CMD_SET_INPUTS_ACK` | `148` |
| `CMD_GET_MOTOR_COMMANDS` | `149` |

---

## Installation

Clone the repository:

```bash
git clone https://github.com/your-username/qbrobotics-python-serial-utils.git
cd qbrobotics-python-serial-utils
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Or directly:

```bash
pip install pyserial
```

---

## Usage

### Quick start

Run the example script:

```bash
python qbrobotics-modules-test.py
```

The script will:
- close currently open serial ports
- show the available COM ports
- ask you to choose a port
- open the selected serial connection
- send a ping command to the selected device ID
- print the received response
- close the serial connection

### Device ID

In the example script, the default device ID is:

```python
ID = 1
```

Change it if your target device uses a different ID.

Note:
- `ID = 0` is commonly used as broadcast

### Example communication flow

A minimal workflow is:

```python
from qbrobotics_serial_utils import *
from qbrobotics_commands import *

ID = 1

close_all_serial_ports()
serial_connection = open_serial_connection(choose_com_port())

if serial_connection:
    qb_cmd_ping(ID, serial_connection)
    close_serial_connection(serial_connection)
```

---

## Available command wrappers

The following helper functions are currently available:

- `qb_cmd_ping(ID, serial_connection)`
- `qb_cmd_ping_reverse(ID, serial_connection)`
- `qb_cmd_get_info(ID, serial_connection)`
- `qb_cmd_boot(ID, serial_connection)`
- `qb_cmd_activate(ID, serial_connection)`
- `qb_cmd_activate_ack(ID, serial_connection)`
- `qb_cmd_get_activate(ID, serial_connection)`
- `qb_cmd_set_inputs(ID, input_1, input_2, serial_connection)`
- `qb_cmd_get_inputs(ID, serial_connection)`
- `qb_cmd_get_measurements(ID, serial_connection)`
- `qb_cmd_get_currents(ID, serial_connection)`
- `qb_cmd_set_baudrate(ID, serial_connection, clk_div)`
- `qb_cmd_get_motor_commands(ID, serial_connection)`

To test another command, edit `qbrobotics-modules-test.py` and uncomment the desired function call.

For example:

```python
if serial_connection:
    qb_cmd_ping(ID, serial_connection)
    # qb_cmd_get_inputs(ID, serial_connection)
    # qb_cmd_get_measurements(ID, serial_connection)
    # qb_cmd_get_currents(ID, serial_connection)
    close_serial_connection(serial_connection)
```

---

## Example output

A typical execution may look like this:

```text
###############################################
### Python libraries for qbrobotics devices ###
###############################################

Porte COM disponibili:
[0] COM3
[1] COM4

Seleziona l'indice della porta COM: 0
Hai selezionato: COM3

Connessione seriale aperta su COM3 con baudrate 2000000.

COMMAND: CMD_PING
Sending the package to the device with ID 1 on COM3 port
Package sent: [58, 58, 1, 2, 0, 0]

Reading package on COM3
...
```

Actual output depends on the connected device and the received packet content.

---

## Notes and limitations

This repository is a practical test utility, not a complete production-ready Python package.

Current limitations include:
- console output is based on `print()` rather than structured logging
- response parsing is only partially specialized for some commands
- no package structure yet
- no automated tests
- error handling can be improved
- some command helpers may require refinement and validation on real hardware before general use

In particular, all command behavior should be validated on the target qbrobotics device and firmware version before being used in a larger application.

---

## Troubleshooting

### No COM ports found
Make sure:
- the device is physically connected
- the USB/serial adapter is detected by the operating system
- the correct drivers are installed

### Serial port cannot be opened
Possible causes:
- the port is already in use by another application
- the selected COM port is wrong
- permissions or driver issues prevent access

### No packet received
Check:
- device power
- device ID
- baudrate
- serial line wiring
- protocol compatibility with the connected device

### Unexpected parsing output
The receive logic is currently simple and should be checked against the exact packet format returned by your device firmware.


---

## License

Choose the license you prefer for the repository.

A simple and common choice is:

```text
MIT License
```

If you want to publish the repository publicly, add a `LICENSE` file accordingly.

---

## Disclaimer

This repository is intended for development, testing, and debugging of serial communication with qbrobotics devices. Always validate commands, packet structure, and device behavior on your specific hardware before using it in critical or production scenarios.
