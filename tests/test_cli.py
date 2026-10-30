"""The command-line entry point must close connections on every exit path."""

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

import qbrobotics_cli as cli
from qbrobotics_serial_utils import QbConnectionError, QbTimeoutError
from test_protocol import FakeSerial, reply


class CliTests(unittest.TestCase):
    def test_importing_compatibility_script_never_opens_or_prompts(self):
        script = Path(__file__).resolve().parents[1] / "qbrobotics-modules-test.py"
        spec = importlib.util.spec_from_file_location("qb_example", script)
        module = importlib.util.module_from_spec(spec)
        with mock.patch("serial.Serial") as opened, mock.patch("builtins.input") as prompted:
            spec.loader.exec_module(module)
        opened.assert_not_called()
        prompted.assert_not_called()

    def test_success_closes_connection_and_prints_result(self):
        connection = FakeSerial(reply(0, b"\0\0\0A"))
        output = io.StringIO()
        with mock.patch.object(cli, "open_serial_connection", return_value=connection), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["--port", "SIMULATED"]), 0)
        self.assertIn("serial number: 65", output.getvalue())
        self.assertFalse(connection.is_open)

    def test_timeout_and_interrupt_close_connection(self):
        for error, code in ((QbTimeoutError("no reply"), 1), (KeyboardInterrupt(), 130)):
            connection = FakeSerial()
            with self.subTest(error=error), mock.patch.object(cli, "open_serial_connection", return_value=connection), mock.patch.object(cli, "qb_cmd_ping", side_effect=error), mock.patch.object(cli.logging, "error"):
                self.assertEqual(cli.main(["--port", "SIMULATED"]), code)
                self.assertFalse(connection.is_open)

    def test_close_failure_reports_nonzero_exit_status(self):
        connection = FakeSerial(reply(0))
        with mock.patch.object(cli, "open_serial_connection", return_value=connection), mock.patch.object(cli, "close_serial_connection", side_effect=QbConnectionError("close failed")), mock.patch.object(cli.logging, "error"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--port", "SIMULATED"]), 1)

    def test_help_invalid_arguments_and_cancel_do_not_open_ports(self):
        with mock.patch.object(cli, "open_serial_connection") as opened:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_info:
                cli.main(["--help"])
            self.assertEqual(exit_info.exception.code, 0)
            for args in (["--id", "0"], ["--timeout", "nan"], ["--timeout", "-1"]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_info:
                    cli.main(args)
                self.assertEqual(exit_info.exception.code, 2)
            with mock.patch.object(cli, "choose_com_port", return_value=None):
                self.assertEqual(cli.main([]), 0)
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
