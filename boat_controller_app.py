"""Native Windows companion for Bluetrum based boAt earbuds."""

import html
import sys
from datetime import datetime

from PyQt6.QtCore import Qt, QSettings, QTimer, QSize
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFrame, QGridLayout, QDialog, QTextEdit,
    QScrollArea, QListWidget, QListWidgetItem, QCheckBox, QSizePolicy,
)

from audio_ringer import EarbudsAudioRinger
from ble_worker import BleWorker
from protocol import EQ_PRESETS, KEY_FUNCTIONS, KEY_TYPES
from ui_components import THEME, ACCENT, MUTED, BatteryReadout, ModeControl, icon, label


class MainWindow(QMainWindow):
    def __init__(self, worker=None, settings=None, audio_ringer=None, startup_scan=True):
        super().__init__()
        self.setWindowTitle("boAt Hearables")
        self.setWindowIcon(icon("earbuds", ACCENT, 32))
        self.setFont(QFont("Segoe UI", 10))
        self.resize(680, 590)
        self.setMinimumSize(560, 460)
        self.setStyleSheet(THEME)
        self.settings = settings if settings is not None else QSettings("JaydeepPatil", "boAt Hearables")
        self.worker = worker if worker is not None else BleWorker(self)
        self.audio_ringer = audio_ringer if audio_ringer is not None else EarbudsAudioRinger(self)
        self._startup_scan = startup_scan
        self._connected = False
        self._busy = False
        self._scanning = False
        self._closing = False
        self._ring_busy = False
        self._devices = {}
        self._preferred_address = self.settings.value("last_device", "")
        self._user_selected = False
        self._selected_address = None
        self._pending_operations = set()
        self._touch_dialog = None
        self.init_ui()
        self._connect_signals()
        self.worker.set_auto_reconnect(self.reconnect_check.isChecked())
        self._update_controls()
        self.refresh_audio_outputs()
        self._shortcut_scan = QShortcut(QKeySequence("Ctrl+R"), self)
        self._shortcut_scan.activated.connect(lambda: self.start_scan() if self.scan_btn.isEnabled() else None)
        self._device_scan_shortcut = QShortcut(QKeySequence("Ctrl+R"), self.device_dialog)
        self._device_scan_shortcut.activated.connect(lambda: self.start_scan() if self.scan_btn.isEnabled() else None)
        self._shortcut_stop = QShortcut(QKeySequence("Esc"), self)
        self._shortcut_stop.activated.connect(self.stop_ring)
        self.worker.start()

    def _connect_signals(self):
        self.worker.ready.connect(self._on_worker_ready)
        self.worker.device_discovered.connect(self.on_device_discovered)
        self.worker.scan_finished.connect(self.on_scan_finished)
        self.worker.status_changed.connect(self.on_status_changed)
        self.worker.connection_changed.connect(self.on_connection_changed)
        self.worker.battery_updated.connect(self.on_battery_updated)
        self.worker.beast_mode_updated.connect(self.card_beast.set_state)
        self.worker.spatial_audio_updated.connect(self.card_spatial.set_state)
        self.worker.command_result.connect(self.on_command_result)
        self.worker.log_message.connect(self.on_log_message)
        self.audio_ringer.playback_started.connect(self.on_ring_started)
        self.audio_ringer.playback_stopped.connect(self.on_ring_stopped)
        self.audio_ringer.error_occurred.connect(self._audio_error)

    def _on_worker_ready(self):
        if self._startup_scan and not self._closing:
            QTimer.singleShot(200, self.start_scan)

    @staticmethod
    def _button(text, callback, style=None, icon_name=None):
        button = QPushButton(text)
        if style:
            button.setObjectName(style)
        if icon_name:
            button.setIcon(icon(icon_name))
            button.setIconSize(QSize(18, 18))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _divider():
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        return divider

    @staticmethod
    def _set_button_style(button, name):
        if button.objectName() != name:
            button.setObjectName(name)
            button.style().unpolish(button)
            button.style().polish(button)

    def init_ui(self):
        root = QWidget()
        root.setObjectName("main")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        device = QVBoxLayout()
        device.setSpacing(5)
        self.device_title = label("No device connected", wrap=True)
        self.device_title.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.device_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.connection_status = label("Disconnected", "muted")
        self.connection_status.setStyleSheet("font-size: 12px; color: #A0A2AA;")
        device.addWidget(self.device_title)
        device.addWidget(self.connection_status)
        header.addLayout(device, 1)
        self.devices_btn = self._button("Connect earbuds", self.open_devices, "primary")
        header.addWidget(self.devices_btn)
        outer.addLayout(header)
        outer.addWidget(self._divider())

        self.feedback = label("", wrap=True)
        self.feedback.hide()
        outer.addWidget(self.feedback)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls = QWidget()
        content = QVBoxLayout(controls)
        content.setContentsMargins(0, 0, 8, 4)
        content.setSpacing(14)
        battery_heading = QHBoxLayout()
        battery_heading.addWidget(label("BATTERY", "sectionTitle"))
        battery_heading.addStretch()
        self.battery_status = label("", "muted")
        self.battery_status.setStyleSheet("font-size: 11px;")
        battery_heading.addWidget(self.battery_status)
        self.refresh_btn = self._button("Refresh", self.refresh_battery, "quiet", "refresh")
        self.refresh_btn.setStyleSheet("padding: 4px 7px; font-size: 11px;")
        battery_heading.addWidget(self.refresh_btn)
        content.addLayout(battery_heading)
        batteries = QHBoxLayout()
        batteries.setSpacing(24)
        self.card_left = BatteryReadout("Left")
        self.card_right = BatteryReadout("Right")
        self.card_case = BatteryReadout("Case")
        for card in (self.card_left, self.card_right, self.card_case):
            batteries.addWidget(card, 1)
        content.addLayout(batteries)
        content.addSpacing(2)
        content.addWidget(self._divider())
        content.addWidget(label("SOUND", "sectionTitle"))
        self.card_beast = ModeControl("BEAST mode", "Gaming / low latency")
        self.card_spatial = ModeControl("Spatial audio", "3D sound")
        self.card_beast.toggled.connect(self.worker.set_beast_mode)
        self.card_spatial.toggled.connect(self.worker.set_spatial_audio)
        self.card_beast.confirmation_failed.connect(self._show_error)
        self.card_spatial.confirmation_failed.connect(self._show_error)
        content.addWidget(self.card_beast)
        content.addWidget(self.card_spatial)
        eq = QHBoxLayout()
        eq.setSpacing(10)
        eq.addWidget(label("Equalizer"), 1)
        self.eq_combo = QComboBox()
        self.eq_combo.setAccessibleName("Sound profile")
        self.eq_combo.addItem("Choose a profile", None)
        for name in EQ_PRESETS:
            self.eq_combo.addItem(name, name)
        self.eq_combo.setMinimumWidth(175)
        self.eq_combo.currentIndexChanged.connect(self._update_controls)
        eq.addWidget(self.eq_combo)
        self.eq_apply_btn = self._button("Apply", self.apply_eq)
        eq.addWidget(self.eq_apply_btn)
        content.addLayout(eq)
        content.addStretch()
        self.scroll.setWidget(controls)
        outer.addWidget(self.scroll, 1)
        outer.addWidget(self._divider())
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.finder_btn = self._button("Find earbuds", self.open_finder, "quiet")
        self.remap_btn = self._button("Touch controls", self.open_touch_remapper, "quiet")
        self.settings_btn = self._button("Settings", self.open_settings, "quiet")
        tools.addWidget(self.finder_btn)
        tools.addWidget(self.remap_btn)
        tools.addStretch()
        tools.addWidget(self.settings_btn)
        outer.addLayout(tools)

        self.device_dialog = QDialog(self)
        self.device_dialog.setWindowTitle("Bluetooth devices")
        self.device_dialog.resize(500, 410)
        discovery = QVBoxLayout(self.device_dialog)
        discovery.setContentsMargins(20, 18, 20, 18)
        discovery.setSpacing(12)
        self.discovery_summary = label("Nearby devices", "sectionTitle")
        discovery.addWidget(self.discovery_summary)
        self.device_list = QListWidget()
        self.device_list.setAccessibleName("Nearby Bluetooth devices")
        self.device_list.setMinimumHeight(160)
        self.device_list.currentItemChanged.connect(self._selection_changed)
        discovery.addWidget(self.device_list, 1)
        self.empty_state = label("Open the case and scan for earbuds.", "muted", True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setMinimumHeight(160)
        discovery.addWidget(self.empty_state, 1)
        self.device_list.hide()
        self.show_all_check = QCheckBox("Show other Bluetooth LE devices")
        self.show_all_check.setToolTip("Include devices without a boAt name or Bluetrum advertising hint.")
        self.show_all_check.toggled.connect(self._filter_devices)
        discovery.addWidget(self.show_all_check)
        self.connection_message = label("Select your earbuds to connect.", "muted", True)
        discovery.addWidget(self.connection_message)
        device_actions = QHBoxLayout()
        self.scan_btn = self._button("Scan", self.start_scan, "quiet", "refresh")
        self.scan_btn.setToolTip("Scan again (Ctrl+R)")
        self.connect_btn = self._button("Connect", self.toggle_connection, "primary")
        device_actions.addWidget(self.scan_btn)
        device_actions.addStretch()
        device_actions.addWidget(self.connect_btn)
        device_actions.addWidget(self._button("Close", self.device_dialog.reject))
        discovery.addLayout(device_actions)

        self.finder_dialog = QDialog(self)
        self.finder_dialog.setWindowTitle("Find earbuds")
        self.finder_dialog.resize(500, 245)
        self.finder_dialog.finished.connect(self.stop_ring)
        finder = QVBoxLayout(self.finder_dialog)
        finder.setContentsMargins(20, 18, 20, 18)
        finder.setSpacing(14)
        finder.addWidget(label("Remove earbuds before playing. Sound stops after 30 seconds.", "muted", True))
        self.finder_feedback = label("", wrap=True)
        self.finder_feedback.hide()
        finder.addWidget(self.finder_feedback)
        output = QHBoxLayout()
        self.output_combo = QComboBox()
        self.output_combo.setAccessibleName("Earbud audio output")
        self.output_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.output_combo.currentIndexChanged.connect(self._output_changed)
        output.addWidget(self.output_combo, 1)
        self.output_refresh_btn = self._button("", self.refresh_audio_outputs, "quiet", "refresh")
        self.output_refresh_btn.setAccessibleName("Refresh audio outputs")
        self.output_refresh_btn.setToolTip("Refresh Windows stereo audio outputs")
        output.addWidget(self.output_refresh_btn)
        finder.addLayout(output)
        play = QHBoxLayout()
        self.btn_ring_l = self._button("Left earbud", lambda: self.start_ring("left"))
        self.btn_ring_both = self._button("Both earbuds", lambda: self.start_ring("both"))
        self.btn_ring_r = self._button("Right earbud", lambda: self.start_ring("right"))
        for button in (self.btn_ring_l, self.btn_ring_both, self.btn_ring_r):
            play.addWidget(button, 1)
        finder.addLayout(play)
        ring_actions = QHBoxLayout()
        self.ring_status_lbl = label("Sound is off", "muted")
        ring_actions.addWidget(self.ring_status_lbl, 1)
        self.btn_ring_stop = self._button("Stop", self.stop_ring, "danger")
        self.btn_ring_stop.setToolTip("Stop the locator sound")
        ring_actions.addWidget(self.btn_ring_stop)
        ring_actions.addWidget(self._button("Close", self.finder_dialog.reject))
        finder.addLayout(ring_actions)

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Settings")
        self.settings_dialog.resize(490, 245)
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setContentsMargins(20, 18, 20, 18)
        settings_layout.setSpacing(18)
        self.reconnect_check = QCheckBox("Reconnect after connection loss")
        self.reconnect_check.setChecked(self.settings.value("auto_reconnect", True, type=bool))
        self.reconnect_check.toggled.connect(self._reconnect_changed)
        settings_layout.addWidget(self.reconnect_check)
        sleep = QHBoxLayout()
        sleep.setSpacing(10)
        sleep.addWidget(label("Idle power-off"), 1)
        self.sleep_combo = QComboBox()
        self.sleep_combo.setAccessibleName("Idle power-off timer")
        self.sleep_combo.addItem("Choose timer", None)
        for title, minutes in (("Off", 0), ("5 minutes", 5), ("10 minutes", 10), ("30 minutes", 30)):
            self.sleep_combo.addItem(title, minutes)
        self.sleep_combo.currentIndexChanged.connect(self._update_controls)
        sleep.addWidget(self.sleep_combo)
        self.sleep_apply_btn = self._button("Apply", self.apply_sleep)
        sleep.addWidget(self.sleep_apply_btn)
        settings_layout.addLayout(sleep)
        self.settings_feedback = label("", "muted", True)
        self.settings_feedback.hide()
        settings_layout.addWidget(self.settings_feedback)
        settings_layout.addWidget(self._divider())
        setting_actions = QHBoxLayout()
        setting_actions.addWidget(self._button("Connection help", self.open_connection_help, "quiet"))
        setting_actions.addWidget(self._button("Diagnostics", self.open_diagnostics, "quiet"))
        setting_actions.addStretch()
        setting_actions.addWidget(self._button("Close", self.settings_dialog.reject))
        settings_layout.addLayout(setting_actions)

        self.diagnostics = QDialog(self)
        self.diagnostics.setWindowTitle("Connection diagnostics")
        self.diagnostics.resize(660, 400)
        diagnostic_layout = QVBoxLayout(self.diagnostics)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.document().setMaximumBlockCount(500)
        diagnostic_layout.addWidget(self.log_text)
        diagnostic_buttons = QHBoxLayout()
        diagnostic_buttons.addWidget(self._button("Copy log", lambda: QApplication.clipboard().setText(self.log_text.toPlainText())))
        diagnostic_buttons.addWidget(self._button("Clear", self.log_text.clear))
        diagnostic_buttons.addStretch()
        diagnostic_buttons.addWidget(self._button("Close", self.diagnostics.close))
        diagnostic_layout.addLayout(diagnostic_buttons)

    def open_devices(self):
        self.device_dialog.open()

    def open_finder(self):
        self.finder_dialog.open()

    def open_settings(self):
        self.settings_dialog.open()

    def _set_status(self, text, color=MUTED):
        self.connection_status.setText(text)
        self.connection_status.setStyleSheet(f"font-size: 12px; color: {color};")

    def _update_controls(self, *args):
        if not hasattr(self, "output_combo"):
            return
        selected = self.device_list.currentItem()
        has_selection = selected is not None and not selected.isHidden()
        self.scan_btn.setEnabled(not self._connected and not self._scanning and not self._busy)
        self.device_list.setEnabled(not self._connected and not self._busy)
        self.show_all_check.setEnabled(not self._connected and not self._busy)
        self.connect_btn.setEnabled(self._connected or self._busy or (has_selection and not self._scanning))
        self.connect_btn.setText("Disconnect" if self._connected else ("Cancel" if self._busy else "Connect"))
        self.refresh_btn.setEnabled(self._connected and "refresh" not in self._pending_operations)
        self.remap_btn.setEnabled(self._connected and "touch" not in self._pending_operations)
        self.eq_combo.setEnabled(self._connected and "eq" not in self._pending_operations)
        self.eq_apply_btn.setEnabled(self._connected and self.eq_combo.currentData() is not None and "eq" not in self._pending_operations)
        self.sleep_combo.setEnabled(self._connected and "sleep" not in self._pending_operations)
        self.sleep_apply_btn.setEnabled(self._connected and self.sleep_combo.currentData() is not None and "sleep" not in self._pending_operations)
        can_ring = self.output_combo.currentData() is not None and not self._ring_busy
        for button in (self.btn_ring_l, self.btn_ring_both, self.btn_ring_r):
            button.setEnabled(can_ring)
        self.btn_ring_stop.setEnabled(self._ring_busy or self.audio_ringer.is_playing)

    def start_scan(self):
        if self._scanning or self._busy or self._connected or self._closing:
            return
        self._scanning = True
        if not self.device_dialog.isVisible():
            self.open_devices()
        self._user_selected = False
        self.device_list.clear()
        self._devices.clear()
        self.device_list.hide()
        self.empty_state.setText("Scanning…\n\nKeep the case open.")
        self.empty_state.show()
        self.discovery_summary.setText("Scanning nearby devices…")
        self.scan_btn.setText("Scanning…")
        self.feedback.hide()
        self._update_controls()
        self.worker.scan_devices()

    def on_device_discovered(self, address, name, rssi, candidate):
        old_selected = self.device_list.currentItem()
        current_address = old_selected.data(Qt.ItemDataRole.UserRole) if old_selected else None
        self.device_list.blockSignals(True)
        item = self._devices.get(address)
        if item is None:
            item = QListWidgetItem()
            self._devices[address] = item
        else:
            self.device_list.takeItem(self.device_list.row(item))
        strength = "Strong" if rssi >= -65 else ("Good" if rssi >= -80 else "Weak")
        item.setText(f"{name}\n{'Possible match' if candidate else 'Other device'} · {strength} signal")
        item.setToolTip(f"{name}\n{address}\nSignal: {rssi} dBm\nControl support is checked when connecting.")
        item.setData(Qt.ItemDataRole.UserRole, address)
        item.setData(Qt.ItemDataRole.UserRole + 1, (name, rssi, candidate))
        def rank(entry):
            _, signal, match = entry.data(Qt.ItemDataRole.UserRole + 1)
            return (not match, -signal, entry.text().casefold())
        position = 0
        while position < self.device_list.count() and rank(self.device_list.item(position)) <= rank(item):
            position += 1
        self.device_list.insertItem(position, item)
        item.setHidden(not candidate and not self.show_all_check.isChecked())
        preferred = self._devices.get(self._preferred_address) if not self._user_selected else None
        selected = preferred or (self._devices.get(current_address) if self._user_selected else None)
        if selected and not selected.isHidden():
            self.device_list.setCurrentItem(selected)
        else:
            self._select_first_visible()
        self.device_list.blockSignals(False)
        self._refresh_discovery_summary()
        self._update_controls()

    def _select_first_visible(self):
        for index in range(self.device_list.count()):
            item = self.device_list.item(index)
            if not item.isHidden():
                self.device_list.setCurrentItem(item)
                return
        self.device_list.setCurrentRow(-1)

    def _filter_devices(self, *args):
        for item in self._devices.values():
            candidate = item.data(Qt.ItemDataRole.UserRole + 1)[2]
            item.setHidden(not candidate and not self.show_all_check.isChecked())
        selected = self.device_list.currentItem()
        if selected is None or selected.isHidden():
            self._select_first_visible()
        self._refresh_discovery_summary()
        self._update_controls()

    def _refresh_discovery_summary(self):
        count = sum(not item.isHidden() for item in self._devices.values())
        self.device_list.setVisible(count > 0)
        self.empty_state.setVisible(count == 0)
        self.discovery_summary.setText(f"{count} nearby device{'s' if count != 1 else ''}" if count else "No matching earbuds found")

    def _selection_changed(self, current, previous):
        if current:
            self._user_selected = True
        self._update_controls()

    def on_scan_finished(self):
        self._scanning = False
        self.scan_btn.setText("Scan again")
        self.empty_state.setText("No earbuds found.\n\nOpen the case and scan again, or enable Show other Bluetooth LE devices.")
        self._refresh_discovery_summary()
        self._update_controls()

    def toggle_connection(self):
        if self._connected or self._busy:
            self.worker.disconnect_device()
            return
        selected = self.device_list.currentItem()
        if selected is None or selected.isHidden():
            return
        self._selected_address = selected.data(Qt.ItemDataRole.UserRole)
        self.device_title.setText(selected.data(Qt.ItemDataRole.UserRole + 1)[0])
        self._busy = True
        self.feedback.hide()
        self._update_controls()
        self.worker.connect_device(self._selected_address)

    def on_status_changed(self, state, message):
        self.connection_message.setText(message)
        self.connection_message.setVisible(state != "connected")
        self._busy = state in ("connecting", "reconnecting")
        if state == "error":
            self._show_error(message)
            self._set_status("Connection failed", "#ECA0A7")
        elif state in ("connecting", "reconnecting", "scanning"):
            self._set_status({"connecting": "Connecting…", "reconnecting": "Reconnecting…", "scanning": "Scanning…"}[state])
        elif state == "disconnected" and not self._connected:
            self._set_status("Disconnected")
        elif state == "connected":
            self._set_status("Connected", "#91BDAA")
        self._update_controls()

    def on_connection_changed(self, connected, message):
        self._connected = connected
        self._busy = False
        self._pending_operations.clear()
        self.card_beast.set_online(connected)
        self.card_spatial.set_online(connected)
        self.eq_combo.setCurrentIndex(0)
        self.sleep_combo.setCurrentIndex(0)
        self.feedback.hide()
        self.settings_feedback.hide()
        self.finder_feedback.hide()
        self.devices_btn.setText("Devices" if connected else "Connect earbuds")
        self._set_button_style(self.devices_btn, "quiet" if connected else "primary")
        self._set_button_style(self.connect_btn, "" if connected else "primary")
        if connected:
            self._preferred_address = self._selected_address or self._preferred_address
            self.settings.setValue("last_device", self._preferred_address)
            selected = self._devices.get(self._preferred_address)
            name = selected.data(Qt.ItemDataRole.UserRole + 1)[0] if selected else "Earbuds"
            self.device_title.setText(name)
            self._set_status("Connected", "#91BDAA")
            self.battery_status.setText("Waiting for battery data…")
            self.device_dialog.accept()
        else:
            self.stop_ring()
            self.device_title.setText("No device connected")
            self.battery_status.setText("")
            self._set_status("Disconnected")
            if self._touch_dialog:
                self._touch_dialog.reject()
        for card in (self.card_left, self.card_right, self.card_case):
            card.set_offline()
        self._update_controls()

    def on_battery_updated(self, left, left_charging, right, right_charging, case, case_charging):
        if not self._connected:
            return
        self.card_left.set_level(left, left_charging)
        self.card_right.set_level(right, right_charging)
        self.card_case.set_level(case, case_charging)
        self.battery_status.setText("Updated " + datetime.now().strftime("%H:%M"))
        self._pending_operations.discard("refresh")
        self._update_controls()

    def refresh_battery(self):
        self._pending_operations.add("refresh")
        self.battery_status.setText("Refreshing…")
        self._update_controls()
        self.worker.query_battery()
        QTimer.singleShot(6000, self._battery_refresh_timeout)

    def _battery_refresh_timeout(self):
        if "refresh" in self._pending_operations:
            self._pending_operations.discard("refresh")
            self.battery_status.setText("No battery update received")
            self._update_controls()

    def apply_eq(self):
        self._pending_operations.add("eq")
        self._update_controls()
        self.worker.set_eq_preset(self.eq_combo.currentData())

    def apply_sleep(self):
        self._pending_operations.add("sleep")
        self._update_controls()
        self.worker.set_auto_shutdown(self.sleep_combo.currentData())

    def on_command_result(self, operation, success, message):
        if not self._connected:
            return
        if operation != "refresh" or not success:
            self._pending_operations.discard(operation)
        if not success:
            if operation == "beast":
                self.card_beast.fail_pending()
            elif operation == "spatial":
                self.card_spatial.fail_pending()
            self._show_error(message)
        elif operation in ("eq", "sleep", "touch"):
            title = {"eq": "Sound profile", "sleep": "Idle power-off timer", "touch": "Touch controls"}[operation]
            self._show_feedback(f"{title}: {message}")
        self._update_controls()

    def _show_feedback(self, message, error=False):
        target = self.feedback
        if self.finder_dialog.isVisible():
            target = self.finder_feedback
        elif self.settings_dialog.isVisible():
            target = self.settings_feedback
        elif self.device_dialog.isVisible():
            target = self.connection_message
        target.setText(message)
        target.setStyleSheet("font-size: 12px; padding: 5px 0; color: " + ("#F2A4AD;" if error else "#B7BAC5;"))
        target.show()

    def _show_error(self, message):
        self._show_feedback(message, True)

    def _reconnect_changed(self, enabled):
        self.worker.set_auto_reconnect(enabled)
        self.settings.setValue("auto_reconnect", enabled)

    def refresh_audio_outputs(self):
        self.stop_ring()
        self.output_combo.blockSignals(True)
        self.output_combo.clear()
        self.output_combo.addItem("Select earbud audio output", None)
        try:
            for index, name in self.audio_ringer.output_devices():
                self.output_combo.addItem(name, index)
                self.output_combo.setItemData(self.output_combo.count() - 1, name, Qt.ItemDataRole.ToolTipRole)
        except Exception as error:
            self.on_log_message("ERROR", f"Audio outputs unavailable: {error}")
            self.ring_status_lbl.setText("Audio output unavailable")
        self.output_combo.blockSignals(False)
        self._update_controls()

    def _output_changed(self, *args):
        self.stop_ring()
        self._update_controls()

    def start_ring(self, channel):
        if self.output_combo.currentData() is None:
            return
        self._ring_busy = True
        self.ring_status_lbl.setText("Starting sound…")
        self._update_controls()
        self.audio_ringer.start(channel, self.output_combo.currentData())

    def on_ring_started(self, channel):
        self._ring_busy = True
        self.ring_status_lbl.setText("Playing · " + {"left": "Left earbud", "right": "Right earbud", "both": "Both earbuds"}[channel])
        self.ring_status_lbl.setStyleSheet("color: #91BDAA; font-size: 12px;")
        self._update_controls()

    def stop_ring(self):
        self.audio_ringer.stop()
        self._ring_busy = False
        if hasattr(self, "ring_status_lbl"):
            self.on_ring_stopped()

    def on_ring_stopped(self):
        self._ring_busy = False
        self.ring_status_lbl.setText("Sound is off")
        self.ring_status_lbl.setStyleSheet("color: #A0A2AA; font-size: 12px;")
        self._update_controls()

    def _audio_error(self, message):
        self.on_ring_stopped()
        self._show_error(message)
        self.on_log_message("ERROR", message)

    def open_touch_remapper(self):
        if not self._connected:
            return
        dialog = QDialog(self)
        self._touch_dialog = dialog
        dialog.setWindowTitle("Touch controls")
        dialog.resize(520, 510)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(15)
        layout.addWidget(label("Only selected gestures will change. Available actions depend on the earbuds.", "muted", True))
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        combos = {}
        for row, (name, key) in enumerate(KEY_TYPES.items()):
            grid.addWidget(label(name), row, 0)
            combo = QComboBox()
            combo.setAccessibleName(name)
            combo.addItem("Keep current", None)
            for function, value in KEY_FUNCTIONS.items():
                combo.addItem(function, value)
            combos[key] = combo
            grid.addWidget(combo, row, 1)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Cancel", dialog.reject, "quiet"))
        actions.addStretch()
        def apply_changes():
            changes = [(key, combo.currentData()) for key, combo in combos.items() if combo.currentData() is not None]
            if changes and self._connected:
                self._pending_operations.add("touch")
                self._update_controls()
                self.worker.set_key_mappings(changes)
                dialog.accept()
        apply_button = self._button("Apply changes", apply_changes, "primary")
        apply_button.setEnabled(False)
        for combo in combos.values():
            combo.currentIndexChanged.connect(lambda: apply_button.setEnabled(any(cb.currentData() is not None for cb in combos.values())))
        actions.addWidget(apply_button)
        layout.addLayout(actions)
        dialog.exec()
        self._touch_dialog = None
        dialog.deleteLater()

    def open_connection_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Connection help")
        dialog.resize(530, 440)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        layout.addWidget(label("Bluetooth setup", "sectionTitle"))
        for title, text in (
            ("1. Start with Windows Bluetooth", "Turn on Bluetooth and pair your earbuds in Windows Settings. This handles music and calls."),
            ("2. Keep your earbuds available", "Open the case or take the earbuds out. Keep them nearby and close the phone companion app if it is using the control connection."),
            ("3. Scan for the control connection", "Open Devices and choose your earbuds. Enable Show other Bluetooth LE devices if they appear with a different name."),
            ("Audio and controls connect separately", "This app uses a Bluetooth LE control connection. For the finder, select the stereo audio output belonging to your earbuds. Classic-only devices and other vendor protocols cannot use these controls."),
        ):
            layout.addWidget(label(title))
            layout.addWidget(label(text, "muted", True))
        layout.addWidget(self._button("Got it", dialog.accept, "primary"))
        dialog.exec()
        dialog.deleteLater()

    def open_diagnostics(self):
        self.diagnostics.show()
        self.diagnostics.raise_()
        self.diagnostics.activateWindow()

    def on_log_message(self, tag, text):
        colors = {"TX": "#96B9FF", "RX": "#8AE6C5", "SCAN": "#D4C3FF", "CONN": "#F3D095", "ERROR": "#FF9AA9", "WARN": "#F3D095"}
        color = colors.get(tag, MUTED)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f'<span style="color: #7E8BA4">{timestamp}</span> '
                             f'<span style="color: {color}">[{html.escape(tag)}]</span> {html.escape(text)}')

    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore()
            if not self._closing:
                self._closing = True
                self.stop_ring()
                self.setEnabled(False)
                self.connection_message.setText("Closing Bluetooth connection…")
                self.worker.finished.connect(self.close)
                self.worker.shutdown()
        else:
            self.audio_ringer.stop()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("boAt Hearables")
    app.setOrganizationName("JaydeepPatil")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
