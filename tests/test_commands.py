"""Wire-level command regressions, including firmware-dependent formats."""

import struct
import time
import unittest
from unittest import mock

import qbrobotics_commands as commands
import qbrobotics_serial_utils as transport
from test_protocol import FakeSerial, reply


class CommandTests(unittest.TestCase):
    def test_set_inputs_sends_both_references_as_bytes(self):
        connection = FakeSerial()
        self.assertTrue(commands.qb_cmd_set_inputs(1, 1000, 2000, connection))
        self.assertEqual(connection.writes, [b"::\x01\x06\x82\x03\xe8\x07\xd0\xbe"])

    def test_signed_input_bounds_and_invalid_values(self):
        connection = FakeSerial()
        commands.qb_cmd_set_inputs(1, -32768, 32767, connection)
        self.assertEqual(connection.writes[0][5:-1], b"\x80\x00\x7f\xff")
        connection.writes.clear()
        for value in (-32769, 32768, 1.5, "100", True):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                commands.qb_cmd_set_inputs(1, value, 0, connection)
        self.assertFalse(connection.writes)

    def test_signed_currents_and_encoder_values_are_returned(self):
        payload = struct.pack(">hh", -256, -512)
        self.assertEqual(commands.qb_cmd_get_currents(1, FakeSerial(reply(133, payload))), (-256, -512))
        payload = struct.pack(">hhhh", -32768, -1, 65, 32767)
        # ID equals command, and payload includes printable ASCII and command-like bytes.
        self.assertEqual(commands.qb_cmd_get_measurements(132, FakeSerial(reply(132, payload, 132))), (-32768, -1, 65, 32767))
        self.assertEqual(commands.qb_cmd_get_inputs(1, FakeSerial(reply(131, struct.pack(">hh", -1, 10)))), (-1, 10))

    def test_invalid_measurement_lengths_are_rejected(self):
        for payload in (b"", b"\0", b"\0\1\0"):
            with self.subTest(payload=payload), self.assertRaises(transport.QbProtocolError):
                commands.qb_cmd_get_measurements(1, FakeSerial(reply(132, payload)))
        with self.assertRaises(transport.QbProtocolError):
            commands.qb_cmd_get_inputs(1, FakeSerial(reply(131, b"\0\1")))

    def test_ping_supports_legacy_and_serial_number_replies(self):
        packet = commands.qb_cmd_ping(1, FakeSerial(reply(0)))
        self.assertIsInstance(packet, transport.Packet)
        self.assertIsNone(packet.serial_number)
        packet = commands.qb_cmd_ping(1, FakeSerial(reply(0, b"\x12\x34\x56\x78")))
        self.assertEqual(packet.serial_number, 0x12345678)
        with self.assertRaises(transport.QbProtocolError):
            commands.qb_cmd_ping(1, FakeSerial(reply(0, b"\1")))

    def test_activation_and_set_inputs_do_not_wait_for_nonexistent_ack(self):
        connection = FakeSerial()
        connection.read = mock.Mock(side_effect=AssertionError("Unexpected read"))
        self.assertTrue(commands.qb_cmd_activate(1, connection))
        self.assertTrue(commands.qb_cmd_deactivate(1, connection))
        self.assertTrue(commands.qb_cmd_set_inputs(1, 0, -1, connection))
        self.assertEqual(connection.writes[0], b"::\1\3\x80\3\x83")
        self.assertEqual(connection.writes[1], b"::\1\3\x80\0\x80")

    def test_activation_status_is_returned_and_validated(self):
        self.assertEqual(commands.qb_cmd_get_activate(1, FakeSerial(reply(129, b"\3"))), 3)
        for payload in (b"", b"\4", b"\0\0"):
            with self.subTest(payload=payload), self.assertRaises(transport.QbProtocolError):
                commands.qb_cmd_get_activate(1, FakeSerial(reply(129, payload)))

    def test_firmware_profile_controls_ack_ids_and_success(self):
        for profile, command in ((commands.RESEARCH_PROFILE, 147), (commands.REPOSITORY_PROFILE, 148)):
            connection = FakeSerial(reply(command, b"\1"))
            packet = commands.qb_cmd_set_inputs_ack(1, -100, 200, connection, profile=profile)
            self.assertEqual(packet.command, command)
            self.assertEqual(connection.writes[0][4:-1], bytes([command]) + struct.pack(">hh", -100, 200))
            with self.assertRaises(commands.QbDeviceError):
                commands.qb_cmd_set_inputs_ack(1, 0, 0, FakeSerial(reply(command, b"\0")), profile=profile)

    def test_ambiguous_firmware_commands_require_supported_profile(self):
        connection = FakeSerial()
        for function in (commands.qb_cmd_activate_ack, commands.qb_cmd_get_motor_commands):
            with self.assertRaises(commands.QbUnsupportedCommandError):
                function(1, connection)
        self.assertFalse(connection.writes)
        connection = FakeSerial(reply(147, b"\1"))
        commands.qb_cmd_activate_ack(1, connection, profile=commands.REPOSITORY_PROFILE)
        self.assertEqual(connection.writes[0][4:-1], b"\x93\1")
        self.assertEqual(
            commands.qb_cmd_get_motor_commands(1, FakeSerial(reply(149, b"\xff\x00\x00A")), profile=commands.REPOSITORY_PROFILE),
            (-256, 65),
        )

    def test_bootloader_ack_is_checked_without_retries(self):
        for profile, response_command in ((commands.RESEARCH_PROFILE, 9), (commands.LEGACY_PROFILE, 1)):
            connection = FakeSerial(reply(response_command, b"\1"))
            commands.qb_cmd_boot(1, connection, profile=profile)
            self.assertEqual(len(connection.writes), 1)
        connection = FakeSerial(reply(9, b"\0"))
        with self.assertRaises(commands.QbDeviceError):
            commands.qb_cmd_boot(1, connection)
        self.assertEqual(len(connection.writes), 1)

    def test_info_supports_scaled_short_and_legacy_text(self):
        payload = b"Firmware info\n" + b"\0" * (318 - len(b"Firmware info\n"))
        connection = FakeSerial(reply(6, payload, scale=32), chunk_size=1)
        self.assertEqual(commands.qb_cmd_get_info(1, connection), "Firmware info\n")
        self.assertEqual(connection.writes, [b"::\1\4\6\0\0\6"])
        connection = FakeSerial(reply(6, b"Short info"))
        self.assertEqual(commands.qb_cmd_get_info(1, connection, profile=commands.REPOSITORY_PROFILE), "Short info")
        connection = FakeSerial(b"Legacy info\n\0", chunk_size=1, empty_reads=2)
        self.assertEqual(commands.qb_cmd_get_info(1, connection, profile=commands.LEGACY_PROFILE), "Legacy info\n")
        self.assertIsNone(connection.timeout)

    def test_legacy_text_idle_deadline_size_and_encoding(self):
        self.assertEqual(transport.receive_text(FakeSerial(b"Info"), timeout=0.1), "Info")
        for data, kwargs, error in (
            (b"", {"timeout": 0.01}, transport.QbTimeoutError),
            (b"ABCDE", {"max_bytes": 4}, transport.QbProtocolError),
            (b"\xff\0", {}, transport.QbProtocolError),
        ):
            connection = FakeSerial(data)
            with self.subTest(data=data), self.assertRaises(error):
                transport.receive_text(connection, **kwargs)
            self.assertIsNone(connection.timeout)

    def test_legacy_text_total_deadline_rejects_incomplete_stream(self):
        connection = FakeSerial()

        def endless_read(size):
            time.sleep(min(connection.timeout, 0.003))
            return b"A"

        connection.read = endless_read
        with self.assertRaises(transport.QbTimeoutError):
            transport.receive_text(connection, timeout=0.015, idle_timeout=0.1)
        self.assertIsNone(connection.timeout)

    def test_baudrate_accepts_integer_divider_and_can_update_host(self):
        connection = FakeSerial()
        self.assertTrue(commands.qb_cmd_set_baudrate(1, connection, 3, new_baudrate=460800))
        self.assertEqual(connection.writes, [b"::\1\3\x90\3\x93"])
        self.assertEqual(connection.baudrate, 460800)

        for value in (-1, 256, [3], 3.0):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                commands.qb_cmd_set_baudrate(1, connection, value)
        self.assertEqual(len(connection.writes), 1)
        connection.out_waiting = 1
        with self.assertRaises(transport.QbTimeoutError):
            commands.qb_cmd_set_baudrate(1, connection, 3, new_baudrate=115200, timeout=0.01)
        self.assertEqual(connection.baudrate, 460800)

    def test_host_baudrate_rejection_reports_that_device_command_was_sent(self):
        connection = FakeSerial()
        with mock.patch.object(FakeSerial, "baudrate", new_callable=mock.PropertyMock, create=True) as baudrate:
            baudrate.side_effect = ValueError("Unsupported baud rate")
            with self.assertRaisesRegex(transport.QbConnectionError, "Device baud command sent"):
                commands.qb_cmd_set_baudrate(1, connection, 3, new_baudrate=1234567)
        self.assertEqual(len(connection.writes), 1)


if __name__ == "__main__":
    unittest.main()
