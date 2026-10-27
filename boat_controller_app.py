"""
boAt Airdopes Control Hub (Windows)
A modern, minimalist desktop companion app for boAt Airdopes Plus 222 & Bluetrum-based TWS earbuds.
"""

import sys
import asyncio
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QComboBox, QFrame,
    QGridLayout, QDialog, QTextEdit
)
from bleak import BleakScanner, BleakClient

from protocol import (
    BLUETRUM_SERVICE_UUID, WRITE_CHAR_UUID, NOTIFY_CHAR_UUID,
    CMD_EQ, CMD_KEY, CMD_AUTO_SHUTDOWN, CMD_WORK_MODE,
    CMD_DEVICE_INFO, CMD_FIND_DEVICE, CMD_NAME, CMD_SPATIAL_AUDIO,
    INFO_TYPE_POWER, INFO_TYPE_WORK_MODE, INFO_TYPE_SPATIAL_AUDIO, INFO_TYPE_MAX_PACKET,
    EQ_PRESETS, KEY_FUNCTIONS, KEY_TYPES, make_packet
)
from audio_ringer import EarbudsAudioRinger


# ==============================================================================
# BLE Background Worker Thread
# ==============================================================================

class BleWorker(QThread):
    device_discovered     = pyqtSignal(str, str, int, bool)
    scan_finished         = pyqtSignal()
    connection_changed    = pyqtSignal(bool, str)
    battery_updated       = pyqtSignal(int, bool, int, bool, int, bool)
    beast_mode_updated    = pyqtSignal(bool)
    spatial_audio_updated = pyqtSignal(bool)
    log_message           = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.client: Optional[BleakClient] = None
        self.seq = 0
        self.running = True
        self.is_connected = False

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _next_packet(self, cmd: int, cmd_type: int, payload: bytes) -> bytes:
        pkt = make_packet(self.seq, cmd, cmd_type, payload)
        self.seq = (self.seq + 1) & 0x0F
        return pkt

    def scan_devices(self):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_scan(), self.loop)

    async def _async_scan(self):
        self.log_message.emit("SCAN", "Scanning nearby BLE devices...")
        try:
            devices = await BleakScanner.discover(timeout=4.5, return_adv=True)
            for d, adv in devices.values():
                name = d.name or adv.local_name or "Unknown Device"
                is_bluetrum = (
                    (adv.service_uuids and BLUETRUM_SERVICE_UUID in adv.service_uuids)
                    or (1602 in adv.manufacturer_data)
                    or ("222" in name) or ("boAt" in name)
                )
                self.device_discovered.emit(d.address, name, adv.rssi, is_bluetrum)
            self.log_message.emit("SCAN", f"Found {len(devices)} device(s).")
        except Exception as e:
            self.log_message.emit("ERROR", str(e))
        finally:
            self.scan_finished.emit()

    def connect_device(self, address: str):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_connect(address), self.loop)

    async def _async_connect(self, address: str):
        self.log_message.emit("CONN", f"Connecting to {address}...")
        try:
            self.client = BleakClient(address)
            await self.client.connect()
            self.is_connected = True
            self.connection_changed.emit(True, "Connected")
            await self.client.start_notify(NOTIFY_CHAR_UUID, self._on_notification)
            await asyncio.sleep(0.3)

            # Protocol Handshake
            await self._async_send(self._next_packet(CMD_DEVICE_INFO, 1, bytes([INFO_TYPE_MAX_PACKET, 0x00])))
            await asyncio.sleep(0.3)

            # Query Initial States (Battery, BEAST mode, Spatial Audio)
            await self._async_send(self._next_packet(CMD_DEVICE_INFO, 1, bytes([INFO_TYPE_POWER, 0x00])))
            await asyncio.sleep(0.3)
            await self._async_send(self._next_packet(CMD_DEVICE_INFO, 1, bytes([INFO_TYPE_WORK_MODE, 0x00])))
            await asyncio.sleep(0.3)
            await self._async_send(self._next_packet(CMD_DEVICE_INFO, 1, bytes([INFO_TYPE_SPATIAL_AUDIO, 0x00])))

            asyncio.create_task(self._poll_loop())
        except Exception as e:
            self.is_connected = False
            self.connection_changed.emit(False, str(e))
            self.log_message.emit("ERROR", f"Connection failed: {e}")

    async def _poll_loop(self):
        while self.is_connected and self.client and self.client.is_connected:
            await asyncio.sleep(12.0)
            if self.is_connected:
                pkt = self._next_packet(CMD_DEVICE_INFO, 1, bytes([INFO_TYPE_POWER, 0x00]))
                await self._async_send(pkt)

    def disconnect_device(self):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_disconnect(), self.loop)

    async def _async_disconnect(self):
        self.is_connected = False
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.connection_changed.emit(False, "Disconnected")

    async def _async_send(self, packet: bytes):
        if not self.client or not self.client.is_connected:
            return
        await self.client.write_gatt_char(WRITE_CHAR_UUID, packet, response=False)
        self.log_message.emit("TX", " ".join(f"{b:02X}" for b in packet))

    def _on_notification(self, sender, data: bytearray):
        self.log_message.emit("RX", " ".join(f"{b:02X}" for b in data))
        if len(data) < 5:
            return
        cmd = data[1]
        payload = data[5:]

        if cmd == CMD_DEVICE_INFO:
            idx = 0
            while idx < len(payload):
                if idx + 1 >= len(payload):
                    break
                t = payload[idx]
                l = payload[idx + 1]
                val = payload[idx + 2 : idx + 2 + l]
                idx += 2 + l

                if t == INFO_TYPE_POWER and len(val) >= 3:
                    l_lvl, l_chg = val[0] & 0x7F, bool(val[0] & 0x80)
                    r_lvl, r_chg = val[1] & 0x7F, bool(val[1] & 0x80)
                    c_lvl, c_chg = val[2] & 0x7F, bool(val[2] & 0x80)
                    self.battery_updated.emit(l_lvl, l_chg, r_lvl, r_chg, c_lvl, c_chg)
                elif t == INFO_TYPE_WORK_MODE and len(val) >= 1:
                    self.beast_mode_updated.emit(val[0] == 1)
                elif t == INFO_TYPE_SPATIAL_AUDIO and len(val) >= 1:
                    self.spatial_audio_updated.emit(val[0] != 0)

        elif cmd == CMD_WORK_MODE:
            val = payload[0] if len(payload) > 0 else 0
            self.beast_mode_updated.emit(val == 1)

    def query_battery(self):
        if self.loop and self.loop.is_running():
            pkt = self._next_packet(CMD_DEVICE_INFO, 1, bytes([INFO_TYPE_POWER, 0x00]))
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)

    def set_beast_mode(self, enable: bool):
        if self.loop and self.loop.is_running():
            pkt = self._next_packet(CMD_WORK_MODE, 1, bytes([0x01 if enable else 0x00]))
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)

    def set_spatial_audio(self, enable: bool):
        if self.loop and self.loop.is_running():
            pkt = self._next_packet(CMD_SPATIAL_AUDIO, 1, bytes([0x01 if enable else 0x00]))
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)
            self.spatial_audio_updated.emit(enable)

    def set_eq_preset(self, preset_name: str):
        if self.loop and self.loop.is_running() and preset_name in EQ_PRESETS:
            gains = EQ_PRESETS[preset_name]
            pkt = self._next_packet(CMD_EQ, 1, bytes([10, 0x20]) + gains)
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)

    def set_auto_shutdown(self, minutes: int):
        if self.loop and self.loop.is_running():
            pkt = self._next_packet(CMD_AUTO_SHUTDOWN, 1, bytes([minutes & 0xFF]))
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)

    def set_key_mapping(self, key_type: int, function_id: int):
        if self.loop and self.loop.is_running():
            payload = bytes([key_type, 1, function_id])
            pkt = self._next_packet(CMD_KEY, 1, payload)
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)

    def set_bluetooth_name(self, name: str):
        if self.loop and self.loop.is_running() and name.strip():
            pkt = self._next_packet(CMD_NAME, 1, name.strip().encode('utf-8'))
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)

    def stop_hardware_buzzer(self):
        if self.loop and self.loop.is_running():
            pkt = self._next_packet(CMD_FIND_DEVICE, 1, bytes([0x00]))
            asyncio.run_coroutine_threadsafe(self._async_send(pkt), self.loop)


