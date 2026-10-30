"""Regression coverage for binary framing, deadlines and transaction ownership."""

import concurrent.futures
import functools
import operator
import threading
import time
import unittest
from unittest import mock

import serial

import qbrobotics_serial_utils as transport


def reply(command, payload=b"", device_id=1, scale=1):
    body = bytes([command]) + payload
    length = len(body) + 1
    assert length % scale == 0
    checksum = functools.reduce(operator.xor, body, 0)
    return b"::" + bytes([device_id, length // scale]) + body + bytes([checksum])


class FakeSerial:
    def __init__(self, data=b"", *, chunk_size=1024, empty_reads=0, on_write=None):
        self.data = bytearray(data)
        self.chunk_size = chunk_size
        self.empty_reads = empty_reads
        self.on_write = on_write
        self.timeout = None
        self.write_timeout = None
        self.is_open = True
        self.port = "SIMULATED"
        self.baudrate = 2000000
        self.out_waiting = 0
        self.writes = []

    @property
    def in_waiting(self):
        raise AssertionError("A buffered-byte count must not decide whether a reply exists")

    def read(self, size):
        if self.empty_reads:
            self.empty_reads -= 1
            return b""
        count = min(size, self.chunk_size, len(self.data))
        result = bytes(self.data[:count])
        del self.data[:count]
        if not result:
            time.sleep(min(self.timeout or 0.001, 0.001))
        return result

    def write(self, data):
        self.writes.append(bytes(data))
        if self.on_write is not None:
            self.data.extend(self.on_write(bytes(data)))
        return len(data)

    def close(self):
        self.is_open = False


class ProtocolTests(unittest.TestCase):
    def test_known_ping_wire_format(self):
        self.assertEqual(transport.build_packet(1, [0]), b"::\x01\x02\x00\x00")

    def test_every_byte_round_trips_through_real_pyserial(self):
        # Includes printable bytes, quotes, backslash, newline, carriage return and NUL.
        with serial.serial_for_url("loop://", timeout=None, write_timeout=None) as connection:
            for payload in (bytes(range(253)), bytes(range(253, 256))):
                transport.send_packet(1, connection, bytes([132]) + payload)
                result = transport.receive_packet(connection, 132, 1)
                self.assertEqual(result.payload, payload)
                self.assertIsNone(connection.timeout)
                self.assertIsNone(connection.write_timeout)

    def test_delayed_fragmented_reply_and_next_frame_are_preserved(self):
        first = reply(132, b"\xff\x00\x00A\x00\n", device_id=132)
        second = reply(133, b"\xff\x00\xfe\x00")
        connection = FakeSerial(b"noise" + first + second, chunk_size=1, empty_reads=3)
        result = transport.receive_packet(connection, 132, 132, timeout=0.1)
        self.assertEqual(result.raw, first)
        self.assertEqual(result.payload, b"\xff\x00\x00A\x00\n")
        self.assertEqual(transport.receive_packet(connection, 133, 1).raw, second)

    def test_bad_checksum_is_rejected(self):
        raw = reply(132, b"\x00\x01\x00\x02\x00\x03")
        connection = FakeSerial(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(transport.QbChecksumError):
            transport.receive_packet(connection, 132, 1)
        self.assertIsNone(connection.timeout)

    def test_header_length_id_and_command_are_validated(self):
        valid = reply(132, b"\x00\x01")
        malformed = (
            b"xx" + valid[2:], valid[:-1], valid + b"\0", b"::\x01\x01\x84\x84",
            reply(132, b"\x00\x01", device_id=0),
        )
        for raw in malformed:
            with self.subTest(raw=raw), self.assertRaises(transport.QbProtocolError):
                transport.parse_packet(raw)
        for raw in (reply(132, device_id=2), reply(133)):
            with self.subTest(raw=raw), self.assertRaises(transport.QbProtocolError):
                transport.receive_packet(FakeSerial(raw), 132, 1)

    def test_empty_and_truncated_reads_expire_and_restore_timeout(self):
        for raw in (b"", b"noise", b"::", reply(132, b"\0\1")[:-1]):
            connection = FakeSerial(raw)
            started = time.monotonic()
            with self.subTest(raw=raw), self.assertRaises(transport.QbTimeoutError):
                transport.receive_packet(connection, 132, 1, timeout=0.015)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertIsNone(connection.timeout)

    def test_total_deadline_applies_to_slow_byte_stream(self):
        connection = FakeSerial(reply(132, b"\0\1\0\2\0\3"), chunk_size=1)
        read = connection.read

        def slow_read(size):
            time.sleep(min(connection.timeout, 0.005))
            return read(size)

        connection.read = slow_read
        with self.assertRaises(transport.QbTimeoutError):
            transport.receive_packet(connection, 132, 1, timeout=0.018)
        self.assertIsNone(connection.timeout)

    def test_scaled_info_frame_does_not_consume_following_frame(self):
        payload = b"Device info\n" + b"\0" * (318 - len(b"Device info\n"))
        info = reply(6, payload, scale=32)
        following = reply(0)
        connection = FakeSerial(info + following, chunk_size=3)
        packet = transport.receive_packet(connection, 6, 1, length_scale=32)
        self.assertEqual(packet.payload, payload)
        self.assertEqual(transport.parse_packet(info, length_scale=32), packet)
        self.assertEqual(transport.receive_packet(connection, 0, 1).raw, following)

    def test_invalid_parameters_never_transmit(self):
        connection = FakeSerial()
        for device_id, body in ((-1, [0]), (256, [0]), (1, []), (1, [0] * 255), (1, [256]), (1, ["0x01"])):
            with self.subTest(device_id=device_id, body=body), self.assertRaises((ValueError, TypeError)):
                transport.send_packet(device_id, connection, body)
        for kwargs in ({"timeout": 0}, {"timeout": float("nan")}, {"length_scale": 2}, {"length_scale": 32}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                transport.request_packet(1, connection, [0], **kwargs)
        with self.assertRaises(ValueError):
            transport.request_packet(0, connection, [0])
        self.assertFalse(connection.writes)
        self.assertTrue(transport.send_packet(0, connection, [128, 0]))

    def test_partial_writes_complete_and_zero_progress_fails(self):
        connection = FakeSerial()
        written = bytearray()

        def partial_write(data):
            written.extend(data[:2])
            return min(2, len(data))

        connection.write = partial_write
        self.assertTrue(transport.send_packet(1, connection, [0]))
        self.assertEqual(written, b"::\1\2\0\0")
        self.assertIsNone(connection.write_timeout)
        connection.write = lambda data: 0
        with self.assertRaises(transport.QbConnectionError):
            transport.send_packet(1, connection, [0])

    def test_write_timeout_and_disconnection_have_specific_errors(self):
        connection = FakeSerial()
        connection.write = mock.Mock(side_effect=serial.SerialTimeoutException("write timeout"))
        with self.assertRaises(transport.QbTimeoutError):
            transport.send_packet(1, connection, [0])
        self.assertIsNone(connection.write_timeout)
        connection.read = mock.Mock(side_effect=serial.SerialException("unplugged"))
        with self.assertRaises(transport.QbConnectionError):
            transport.receive_packet(connection, 0)
        self.assertIsNone(connection.timeout)
        connection.close()
        for operation in (
            lambda: transport.send_packet(1, connection, [0]),
            lambda: transport.receive_packet(connection, 0),
            lambda: transport.request_packet(1, None, [0]),
        ):
            with self.assertRaises(transport.QbConnectionError):
                operation()

    def test_two_threads_cannot_interleave_requests(self):
        waiting = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        second_write = threading.Event()
        connection = FakeSerial()

        def write(data):
            connection.writes.append(bytes(data))
            if len(connection.writes) > 1:
                second_write.set()
            connection.data.extend(reply(data[4], device_id=data[2]))
            return len(data)

        original_read = connection.read

        def read(size):
            if len(connection.writes) == 1:
                waiting.set()
                if not release.wait(1):
                    raise AssertionError("First transaction was not released")
            return original_read(size)

        def second_request():
            second_started.set()
            return transport.request_packet(2, connection, [129], timeout=0.5)

        connection.write, connection.read = write, read
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(transport.request_packet, 1, connection, [0], timeout=0.5)
            try:
                self.assertTrue(waiting.wait(1))
                second = pool.submit(second_request)
                self.assertTrue(second_started.wait(1))
                self.assertFalse(second_write.wait(0.03))
            finally:
                release.set()
            self.assertEqual(first.result(timeout=1).device_id, 1)
            self.assertEqual(second.result(timeout=1).device_id, 2)

    def test_close_all_owns_only_connections_it_opened(self):
        managed, unrelated = FakeSerial(), FakeSerial()
        self.addCleanup(transport.close_all_serial_ports)
        with mock.patch.object(transport.serial, "Serial", return_value=managed) as factory:
            self.assertIs(transport.open_serial_connection("SIMULATED"), managed)
            with mock.patch.object(transport.serial.tools.list_ports, "comports") as enumerate_ports:
                self.assertEqual(transport.close_all_serial_ports(), 1)
                enumerate_ports.assert_not_called()
            factory.assert_called_once()
        self.assertFalse(managed.is_open)
        self.assertTrue(unrelated.is_open)
        self.assertEqual(transport.close_all_serial_ports(), 0)

    def test_open_cancel_and_failure(self):
        self.assertIsNone(transport.open_serial_connection(None))
        with mock.patch.object(transport.serial, "Serial", side_effect=serial.SerialException("busy")):
            with self.assertRaises(transport.QbConnectionError):
                transport.open_serial_connection("SIMULATED")

    def test_unplug_during_cleanup_does_not_hide_checksum_failure(self):
        class UnpluggedSerial(FakeSerial):
            def __setattr__(self, name, value):
                if name == "timeout" and value is None and getattr(self, "unplugged", False):
                    raise serial.SerialException("Device unplugged during cleanup")
                super().__setattr__(name, value)

        raw = reply(0)
        connection = UnpluggedSerial(raw[:-1] + b"\x01")
        connection.unplugged = True
        with self.assertRaises(transport.QbChecksumError):
            transport.receive_packet(connection, 0)


if __name__ == "__main__":
    unittest.main()
