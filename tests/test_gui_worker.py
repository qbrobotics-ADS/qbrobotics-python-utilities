"""Device-independent GUI worker tests; no physical serial ports are opened."""

import queue
import struct
import threading
import unittest
from unittest import mock

import qbrobotics_commands as commands
import qbrobotics_serial_utils as transport
from qbrobotics_gui_worker import ConnectionSettings, ReferenceLimits, SerialWorker
from test_protocol import FakeSerial, reply


def simulated_device(packet):
    command, device_id = packet[4], packet[2]
    payloads = {
        0: b"\x12\x34\x56\x78", 132: struct.pack(">hhh", -256, 1000, 2000),
        133: struct.pack(">hh", -512, 65), 129: b"\0", 131: struct.pack(">hh", 0, 0),
        147: b"\1", 148: b"\1", 149: struct.pack(">hh", -100, 100),
    }
    return reply(command, payloads[command], device_id) if command in payloads else b""


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.connection = FakeSerial(on_write=simulated_device)
        patcher = mock.patch.object(transport.serial, "Serial", return_value=self.connection)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.worker = SerialWorker()
        self.worker.start()
        self.addCleanup(self.stop_worker)

    def stop_worker(self):
        self.worker.shutdown()
        self.worker.join(timeout=2)
        self.assertFalse(self.worker.is_alive())

    def event(self, kind="result", action=None):
        while True:
            event = self.worker.events.get(timeout=2)
            if event.kind == kind and (action is None or event.action == action):
                return event
            if event.kind == "error" and kind != "error":
                self.fail(event.error)

    def connect(self, profile="research"):
        self.assertTrue(self.worker.submit("connect", settings=ConnectionSettings("SIMULATED", profile=profile)))
        return self.event(action="connect")

    def test_connect_verifies_ping_without_actuating(self):
        event = self.connect()
        self.assertEqual(event.value["packet"].serial_number, 0x12345678)
        self.assertEqual([packet[4] for packet in self.connection.writes], [0])
        self.worker.disconnect()
        self.event("disconnected")
        self.assertFalse(self.connection.is_open)

    def test_snapshot_reuses_signed_backend_results(self):
        self.connect()
        self.assertTrue(self.worker.submit("snapshot"))
        values = self.event(action="snapshot").value
        self.assertEqual(values["measurements"], (-256, 1000, 2000))
        self.assertEqual(values["currents"], (-512, 65))
        self.assertEqual(values["activation"], 0)
        self.assertEqual(values["inputs"], (0, 0))

    def test_reference_limits_are_enforced_at_worker_boundary(self):
        self.connect()
        limits = ReferenceLimits(-100, 100, 0, 200)
        self.worker.submit("set_inputs", first=-100, second=200, limits=limits, ack=True)
        self.event(action="set_inputs")
        self.assertEqual(self.connection.writes[-1][4:-1], b"\x93" + struct.pack(">hh", -100, 200))
        previous = len(self.connection.writes)
        self.worker.submit("set_inputs", first=101, second=0, limits=limits)
        error = self.event("error", "set_inputs")
        self.assertIn("ValueError", error.error)
        self.assertEqual(len(self.connection.writes), previous)
        self.assertFalse(self.connection.is_open)

    def test_invalid_limits_and_connection_settings_are_rejected(self):
        for args in ((2, 1, 0, 1), (-32769, 0, 0, 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ReferenceLimits(*args)
        for kwargs in ({"device_id": 0}, {"profile": "unknown"}, {"timeout": float("nan")}, {"timeout": 0.01}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ConnectionSettings("SIMULATED", **kwargs)

    def test_busy_worker_does_not_accumulate_normal_commands(self):
        self.connect()
        entered, release = threading.Event(), threading.Event()
        original = commands.qb_cmd_get_measurements

        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Test did not release serial operation")
            return original(*args, **kwargs)

        with mock.patch.object(commands, "qb_cmd_get_measurements", side_effect=blocked):
            try:
                self.assertTrue(self.worker.submit("snapshot"))
                self.assertTrue(entered.wait(2))
                self.assertFalse(self.worker.submit("activate", mask=3))
                self.assertFalse(self.worker.submit("snapshot"))
            finally:
                release.set()
            self.event(action="snapshot")
        self.assertNotIn(128, [packet[4] for packet in self.connection.writes])

    def test_deactivation_preempts_remaining_reads_and_runs_before_shutdown(self):
        self.connect()
        entered, release = threading.Event(), threading.Event()
        original = commands.qb_cmd_get_measurements

        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Test did not release serial operation")
            return original(*args, **kwargs)

        with mock.patch.object(commands, "qb_cmd_get_measurements", side_effect=blocked):
            try:
                self.worker.submit("snapshot")
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.worker.submit("deactivate"))
                self.worker.shutdown()
            finally:
                release.set()
            self.event(action="deactivate")
        self.worker.join(timeout=2)
        self.assertEqual([packet[4] for packet in self.connection.writes], [0, 132, 128])
        self.assertEqual(self.connection.writes[-1][5], 0)
        self.assertFalse(self.connection.is_open)

    def test_shutdown_discards_pending_activation(self):
        worker = SerialWorker()
        self.assertTrue(worker.submit("activate", mask=3))
        worker.shutdown()
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.factory.assert_not_called()
        self.assertFalse(self.connection.writes)

    def test_failed_ping_closes_port_and_publishes_error(self):
        self.connection.on_write = lambda packet: b""
        self.worker.submit("connect", settings=ConnectionSettings("SIMULATED", timeout=0.05))
        event = self.event("error", "connect")
        self.assertIn("QbTimeoutError", event.error)
        self.assertFalse(self.connection.is_open)

    def test_firmware_profile_gates_motor_command(self):
        self.connect()
        self.worker.submit("motor_commands")
        event = self.event("error", "motor_commands")
        self.assertIn("QbUnsupportedCommandError", event.error)
        self.assertEqual([packet[4] for packet in self.connection.writes], [0])


if __name__ == "__main__":
    unittest.main()
