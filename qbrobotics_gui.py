"""Desktop interface for qbrobotics serial devices. Run with python -m qbrobotics_gui."""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
from importlib.resources import as_file, files
import logging
from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from qbrobotics_gui_worker import ConnectionSettings, PROFILES, ReferenceLimits, SerialWorker
from qbrobotics_serial_utils import Packet

_ACTION_LABELS = {
    "ports": "refreshing ports", "connect": "connecting", "ping": "ping",
    "snapshot": "reading values", "info": "reading firmware information",
    "motor_commands": "reading motor commands", "activate": "activating motors",
    "deactivate": "deactivating motors", "set_inputs": "sending references",
}


class _LogHandler(logging.Handler):
    """Deliver transport logs without calling Tk from the serial thread."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: queue.Queue[str] = queue.Queue(maxsize=1000)
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record) -> None:
        text = self.format(record)
        try:
            self.messages.put_nowait(text)
        except queue.Full:
            # Keep serial I/O independent of UI speed; retain the newest diagnostics.
            try:
                self.messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self.messages.put_nowait(text)
            except queue.Full:
                pass


class QbApplication:
    """Tk owns widgets; SerialWorker owns the connection and every device command."""

    def __init__(self, root: tk.Tk, *, worker=None, initial_port: str = "") -> None:
        self.root = root
        self.worker = worker if worker is not None else SerialWorker()
        self._connected = False
        self._closing = False
        self._disconnecting = False
        self._deactivate_pending = False
        self._poll_timer = None
        self._event_timer = None
        self._settings = None
        self._port = tk.StringVar(root, initial_port)
        self._baudrate = tk.StringVar(root, "2000000")
        self._device_id = tk.StringVar(root, "1")
        self._profile = tk.StringVar(root, "research")
        self._timeout = tk.StringVar(root, "0.5")
        self._status = tk.StringVar(root, "Select a port, device ID and firmware profile.")
        self._serial_number = tk.StringVar(root, "—")
        self._activation = tk.StringVar(root, "—")
        self._inputs = tk.StringVar(root, "—")
        self._updated = tk.StringVar(root, "No readings yet")
        self._polling = tk.BooleanVar(root, False)
        self._interval = tk.StringVar(root, "500")
        self._mask = tk.StringVar(root, "Both motors (3)")
        self._reference_1 = tk.StringVar(root, "0")
        self._reference_2 = tk.StringVar(root, "0")
        self._limit_vars = [tk.StringVar(root, "") for _ in range(4)]
        self._ack = tk.BooleanVar(root, False)
        self._raw_logs = tk.BooleanVar(root, True)
        self._build()
        self._transport_logger = logging.getLogger("qbrobotics_serial_utils")
        self._previous_log_level = self._transport_logger.level
        self._previous_log_propagate = self._transport_logger.propagate
        self._log_handler = _LogHandler()
        self._transport_logger.addHandler(self._log_handler)
        self._transport_logger.setLevel(logging.DEBUG)
        self._transport_logger.propagate = False
        for variable in (*self._limit_vars, self._reference_1, self._reference_2, self._profile):
            variable.trace_add("write", lambda *_: self._sync_controls())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker.start()
        self.worker.submit("ports")
        self._append_log("Ready. Connecting requires a valid ping from the selected device.")
        self._sync_controls()
        self._event_timer = self.root.after(50, self._drain_events)

    def _build(self) -> None:
        root = self.root
        root.title("qbrobotics · Device Console")
        if root.tk.call("tk", "windowingsystem") == "win32":
            with as_file(files("qbrobotics_assets").joinpath("qb.ico")) as icon:
                root.iconbitmap(str(icon))
                root.iconbitmap(default=str(icon))
        width = min(1160, root.winfo_screenwidth() - 60)
        height = min(820, root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(980, 650)
        root.configure(background="#eef2f7")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f7")
        style.configure("TLabel", background="#eef2f7", foreground="#18324d", font=("Segoe UI", 10))
        style.configure("TButton", padding=(12, 7), font=("Segoe UI", 10))
        style.configure("TCheckbutton", background="#eef2f7", font=("Segoe UI", 10))
        style.configure("TLabelframe", background="#eef2f7", bordercolor="#cbd5e1")
        style.configure("TLabelframe.Label", background="#eef2f7", foreground="#18324d", font=("Segoe UI", 10, "bold"))
        style.configure("Header.TFrame", background="#15324f")
        style.configure("Title.TLabel", background="#15324f", foreground="white", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background="#15324f", foreground="#c6d8e9", font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#166a96", foreground="white")
        style.map("Accent.TButton", background=[("disabled", "#ccd5df"), ("active", "#12577b")], foreground=[("disabled", "#64748b")])
        style.configure("Stop.TButton", foreground="#a52a32")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 11), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=3)
        root.rowconfigure(3, weight=1)
        header = ttk.Frame(root, style="Header.TFrame", padding=(22, 12))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="qbrobotics", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="DEVICE CONSOLE  /  Connection · Monitoring · Control", style="Subtitle.TLabel").pack(side="left", padx=24)

        connection = ttk.LabelFrame(root, text=" Connection ", padding=12)
        connection.grid(row=1, column=0, sticky="ew", padx=18, pady=(12, 8))
        connection.columnconfigure(0, weight=1)
        labels = {0: "Serial port", 2: "Baudrate", 3: "ID", 4: "Firmware profile", 5: "Timeout (s)"}
        for column, label in labels.items():
            ttk.Label(connection, text=label).grid(row=0, column=column, sticky="w", padx=(0, 10), pady=(0, 5))
        self.port_box = ttk.Combobox(connection, textvariable=self._port, width=16)
        self.port_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.refresh_button = ttk.Button(connection, text="Refresh", command=lambda: self._request("ports"))
        self.refresh_button.grid(row=1, column=1, padx=(0, 10))
        baud = ttk.Entry(connection, textvariable=self._baudrate, width=10)
        baud.grid(row=1, column=2, padx=(0, 10))
        device_id = ttk.Spinbox(connection, from_=1, to=255, textvariable=self._device_id, width=4)
        device_id.grid(row=1, column=3, padx=(0, 10))
        profile = ttk.Combobox(connection, textvariable=self._profile, values=tuple(PROFILES), state="readonly", width=12)
        profile.grid(row=1, column=4, padx=(0, 10))
        timeout = ttk.Spinbox(connection, from_=0.05, to=10, increment=0.05, textvariable=self._timeout, width=5)
        timeout.grid(row=1, column=5, padx=(0, 10))
        self.connect_button = ttk.Button(connection, text="Connect", style="Accent.TButton", command=self.connect)
        self.connect_button.grid(row=1, column=6, padx=(0, 8))
        self.disconnect_button = ttk.Button(connection, text="Disconnect", command=self.disconnect)
        self.disconnect_button.grid(row=1, column=7)
        self._connection_fields = (self.port_box, baud, device_id, profile, timeout)

        self.tabs = ttk.Notebook(root)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=18, pady=4)
        monitor = ttk.Frame(self.tabs, padding=14)
        manual = ttk.Frame(self.tabs, padding=14)
        info = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(monitor, text="  Monitoring  ")
        self.tabs.add(manual, text="  Manual control  ")
        self.tabs.add(info, text="  Firmware information  ")
        self._build_monitor(monitor)
        self._build_manual(manual)
        info.rowconfigure(1, weight=1)
        info.columnconfigure(0, weight=1)
        self.info_button = ttk.Button(info, text="Read information", command=lambda: self._request("info"))
        self.info_button.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.info_text = self._text_with_scrollbar(info, row=1, height=8)

        diagnostics = ttk.LabelFrame(root, text=" Diagnostics · latest 3000 lines ", padding=(10, 6))
        diagnostics.grid(row=3, column=0, sticky="nsew", padx=18, pady=(8, 5))
        diagnostics.columnconfigure(0, weight=1)
        diagnostics.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(diagnostics)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Checkbutton(toolbar, text="TX/RX packets", variable=self._raw_logs).pack(side="left")
        ttk.Button(toolbar, text="Export log…", command=self.export_log).pack(side="right")
        self.log_text = self._text_with_scrollbar(diagnostics, row=1, height=6)
        self.log_text.tag_configure("error", foreground="#a52a32")
        ttk.Label(root, textvariable=self._status, style="Status.TLabel", wraplength=1050, padding=(20, 8)).grid(row=4, column=0, sticky="ew")

    def _text_with_scrollbar(self, parent, *, row: int, height: int):
        text = tk.Text(parent, height=height, wrap="word", state="disabled", font=("Consolas", 10), background="white", foreground="#24364a", relief="flat", padx=8, pady=6)
        text.grid(row=row, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, command=text.yview)
        scrollbar.grid(row=row, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        return text

    def _build_monitor(self, monitor) -> None:
        monitor.columnconfigure(0, weight=1)
        monitor.columnconfigure(1, weight=1)
        monitor.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(monitor)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.ping_button = ttk.Button(toolbar, text="Ping", command=lambda: self._request("ping"))
        self.ping_button.pack(side="left", padx=(0, 8))
        self.read_button = ttk.Button(toolbar, text="Read values", command=lambda: self._request("snapshot"))
        self.read_button.pack(side="left", padx=(0, 8))
        self.poll_button = ttk.Button(toolbar, text="Start monitoring", command=self.toggle_polling)
        self.poll_button.pack(side="left", padx=(0, 14))
        ttk.Label(toolbar, text="Pause between readings (ms)").pack(side="left")
        self.interval_box = ttk.Spinbox(toolbar, from_=100, to=10000, increment=100, textvariable=self._interval, width=6)
        self.interval_box.pack(side="left", padx=8)
        ttk.Label(monitor, textvariable=self._updated).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.measurements = self._value_table(monitor, 0, "Encoder", "Position (ticks)")
        self.currents = self._value_table(monitor, 1, "Motor", "Current (mA)")
        footer = ttk.Frame(monitor)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(footer, text="Serial number:").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self._serial_number, style="Status.TLabel").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(footer, text="Motor status:").grid(row=0, column=2, sticky="w", padx=(28, 0))
        ttk.Label(footer, textvariable=self._activation, style="Status.TLabel").grid(row=0, column=3, sticky="w", padx=8)
        ttk.Label(footer, text="Read references:").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Label(footer, textvariable=self._inputs).grid(row=1, column=1, columnspan=3, sticky="w", padx=8, pady=(7, 0))

    def _value_table(self, parent, column: int, first: str, second: str):
        table = ttk.Treeview(parent, columns=("name", "value"), show="headings", height=4, selectmode="none")
        table.heading("name", text=first)
        table.heading("value", text=second)
        table.column("name", width=130, stretch=True)
        table.column("value", width=170, stretch=True, anchor="e")
        table.grid(row=2, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        return table

    def _build_manual(self, manual) -> None:
        manual.columnconfigure(0, weight=1)
        manual.columnconfigure(1, weight=2)
        motors = ttk.LabelFrame(manual, text=" Motors ", padding=14)
        motors.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(motors, text="Motors to activate").pack(anchor="w")
        self.mask_box = ttk.Combobox(motors, textvariable=self._mask, values=("Both motors (3)", "Motor 1 (1)", "Motor 2 (2)"), state="readonly", width=20)
        self.mask_box.pack(anchor="w", pady=8)
        self.activate_button = ttk.Button(motors, text="Activate motors", command=self.activate)
        self.activate_button.pack(fill="x", pady=(8, 6))
        self.deactivate_button = ttk.Button(motors, text="Deactivate motors", style="Stop.TButton", command=lambda: self._request("deactivate"))
        self.deactivate_button.pack(fill="x")
        ttk.Label(motors, text="Disconnecting closes the port.\nUse Deactivate motors to disable the motors.", wraplength=280).pack(anchor="w", pady=(14, 0))
        references = ttk.LabelFrame(manual, text=" References · units depend on the control mode ", padding=14)
        references.grid(row=0, column=1, sticky="nsew")
        for column in (1, 2, 3):
            references.columnconfigure(column, weight=1)
        for column, name in enumerate(("", "Minimum", "Maximum", "Reference")):
            ttk.Label(references, text=name).grid(row=0, column=column, sticky="w", padx=5, pady=(0, 8))
        self._reference_fields = []
        for row, reference in enumerate((self._reference_1, self._reference_2), 1):
            ttk.Label(references, text=f"Input {row}").grid(row=row, column=0, sticky="w", padx=5)
            variables = (self._limit_vars[(row - 1) * 2], self._limit_vars[(row - 1) * 2 + 1], reference)
            for column, variable in enumerate(variables, 1):
                entry = ttk.Entry(references, textvariable=variable, width=11)
                entry.grid(row=row, column=column, padx=5, pady=5, sticky="ew")
                self._reference_fields.append(entry)
        ttk.Label(references, text="Enter limits compatible with the device and control mode.\nReferences must be signed 16-bit integers.", wraplength=480).grid(row=3, column=0, columnspan=4, sticky="w", pady=10)
        self.ack_box = ttk.Checkbutton(references, text="Request ACK (if supported by the profile)", variable=self._ack)
        self.ack_box.grid(row=4, column=0, columnspan=4, sticky="w")
        self.send_button = ttk.Button(references, text="Send references", style="Accent.TButton", command=self.send_inputs)
        self.send_button.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        self.motor_commands_button = ttk.Button(manual, text="Read motor commands", command=lambda: self._request("motor_commands"))
        self.motor_commands_button.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _reference_values(self):
        try:
            limits = ReferenceLimits(*(int(variable.get()) for variable in self._limit_vars))
            first, second = int(self._reference_1.get()), int(self._reference_2.get())
        except ValueError as exc:
            raise ValueError("Enter valid integer limits and references for both inputs.") from exc
        limits.validate(first, second)
        return first, second, limits

    @staticmethod
    def _enable(widget, enabled: bool, *, readonly: bool = False) -> None:
        widget.configure(state=("readonly" if readonly else "normal") if enabled else "disabled")

    def _sync_controls(self) -> None:
        if self._closing:
            available = editable = False
        else:
            available = self._connected and not self._disconnecting and not self.worker.busy
            editable = not self._connected and not self._disconnecting and not self.worker.busy
        for widget in self._connection_fields:
            self._enable(widget, editable, readonly=widget is self._connection_fields[3])
        self._enable(self.connect_button, editable)
        self._enable(self.refresh_button, editable)
        self._enable(self.disconnect_button, self._connected and not self._closing and not self._disconnecting)
        for widget in (self.ping_button, self.read_button, self.info_button, self.activate_button):
            self._enable(widget, available)
        self._enable(self.mask_box, available, readonly=True)
        self._enable(self.deactivate_button, self._connected and not self._closing and not self._disconnecting and not self._deactivate_pending)
        self._enable(self.poll_button, self._connected and not self._closing and not self._disconnecting)
        self._enable(self.interval_box, not self._polling.get() and not self._closing)
        profile = PROFILES.get(self._profile.get())
        ack_supported = profile is not None and profile.set_inputs_ack is not None
        if not ack_supported:
            self._ack.set(False)
        self._enable(self.ack_box, available and ack_supported)
        self._enable(self.motor_commands_button, available and profile is not None and profile.get_motor_commands is not None)
        try:
            self._reference_values()
            valid_references = True
        except (ValueError, TypeError):
            valid_references = False
        self._enable(self.send_button, available and valid_references)
        for widget in self._reference_fields:
            self._enable(widget, not self._closing and not self._disconnecting and not self.worker.busy)

    def _request(self, action: str, **arguments) -> bool:
        if self._closing or self._disconnecting:
            return False
        if self.worker.submit(action, **arguments):
            if action == "deactivate":
                self._deactivate_pending = True
            self._status.set(f"In progress: {_ACTION_LABELS[action]}…")
            self._sync_controls()
            return True
        return False

    def connect(self) -> None:
        try:
            settings = ConnectionSettings(
                self._port.get().strip(), int(self._device_id.get()), int(self._baudrate.get()),
                float(self._timeout.get()), self._profile.get(),
            )
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return
        self._request("connect", settings=settings)

    def disconnect(self) -> None:
        self.stop_polling()
        self._disconnecting = True
        self._status.set("Closing the connection after the current operation…")
        self.worker.disconnect()
        self._sync_controls()

    def activate(self) -> None:
        masks = {"Both motors (3)": 3, "Motor 1 (1)": 1, "Motor 2 (2)": 2}
        self._request("activate", mask=masks[self._mask.get()])

    def send_inputs(self) -> None:
        try:
            first, second, limits = self._reference_values()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid references", str(exc), parent=self.root)
            return
        self._request("set_inputs", first=first, second=second, limits=limits, ack=self._ack.get())

    def toggle_polling(self) -> None:
        if self._polling.get():
            self.stop_polling()
            return
        try:
            interval = int(self._interval.get())
            if not 100 <= interval <= 10000:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid interval", "Enter a pause between 100 and 10000 ms.", parent=self.root)
            return
        self._polling.set(True)
        self.poll_button.configure(text="Stop monitoring")
        self._sync_controls()
        self._poll_tick()

    def stop_polling(self) -> None:
        self._polling.set(False)
        self.poll_button.configure(text="Start monitoring")
        if self._poll_timer is not None:
            self.root.after_cancel(self._poll_timer)
            self._poll_timer = None
        self._sync_controls()

    def _poll_tick(self) -> None:
        self._poll_timer = None
        if not self._polling.get() or not self._connected or self._closing or self._disconnecting:
            return
        if not self._request("snapshot"):
            self._poll_timer = self.root.after(100, self._poll_tick)

    def _append_log(self, text: str, *, error: bool = False, timestamp: bool = True) -> None:
        if timestamp:
            text = datetime.now().strftime("%H:%M:%S") + "  " + text
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", "error" if error else "")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 3000:
            self.log_text.delete("1.0", f"{lines - 3000 + 1}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def export_log(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self.root, title="Export diagnostic log", defaultextension=".log",
            initialfile=datetime.now().strftime("qbrobotics-%Y%m%d-%H%M%S.log"),
            filetypes=[("Log", "*.log"), ("Text", "*.txt")],
        )
        if filename:
            try:
                Path(filename).write_text(self.log_text.get("1.0", "end-1c"), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc), parent=self.root)

    def _clear_readings(self) -> None:
        for table in (self.measurements, self.currents):
            table.delete(*table.get_children())
        self._serial_number.set("—")
        self._activation.set("—")
        self._inputs.set("—")
        self._updated.set("No valid readings in the current session")
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.configure(state="disabled")

    def _handle_event(self, event) -> None:
        if event.kind == "error":
            self.stop_polling()
            self._connected = self._disconnecting = self._deactivate_pending = False
            self._settings = None
            self._clear_readings()
            self._status.set("Error: " + event.error + " · Reconnect before retrying.")
            self._append_log(event.action + ": " + event.error, error=True)
        elif event.kind == "disconnected":
            self._connected = self._disconnecting = self._deactivate_pending = False
            self._settings = None
            self._clear_readings()
            self._status.set("Disconnected. Disconnecting does not send a motor deactivation command.")
            self._append_log("Serial port closed.")
        elif event.kind == "result":
            action, value = event.action, event.value
            if action == "ports":
                self.port_box.configure(values=value)
                if not self._port.get() and value:
                    self._port.set(value[0])
                self._status.set("Select a port and ID, then click Connect." if value else "No ports detected. You can enter a port name manually.")
            elif action == "connect":
                self._connected = True
                self._settings = value["settings"]
                self._clear_readings()
                self._serial_number.set(str(value["packet"].serial_number) if value["packet"].serial_number is not None else "Not available (legacy)")
                self._status.set(f"Connected · {self._settings.port} · ID {self._settings.device_id} · {self._settings.profile}")
                self._append_log(self._status.get())
            elif action == "snapshot":
                for table, key, name in ((self.measurements, "measurements", "Encoder"), (self.currents, "currents", "Motor")):
                    table.delete(*table.get_children())
                    for index, number in enumerate(value[key], 1):
                        table.insert("", "end", values=(f"{name} {index}", number))
                self._activation.set({0: "Deactivated", 1: "Motor 1 active", 2: "Motor 2 active", 3: "Both motors active"}[value["activation"]])
                self._inputs.set(str(value["inputs"]))
                self._updated.set("Last reading: " + datetime.now().strftime("%H:%M:%S"))
                self._status.set("Values updated.")
                if self._polling.get() and self._poll_timer is None:
                    self._poll_timer = self.root.after(int(self._interval.get()), self._poll_tick)
            elif action == "info":
                self.info_text.configure(state="normal")
                self.info_text.delete("1.0", "end")
                self.info_text.insert("end", value)
                self.info_text.configure(state="disabled")
                self.tabs.select(2)
                self._status.set("Firmware information received.")
            elif action == "ping":
                self._serial_number.set(str(value.serial_number) if value.serial_number is not None else "Not available (legacy)")
                self._status.set("Ping successful.")
                self._append_log("Ping successful.")
            elif action in ("activate", "deactivate", "set_inputs"):
                if action == "deactivate":
                    self._deactivate_pending = False
                if action in ("activate", "deactivate"):
                    self._activation.set("Read values to verify")
                else:
                    self._inputs.set("Read values to verify")
                acknowledged = isinstance(value, Packet)
                label = {"activate": "Activation", "deactivate": "Deactivation", "set_inputs": "References"}[action]
                text = f"{label}: ACK received." if acknowledged else f"{label}: command sent; read values to verify the state."
                self._status.set(text)
                self._append_log(text)
            elif action == "motor_commands":
                self._status.set(f"Motor commands: {value}")
                self._append_log(self._status.get())

    def _drain_events(self) -> None:
        if self._event_timer is not None:
            self.root.after_cancel(self._event_timer)
            self._event_timer = None
        for _ in range(200):
            try:
                event = self.worker.events.get_nowait()
            except queue.Empty:
                break
            if not self._closing:
                self._handle_event(event)
        for _ in range(200):
            try:
                text = self._log_handler.messages.get_nowait()
            except queue.Empty:
                break
            if self._raw_logs.get():
                self._append_log(text, timestamp=False)
        if self._closing and not self.worker.is_alive():
            self._transport_logger.removeHandler(self._log_handler)
            self._transport_logger.setLevel(self._previous_log_level)
            self._transport_logger.propagate = self._previous_log_propagate
            self._log_handler.close()
            self.root.destroy()
            return
        self._sync_controls()
        self._event_timer = self.root.after(50, self._drain_events)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.stop_polling()
        self._status.set("Closing: waiting for the current request to finish…")
        self.worker.shutdown()
        self._sync_controls()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="", help="Preselect a port without connecting automatically")
    args = parser.parse_args()
    if sys.platform == "win32":
        # Give the taskbar a dedicated application identity instead of grouping with Python.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("qbrobotics.DeviceConsole")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"GUI unavailable: {exc}. Check your installation with python -m tkinter.", file=sys.stderr)
        return 1
    QbApplication(root, initial_port=args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