# ==============================================================================
# UI Component Widgets
# ==============================================================================

class BatteryCard(QFrame):
    """Clean minimal battery card displaying level, icon, and charging state."""
    def __init__(self, title: str, icon_symbol: str):
        super().__init__()
        self.setObjectName("batCard")
        self.setStyleSheet("""
            QFrame#batCard {
                background-color: #16181E;
                border: 1px solid #232630;
                border-radius: 14px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        top_h = QHBoxLayout()
        icon_lbl = QLabel(icon_symbol)
        icon_lbl.setStyleSheet("font-size: 15px; color: #8C92A4;")
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #7B8194;")
        self.chg_lbl = QLabel("")
        self.chg_lbl.setStyleSheet("font-size: 12px; color: #00E676; font-weight: bold;")

        top_h.addWidget(icon_lbl)
        top_h.addWidget(title_lbl)
        top_h.addStretch()
        top_h.addWidget(self.chg_lbl)
        layout.addLayout(top_h)

        self.val_lbl = QLabel("--")
        self.val_lbl.setStyleSheet("font-size: 26px; font-weight: 700; color: #F0F2F5;")
        layout.addWidget(self.val_lbl)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(5)
        self.pbar.setTextVisible(False)
        self.pbar.setValue(0)
        self.pbar.setStyleSheet("""
            QProgressBar {
                background-color: #242833;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #E60026;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.pbar)

    def set_level(self, level: int, is_charging: bool):
        self.val_lbl.setText(f"{level}%")
        self.pbar.setValue(level)
        chunk_color = "#00E676" if is_charging else "#E60026"
        self.chg_lbl.setText("⚡" if is_charging else "")
        self.pbar.setStyleSheet(f"""
            QProgressBar {{ background-color: #242833; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background-color: {chunk_color}; border-radius: 2px; }}
        """)

    def set_offline(self):
        self.val_lbl.setText("--")
        self.pbar.setValue(0)
        self.chg_lbl.setText("")


class FeatureCard(QFrame):
    """Modern quick-toggle card with state indicator and pill switch."""
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, subtitle: str, icon_str: str):
        super().__init__()
        self.is_active = False
        self.setObjectName("featureCard")
        self.setStyleSheet("""
            QFrame#featureCard {
                background-color: #16181E;
                border: 1px solid #232630;
                border-radius: 14px;
            }
            QFrame#featureCard:hover {
                border-color: #313645;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)

        icon_lbl = QLabel(icon_str)
        icon_lbl.setStyleSheet("font-size: 20px; margin-right: 6px;")
        layout.addWidget(icon_lbl)

        txt_v = QVBoxLayout()
        txt_v.setSpacing(2)
        title_l = QLabel(title)
        title_l.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        self.sub_l = QLabel(subtitle)
        self.sub_l.setStyleSheet("font-size: 11px; color: #7B8194;")
        txt_v.addWidget(title_l)
        txt_v.addWidget(self.sub_l)
        layout.addLayout(txt_v)

        layout.addStretch()

        self.btn = QPushButton("OFF")
        self.btn.setFixedSize(62, 28)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._on_clicked)
        self.update_btn_style()
        layout.addWidget(self.btn)

    def _on_clicked(self):
        self.is_active = not self.is_active
        self.update_btn_style()
        self.toggled.emit(self.is_active)

    def set_state(self, active: bool):
        self.is_active = active
        self.update_btn_style()

    def update_btn_style(self):
        if self.is_active:
            self.btn.setText("ON")
            self.btn.setStyleSheet("""
                QPushButton {
                    background-color: #E60026;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-size: 11px;
                    font-weight: 700;
                }
            """)
        else:
            self.btn.setText("OFF")
            self.btn.setStyleSheet("""
                QPushButton {
                    background-color: #232630;
                    color: #7B8194;
                    border: none;
                    border-radius: 14px;
                    font-size: 11px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #2E3240;
                    color: #A0A6B8;
                }
            """)


# ==============================================================================
# Main Application Window
# ==============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("boAt Airdopes")
        self.resize(500, 700)
        self.setMinimumSize(460, 640)

        self.audio_ringer = EarbudsAudioRinger()
        self.worker = BleWorker()
        self.worker.start()

        self.worker.device_discovered.connect(self.on_device_discovered)
        self.worker.scan_finished.connect(self.on_scan_finished)
        self.worker.connection_changed.connect(self.on_connection_changed)
        self.worker.battery_updated.connect(self.on_battery_updated)
        self.worker.beast_mode_updated.connect(self.on_beast_mode_updated)
        self.worker.spatial_audio_updated.connect(self.on_spatial_audio_updated)
        self.worker.log_message.connect(self.on_log_message)

        self.discovered_addresses = set()

        self.apply_global_theme()
        self.init_ui()

        QTimer.singleShot(400, self.start_scan)

    def apply_global_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0C0D11;
            }
            QLabel {
                color: #F0F2F5;
                font-family: 'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif;
            }
            QComboBox {
                background-color: #16181E;
                color: #F0F2F5;
                border: 1px solid #232630;
                border-radius: 10px;
                padding: 7px 12px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #16181E;
                color: #FFFFFF;
                border: 1px solid #2A2E3B;
                selection-background-color: #E60026;
                padding: 4px;
            }
            QPushButton {
                background-color: #16181E;
                color: #F0F2F5;
                border: 1px solid #232630;
                border-radius: 10px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #21242D;
                border-color: #313645;
            }
            QTextEdit {
                background-color: #0E0F14;
                color: #8CE08C;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid #1E2129;
                border-radius: 8px;
            }
        """)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(22, 20, 22, 18)
        main_layout.setSpacing(16)

        # 1. Header Bar: Brand + Connection Status Pill
        header = QHBoxLayout()
        header.setSpacing(10)

        title_v = QVBoxLayout()
        title_v.setSpacing(1)
        title_lbl = QLabel("boAt Airdopes")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #FFFFFF;")
        sub_lbl = QLabel("Plus 222 • TWS Bluetooth")
        sub_lbl.setStyleSheet("font-size: 11px; color: #6F7587;")
        title_v.addWidget(title_lbl)
        title_v.addWidget(sub_lbl)
        header.addLayout(title_v)

        header.addStretch()

        self.conn_pill = QLabel("● Disconnected")
        self.conn_pill.setStyleSheet("""
            background-color: #1A1C22;
            color: #7B8194;
            padding: 5px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        """)
        header.addWidget(self.conn_pill)
        main_layout.addLayout(header)

        # 2. Connection Island
        conn_frame = QFrame()
        conn_frame.setStyleSheet("""
            QFrame {
                background-color: #13141A;
                border: 1px solid #1F222B;
                border-radius: 12px;
                padding: 4px;
            }
        """)
        conn_h = QHBoxLayout(conn_frame)
        conn_h.setContentsMargins(6, 4, 6, 4)
        conn_h.setSpacing(8)

        self.dev_combo = QComboBox()
        self.dev_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        conn_h.addWidget(self.dev_combo, stretch=1)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setFixedWidth(64)
        self.scan_btn.clicked.connect(self.start_scan)
        conn_h.addWidget(self.scan_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setFixedWidth(80)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #E60026;
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #FF1A38;
            }
        """)
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_h.addWidget(self.connect_btn)

        main_layout.addWidget(conn_frame)

        # 3. Battery Section (Left, Case, Right)
        bat_h = QHBoxLayout()
        bat_h.setSpacing(10)

        self.card_left = BatteryCard("Left Earbud", "🎧")
        self.card_case = BatteryCard("Charging Case", "🔋")
        self.card_right = BatteryCard("Right Earbud", "🎧")

        bat_h.addWidget(self.card_left)
        bat_h.addWidget(self.card_case)
        bat_h.addWidget(self.card_right)
        main_layout.addLayout(bat_h)

        # 4. Feature Cards (BEAST Mode & Spatial Audio)
        features_h = QHBoxLayout()
        features_h.setSpacing(10)

        self.card_beast = FeatureCard("BEAST™ Mode", "55ms Low Latency", "⚡")
        self.card_beast.toggled.connect(self.worker.set_beast_mode)

        self.card_spatial = FeatureCard("Spatial Audio", "3D Soundstage", "🌐")
        self.card_spatial.toggled.connect(self.worker.set_spatial_audio)

        features_h.addWidget(self.card_beast)
        features_h.addWidget(self.card_spatial)
        main_layout.addLayout(features_h)

        # 5. Equalizer Selection
        eq_frame = QFrame()
        eq_frame.setStyleSheet("""
            QFrame {
                background-color: #16181E;
                border: 1px solid #232630;
                border-radius: 14px;
                padding: 8px 12px;
            }
        """)
        eq_layout = QHBoxLayout(eq_frame)
        eq_layout.setContentsMargins(10, 6, 10, 6)

        eq_title_l = QLabel("🎚 Sound Profile")
        eq_title_l.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        eq_layout.addWidget(eq_title_l)
        eq_layout.addStretch()

        self.eq_combo = QComboBox()
        self.eq_combo.addItems(list(EQ_PRESETS.keys()))
        self.eq_combo.setMinimumWidth(150)
        self.eq_combo.currentTextChanged.connect(self.worker.set_eq_preset)
        eq_layout.addWidget(self.eq_combo)
        main_layout.addWidget(eq_frame)

        # 6. Find Earbuds - Minimal Segmented Controller
        find_frame = QFrame()
        find_frame.setStyleSheet("""
            QFrame {
                background-color: #16181E;
                border: 1px solid #232630;
                border-radius: 14px;
                padding: 10px;
            }
        """)
        find_layout = QVBoxLayout(find_frame)
        find_layout.setContentsMargins(10, 8, 10, 8)
        find_layout.setSpacing(8)

        find_top = QHBoxLayout()
        find_title = QLabel("🔔 Find My Earbuds")
        find_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        self.ring_status_lbl = QLabel("Sound is off")
        self.ring_status_lbl.setStyleSheet("font-size: 11px; color: #6F7587;")
        find_top.addWidget(find_title)
        find_top.addStretch()
        find_top.addWidget(self.ring_status_lbl)
        find_layout.addLayout(find_top)

        btns_h = QHBoxLayout()
        btns_h.setSpacing(6)

        self.btn_ring_l = QPushButton("Left Bud")
        self.btn_ring_l.clicked.connect(lambda: self.start_ring("left"))
        self.btn_ring_both = QPushButton("Both Buds")
        self.btn_ring_both.clicked.connect(lambda: self.start_ring("both"))
        self.btn_ring_r = QPushButton("Right Bud")
        self.btn_ring_r.clicked.connect(lambda: self.start_ring("right"))

        self.btn_ring_stop = QPushButton("Stop")
        self.btn_ring_stop.setStyleSheet("""
            QPushButton {
                background-color: #2E1619;
                color: #FF5264;
                border: 1px solid #4A1C22;
                border-radius: 8px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #FF1A38;
                color: white;
            }
        """)
        self.btn_ring_stop.clicked.connect(self.stop_ring)

        btns_h.addWidget(self.btn_ring_l)
        btns_h.addWidget(self.btn_ring_both)
        btns_h.addWidget(self.btn_ring_r)
        btns_h.addWidget(self.btn_ring_stop)
        find_layout.addLayout(btns_h)

        main_layout.addWidget(find_frame)

        # 7. Utilities Bar & Collapsible Sniffer Drawer
        bottom_h = QHBoxLayout()
        self.remap_btn = QPushButton("✋ Touch Remapper")
        self.remap_btn.clicked.connect(self.open_touch_remapper)

        self.sleep_combo = QComboBox()
        self.sleep_combo.addItem("⏱ Sleep: Off", 0)
        self.sleep_combo.addItem("⏱ Sleep: 5m", 5)
        self.sleep_combo.addItem("⏱ Sleep: 10m", 10)
        self.sleep_combo.addItem("⏱ Sleep: 30m", 30)
        self.sleep_combo.currentIndexChanged.connect(self.on_sleep_changed)

        self.log_toggle_btn = QPushButton("Protocol Log ▾")
        self.log_toggle_btn.clicked.connect(self.toggle_log_drawer)

        bottom_h.addWidget(self.remap_btn)
        bottom_h.addWidget(self.sleep_combo)
        bottom_h.addWidget(self.log_toggle_btn)
        main_layout.addLayout(bottom_h)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(100)
        self.log_text.setVisible(False)
        main_layout.addWidget(self.log_text)

    def start_scan(self):
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("...")
        self.dev_combo.clear()
        self.discovered_addresses.clear()
        self.worker.scan_devices()

    def on_device_discovered(self, address: str, name: str, rssi: int, is_bluetrum: bool):
        if address in self.discovered_addresses:
            return
        self.discovered_addresses.add(address)
        prefix = "★ " if is_bluetrum else ""
        self.dev_combo.addItem(f"{prefix}{name} ({address})", address)
        if is_bluetrum or "222" in name:
            self.dev_combo.setCurrentIndex(self.dev_combo.count() - 1)

    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan")

    def toggle_connection(self):
        if not self.worker.is_connected:
            addr = self.dev_combo.currentData()
            if not addr:
                return
            self.connect_btn.setEnabled(False)
            self.connect_btn.setText("...")
            self.worker.connect_device(addr)
        else:
            self.worker.disconnect_device()

    def on_connection_changed(self, is_connected: bool, message: str):
        self.connect_btn.setEnabled(True)
        if is_connected:
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #232630;
                    color: #A0A6B8;
                    border: 1px solid #313645;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #313645;
                    color: white;
                }
            """)
            self.conn_pill.setText("● Connected")
            self.conn_pill.setStyleSheet("""
                background-color: #112818;
                color: #00E676;
                padding: 5px 12px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
            """)
        else:
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E60026;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #FF1A38;
                }
            """)
            self.conn_pill.setText("● Disconnected")
            self.conn_pill.setStyleSheet("""
                background-color: #1A1C22;
                color: #7B8194;
                padding: 5px 12px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
            """)
            self.card_left.set_offline()
            self.card_case.set_offline()
            self.card_right.set_offline()
            self.card_beast.set_state(False)
            self.card_spatial.set_state(False)

    def on_battery_updated(self, l_lvl, l_chg, r_lvl, r_chg, c_lvl, c_chg):
        self.card_left.set_level(l_lvl, l_chg)
        self.card_case.set_level(c_lvl, c_chg)
        self.card_right.set_level(r_lvl, r_chg)

    def on_beast_mode_updated(self, is_beast: bool):
        self.card_beast.set_state(is_beast)

    def on_spatial_audio_updated(self, is_spatial: bool):
        self.card_spatial.set_state(is_spatial)

    def start_ring(self, channel: str):
        self.audio_ringer.start(channel)
        label_text = f"Playing on {channel.capitalize()} bud" if channel != "both" else "Playing on Both buds"
        self.ring_status_lbl.setText(f"🔔 {label_text}")
        self.ring_status_lbl.setStyleSheet("font-size: 11px; color: #00E676; font-weight: bold;")

    def stop_ring(self):
        self.audio_ringer.stop()
        self.worker.stop_hardware_buzzer()
        self.ring_status_lbl.setText("Sound is off")
        self.ring_status_lbl.setStyleSheet("font-size: 11px; color: #6F7587;")

    def toggle_log_drawer(self):
        visible = not self.log_text.isVisible()
        self.log_text.setVisible(visible)
        self.log_toggle_btn.setText("Protocol Log ▴" if visible else "Protocol Log ▾")

    def on_sleep_changed(self):
        mins = self.sleep_combo.currentData()
        self.worker.set_auto_shutdown(mins)

    def open_touch_remapper(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Touch Controls Remapper")
        dlg.setFixedSize(420, 380)
        dlg.setStyleSheet("""
            QDialog { background-color: #121318; }
            QLabel { color: #E0E2E8; font-size: 12px; }
            QComboBox { background-color: #1A1C22; color: white; border: 1px solid #2B2E38; border-radius: 6px; padding: 5px; }
            QPushButton { background-color: #E60026; color: white; border-radius: 6px; padding: 7px 14px; font-weight: bold; }
        """)
        d_layout = QVBoxLayout(dlg)
        d_layout.setContentsMargins(18, 16, 18, 16)
        d_layout.setSpacing(10)

        grid = QGridLayout()
        combos = {}
        row = 0
        for name, k_id in KEY_TYPES.items():
            grid.addWidget(QLabel(name + ":"), row, 0)
            cb = QComboBox()
            for fn_name, fn_id in KEY_FUNCTIONS.items():
                cb.addItem(fn_name, fn_id)
            combos[k_id] = cb
            grid.addWidget(cb, row, 1)
            row += 1

        d_layout.addLayout(grid)

        btn_h = QHBoxLayout()
        apply_btn = QPushButton("Save to Earbuds")
        apply_btn.clicked.connect(lambda: [self.worker.set_key_mapping(k_id, cb.currentData()) for k_id, cb in combos.items()] + [dlg.close()])
        btn_h.addStretch()
        btn_h.addWidget(apply_btn)
        d_layout.addLayout(btn_h)
        dlg.exec()

    def on_log_message(self, tag: str, text: str):
        color_map = {"TX": "#00E5FF", "RX": "#00E676", "SCAN": "#FFD600", "CONN": "#FF9100", "ERROR": "#FF1744"}
        color = color_map.get(tag, "#A0A6B8")
        self.log_text.append(f'<span style="color: {color};">[{tag}]</span> {text}')

    def closeEvent(self, event):
        self.audio_ringer.stop()
        self.worker.stop_hardware_buzzer()
        self.worker.disconnect_device()
        self.worker.running = False
        if self.worker.loop:
            self.worker.loop.call_soon_threadsafe(self.worker.loop.stop)
        self.worker.quit()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
