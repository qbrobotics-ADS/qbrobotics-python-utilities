"""Widget integration tests. Skipped when Tk or a graphical display is unavailable."""

import logging
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    import tkinter as tk
    import qbrobotics_gui as gui
except ImportError:
    tk = None

import qbrobotics_serial_utils as transport
from test_gui_worker import simulated_device
from test_protocol import FakeSerial


@unittest.skipIf(tk is None, "Tkinter is unavailable")
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Graphical display unavailable: {exc}")
        self.root.withdraw()
        self.connection = FakeSerial(on_write=simulated_device)
        self.serial_patch = mock.patch.object(transport.serial, "Serial", return_value=self.connection)
        self.port_patch = mock.patch.object(transport, "list_com_ports", return_value=["SIMULATED"])
        self.serial_patch.start()
        self.port_patch.start()
        self.addCleanup(self.cleanup)
        self.application = gui.QbApplication(self.root)
        self.pump(lambda: not self.application.worker.busy and self.application._port.get() == "SIMULATED")

    def cleanup(self):
        if hasattr(self, "application"):
            self.application.close()
            self.application.worker.join(timeout=2)
            self.assertFalse(self.application.worker.is_alive())
            self.application._drain_events()
        else:
            self.root.destroy()
        self.port_patch.stop()
        self.serial_patch.stop()

    def pump(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.005)
        self.fail("GUI did not reach the expected state")

    def connect(self):
        self.application.connect()
        self.pump(lambda: self.application._connected)

    def test_startup_disables_device_commands_and_does_not_open_ports(self):
        self.assertTrue(self.application.activate_button.instate(["disabled"]))
        self.assertTrue(self.application.send_button.instate(["disabled"]))
        self.assertFalse(self.connection.writes)

    def test_connection_snapshot_and_reference_validation(self):
        app = self.application
        self.connect()
        self.assertEqual(app._serial_number.get(), str(0x12345678))
        self.assertTrue(app.port_box.instate(["disabled"]))
        self.assertTrue(app.motor_commands_button.instate(["disabled"]))
        app.read_button.invoke()
        self.pump(lambda: len(app.measurements.get_children()) == 3)
        self.assertEqual(app.currents.item(app.currents.get_children()[0], "values"), ("Motor 1", "-512"))
        self.assertEqual(app._activation.get(), "Deactivated")
        self.assertTrue(app.send_button.instate(["disabled"]))
        for variable, value in zip(app._limit_vars, ("-100", "100", "0", "200")):
            variable.set(value)
        app._reference_1.set("-100")
        app._reference_2.set("200")
        self.assertFalse(app.send_button.instate(["disabled"]))
        app.send_button.invoke()
        self.pump(lambda: "References: command sent" in app._status.get())
        self.assertEqual(self.connection.writes[-1][4:-1], b"\x82\xff\x9c\x00\xc8")
        app._reference_1.set("101")
        self.assertTrue(app.send_button.instate(["disabled"]))

    def test_polling_stops_on_error_and_clears_stale_values(self):
        app = self.application
        self.connect()
        app.toggle_polling()
        self.pump(lambda: len(app.measurements.get_children()) == 3)
        self.connection.on_write = lambda packet: b""
        self.pump(lambda: not app._connected, timeout=3)
        self.assertFalse(app._polling.get())
        self.assertFalse(self.connection.is_open)
        self.assertFalse(app.measurements.get_children())
        self.assertTrue(app.activate_button.instate(["disabled"]))

    def test_log_export_writes_visible_diagnostics(self):
        app = self.application
        app._append_log("Synthetic diagnostic entry")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "diagnostics.log"
            with mock.patch.object(gui.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export_log()
            self.assertIn("Synthetic diagnostic entry", target.read_text(encoding="utf-8"))

    def test_invalid_settings_do_not_open_port(self):
        app = self.application
        app._device_id.set("0")
        with mock.patch.object(gui.messagebox, "showerror") as shown:
            app.connect()
        shown.assert_called_once()
        self.assertFalse(self.connection.writes)


if __name__ == "__main__":
    unittest.main()
