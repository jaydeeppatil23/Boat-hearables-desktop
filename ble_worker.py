"""Bluetooth control, isolated from the UI and confined to one asyncio thread."""

import asyncio
import concurrent.futures
import sys
from contextlib import suppress

from bleak import BleakClient, BleakScanner
from PyQt6.QtCore import QThread, pyqtSignal

from protocol import (
    BLUETRUM_SERVICE_UUID, WRITE_CHAR_UUID, NOTIFY_CHAR_UUID,
    CMD_EQ, CMD_KEY, CMD_AUTO_SHUTDOWN, CMD_WORK_MODE, CMD_DEVICE_INFO,
    CMD_NOTIFY, CMD_FIND_DEVICE, CMD_NAME, CMD_SPATIAL_AUDIO,
    INFO_TYPE_POWER, INFO_TYPE_WORK_MODE, INFO_TYPE_SPATIAL_AUDIO,
    INFO_TYPE_MAX_PACKET, EQ_PRESETS, PacketDecoder, make_packet, parse_tlvs,
)


def is_candidate(device, advertisement) -> bool:
    """Advertising hints help discovery; GATT characteristics establish support."""
    name = (advertisement.local_name or device.name or "").casefold()
    services = {uuid.casefold() for uuid in advertisement.service_uuids or []}
    return (BLUETRUM_SERVICE_UUID in services
            or 1602 in (advertisement.manufacturer_data or {})
            or any(word in name for word in ("boat", "airdopes", "rockerz", "bluetrum")))


def connection_help(error: Exception) -> str:
    detail = str(error).strip() or type(error).__name__
    lowered = detail.casefold()
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "Connection timed out. Keep the earbuds awake and nearby, then scan again."
    if "bluetooth" in lowered and any(word in lowered for word in ("off", "available", "disabled")):
        return "Turn on Bluetooth in Windows Settings, then scan again."
    if any(word in lowered for word in ("denied", "permission", "unauthorized")):
        return "Bluetooth access was denied. Check Windows Bluetooth permissions."
    if any(word in lowered for word in ("not found", "unreachable", "not discover")):
        return "Earbuds are unavailable. Open the case, move closer, and scan again."
    return f"{detail} Close the phone companion app and try again."


class UnsupportedDeviceError(Exception):
    pass


class BleWorker(QThread):
    ready = pyqtSignal()
    device_discovered = pyqtSignal(str, str, int, bool)
    scan_finished = pyqtSignal()
    status_changed = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool, str)
    battery_updated = pyqtSignal(int, bool, int, bool, int, bool)
    beast_mode_updated = pyqtSignal(bool)
    spatial_audio_updated = pyqtSignal(bool)
    command_result = pyqtSignal(str, bool, str)
    log_message = pyqtSignal(str, str)

    SCAN_SECONDS = 6.0
    CONNECT_TIMEOUT = 18.0
    COMMAND_RESPONSE_TIMEOUT = 2.0
    RETRY_DELAYS = (2.0, 4.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop = None
        self.client = None
        self.is_connected = False
        self.auto_reconnect = True
        self.seq = 0
        self._devices = {}
        self._scan_task = None
        self._connect_task = None
        self._poll_task = None
        self._write_lock = None
        self._command_lock = None
        self._target_address = None
        self._closing = False
        self._write_char = None
        self._notify_char = None
        self._write_response = False
        self._decoder = PacketDecoder()
        self._last_commands = {}
        self._shutdown_task = None

    def run(self):
        # Qt's UI thread and BLE's WinRT thread have different COM requirements.
        if sys.platform == "win32":
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._write_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self.loop.call_soon(lambda: self._start_shutdown() if self._closing else self.ready.emit())
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def _submit(self, factory):
        if self._closing or not self.loop or not self.loop.is_running():
            return
        async def execute():
            await factory()
        future = asyncio.run_coroutine_threadsafe(execute(), self.loop)
        future.add_done_callback(self._report_failure)
        return future

    def _report_failure(self, future):
        try:
            future.result()
        except (asyncio.CancelledError, concurrent.futures.CancelledError):
            pass
        except Exception as error:
            self.log_message.emit("ERROR", str(error) or type(error).__name__)

    def scan_devices(self):
        self._submit(self._async_scan)

    async def _async_scan(self):
        if self.is_connected or (self._scan_task and not self._scan_task.done()):
            return
        self._scan_task = asyncio.current_task()
        self._devices.clear()
        seen = {}
        self.status_changed.emit("scanning", "Looking for nearby earbuds. Keep the case open.")
        self.log_message.emit("SCAN", "Scanning for Bluetooth Low Energy advertisements.")

        def discovered(device, adv):
            self._devices[device.address] = device
            name = adv.local_name or device.name or "Unnamed device"
            info = (name, adv.rssi, is_candidate(device, adv))
            if seen.get(device.address) != info:
                seen[device.address] = info
                self.device_discovered.emit(device.address, *info)

        try:
            async with BleakScanner(detection_callback=discovered):
                await asyncio.sleep(self.SCAN_SECONDS)
            count = sum(info[2] for info in seen.values())
            message = (f"Found {count} possible earbud device(s). Select yours to connect."
                       if count else "No matching earbuds yet. Open the case or enable Show all devices.")
            self.status_changed.emit("disconnected", message)
            self.log_message.emit("SCAN", f"Found {len(seen)} BLE devices; {count} possible matches.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.status_changed.emit("error", connection_help(error))
            self.log_message.emit("ERROR", f"Scan failed: {error}")
        finally:
            self._scan_task = None
            self.scan_finished.emit()

    def connect_device(self, address):
        self._submit(lambda: self._begin_connect(address))

    async def _begin_connect(self, address, recovering=False):
        if self._connect_task and not self._connect_task.done():
            return
        if self._scan_task:
            self._scan_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scan_task
        self._target_address = address
        self._connect_task = asyncio.create_task(self._connect_flow(address, recovering))

    async def _connect_flow(self, address, recovering=False):
        attempts = 3 if recovering else 2
        try:
            for attempt in range(attempts):
                if attempt or recovering:
                    self.status_changed.emit("reconnecting", f"Reconnecting to your earbuds ({attempt + 1}/{attempts})…")
                    await asyncio.sleep(self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)])
                else:
                    self.status_changed.emit("connecting", "Connecting and checking earbud controls…")
                try:
                    await asyncio.wait_for(self._open_connection(address), timeout=self.CONNECT_TIMEOUT)
                    self.is_connected = True
                    self.connection_changed.emit(True, "Connected")
                    self.status_changed.emit("connected", "Earbud controls connected. Battery information updates automatically.")
                    self._poll_task = asyncio.create_task(self._poll_loop(self.client))
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.log_message.emit("ERROR", f"Connection attempt {attempt + 1}: {error}")
                    await self._release_client()
                    if isinstance(error, UnsupportedDeviceError) or attempt == attempts - 1:
                        message = str(error) if isinstance(error, UnsupportedDeviceError) else connection_help(error)
                        self.connection_changed.emit(False, message)
                        self.status_changed.emit("error", message)
                        return
        finally:
            self._connect_task = None

    async def _open_connection(self, address):
        self.log_message.emit("CONN", f"Connecting to {address}.")
        device = self._devices.get(address)
        if device is None:
            device = await BleakScanner.find_device_by_address(address, timeout=7.0)
            if device is None:
                raise RuntimeError("Device not found")
        kwargs = {"winrt": {"use_cached_services": False}} if sys.platform == "win32" else {}
        client = BleakClient(device, disconnected_callback=self._on_disconnected, timeout=12.0, **kwargs)
        self.client = client
        self.seq = 0
        self._decoder.reset()
        self._last_commands.clear()
        await client.connect()
        tx = client.services.get_characteristic(WRITE_CHAR_UUID)
        rx = client.services.get_characteristic(NOTIFY_CHAR_UUID)
        if (tx is None or rx is None
                or not {"write", "write-without-response"}.intersection(tx.properties)
                or not {"notify", "indicate"}.intersection(rx.properties)):
            raise UnsupportedDeviceError(
                "This device does not expose supported earbud controls. "
                "You can still use it for audio through Windows Bluetooth settings.")
        self._write_char, self._notify_char = tx, rx
        self._write_response = "write-without-response" not in tx.properties
        await client.start_notify(rx, lambda sender, data: self._on_notification(sender, data)
                                  if self.client is client else None)
        await asyncio.sleep(0.15)
        await self._send(CMD_DEVICE_INFO, bytes([INFO_TYPE_MAX_PACKET, 0]))
        if not client.is_connected:
            raise ConnectionError("Earbuds disconnected during setup")

    def _on_disconnected(self, client):
        if self.loop and self.loop.is_running() and not self._closing:
            future = asyncio.run_coroutine_threadsafe(self._handle_disconnected(client), self.loop)
            future.add_done_callback(self._report_failure)

    async def _handle_disconnected(self, client):
        if client is not self.client or not self.is_connected:
            return
        self.is_connected = False
        self.connection_changed.emit(False, "Connection lost")
        self.log_message.emit("CONN", "Earbuds disconnected unexpectedly.")
        address = self._target_address
        await self._release_client()
        if self.auto_reconnect and address and not self._closing:
            await self._begin_connect(address, recovering=True)
        else:
            self.status_changed.emit("disconnected", "Connection lost. Keep the earbuds nearby and connect again.")

    async def _poll_loop(self, client):
        try:
            while self.is_connected and self.client is client:
                await self._query_states()
                await asyncio.sleep(12.0)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.log_message.emit("ERROR", f"Telemetry update failed: {error}")
            # A failed GATT write can leave Bleak's cached connected flag stale.
            asyncio.create_task(self._handle_disconnected(client))

    async def _query_states(self):
        for info_type in (INFO_TYPE_POWER, INFO_TYPE_WORK_MODE, INFO_TYPE_SPATIAL_AUDIO):
            await self._send(CMD_DEVICE_INFO, bytes([info_type, 0]))
            await asyncio.sleep(0.15)

    async def _release_client(self):
        poll, self._poll_task = self._poll_task, None
        if poll and poll is not asyncio.current_task():
            poll.cancel()
            with suppress(asyncio.CancelledError):
                await poll
        client, self.client = self.client, None
        self.is_connected = False
        self._write_char = self._notify_char = None
        self._decoder.reset()
        for _, response in self._last_commands.values():
            if not response.done():
                response.set_result(False)
        self._last_commands.clear()
        if client:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=3.0)
            except Exception as error:
                self.log_message.emit("CONN", f"Disconnect cleanup: {error}")

    def disconnect_device(self):
        self._submit(self._async_disconnect)

    async def _async_disconnect(self):
        self._target_address = None
        connecting = self._connect_task
        if connecting and connecting is not asyncio.current_task():
            connecting.cancel()
            with suppress(asyncio.CancelledError):
                await connecting
        await self._release_client()
        self.connection_changed.emit(False, "Disconnected")
        self.status_changed.emit("disconnected", "Select your earbuds and connect when you're ready.")

    def set_auto_reconnect(self, enabled):
        self.auto_reconnect = bool(enabled)

    async def _send(self, cmd, payload):
        async with self._write_lock:
            client = self.client
            if not client or not client.is_connected or self._write_char is None:
                raise ConnectionError("Earbuds are disconnected")
            packet = make_packet(self.seq, cmd, 1, payload)
            self.seq = (self.seq + 1) & 0x0F
            await asyncio.wait_for(client.write_gatt_char(self._write_char, packet, response=self._write_response), timeout=5.0)
            self.log_message.emit("TX", packet.hex(" ").upper())

    def _command(self, operation, commands, query=None):
        session_client = self.client
        async def execute():
            async with self._command_lock:
                try:
                    if not self.is_connected or self.client is not session_client:
                        raise ConnectionError("Connect your earbuds first.")
                    confirmed = True
                    for cmd, payload in commands:
                        if self.client is not session_client:
                            raise ConnectionError("The earbud connection changed. Try again.")
                        response = asyncio.get_running_loop().create_future()
                        self._last_commands[cmd] = (operation, response)
                        try:
                            await self._send(cmd, payload)
                            if query is not None:
                                await asyncio.sleep(0.15)
                                await self._send(CMD_DEVICE_INFO, bytes([query, 0]))
                            try:
                                accepted = await asyncio.wait_for(response, timeout=self.COMMAND_RESPONSE_TIMEOUT)
                            except (TimeoutError, asyncio.TimeoutError):
                                confirmed = False
                            else:
                                if not accepted:
                                    raise ValueError("Your earbuds did not accept this setting.")
                        finally:
                            self._last_commands.pop(cmd, None)
                        await asyncio.sleep(0.1)
                    if query is not None:
                        if not commands:
                            await self._send(CMD_DEVICE_INFO, bytes([query, 0]))
                    message = "Accepted by earbuds." if commands and confirmed else "Sent; device confirmation unavailable."
                    self.command_result.emit(operation, True, message)
                except Exception as error:
                    self.command_result.emit(operation, False, str(error) or "Command failed. Try again.")
                    self.log_message.emit("ERROR", f"{operation}: {error}")
        self._submit(execute)

    def query_battery(self):
        self._command("refresh", [], query=INFO_TYPE_POWER)

    def set_beast_mode(self, enabled):
        self._command("beast", [(CMD_WORK_MODE, bytes([bool(enabled)]))], INFO_TYPE_WORK_MODE)

    def set_spatial_audio(self, enabled):
        self._command("spatial", [(CMD_SPATIAL_AUDIO, bytes([bool(enabled)]))], INFO_TYPE_SPATIAL_AUDIO)

    def set_eq_preset(self, name):
        if name in EQ_PRESETS:
            self._command("eq", [(CMD_EQ, bytes([10, 0x20]) + EQ_PRESETS[name])])

    def set_auto_shutdown(self, minutes):
        if minutes in (0, 5, 10, 30):
            self._command("sleep", [(CMD_AUTO_SHUTDOWN, bytes([minutes]))])

    def set_key_mappings(self, mappings):
        self._command("touch", [(CMD_KEY, bytes([key, 1, function])) for key, function in mappings])

    def set_key_mapping(self, key_type, function_id):
        self.set_key_mappings([(key_type, function_id)])

    def set_bluetooth_name(self, name):
        encoded = name.strip().encode("utf-8")
        if 0 < len(encoded) <= 15:
            self._command("name", [(CMD_NAME, encoded)])

    def stop_hardware_buzzer(self):
        if self.is_connected:
            self._command("buzzer", [(CMD_FIND_DEVICE, b"\x00")])

    def _on_notification(self, sender, data):
        self.log_message.emit("RX", bytes(data).hex(" ").upper())
        try:
            for cmd, kind, payload in self._decoder.feed(bytes(data)):
                if cmd == CMD_DEVICE_INFO or (cmd == CMD_NOTIFY and kind == 3):
                    for tag, value in parse_tlvs(payload):
                        self._update_info(tag, value)
                elif kind == 3:
                    # The SDK uses info IDs (1, 8, 24) for direct notifications.
                    self._update_info(cmd, payload)
                elif kind == 2 and cmd in self._last_commands:
                    # Mode command replies are acknowledgements: 0 = success.
                    # They never represent the current on/off state.
                    _, response = self._last_commands[cmd]
                    if cmd == CMD_KEY:
                        values = parse_tlvs(payload)
                        if not values or any(len(value) != 1 for _, value in values):
                            raise ValueError("Invalid gesture acknowledgement")
                        rejected = any(value[0] != 0 for _, value in values)
                    else:
                        if len(payload) != 1:
                            raise ValueError("Invalid command acknowledgement")
                        rejected = payload[0] != 0
                    if not response.done():
                        response.set_result(not rejected)
        except ValueError as error:
            self.log_message.emit("WARN", f"Ignored malformed response: {error}")

    def _update_info(self, tag, value):
        if tag == INFO_TYPE_POWER and value:
            batteries = []
            for raw in value[:3]:
                level = raw & 0x7F
                batteries.extend((level if level <= 100 else -1, bool(raw & 0x80) and level <= 100))
            while len(batteries) < 6:
                batteries.extend((-1, False))
            self.battery_updated.emit(*batteries)
        elif tag == INFO_TYPE_WORK_MODE and len(value) == 1 and value[0] in (0, 1):
            self.beast_mode_updated.emit(value[0] == 1)
        elif tag == INFO_TYPE_SPATIAL_AUDIO and len(value) == 1:
            self.spatial_audio_updated.emit(value[0] != 0)

    async def _async_shutdown(self):
        if self._scan_task:
            self._scan_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scan_task
        await self._async_disconnect()

    def shutdown(self):
        """Finish Bluetooth cleanup before joining the QThread."""
        self._closing = True
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._start_shutdown)

    def _start_shutdown(self):
        if self._shutdown_task is not None:
            return
        self._shutdown_task = asyncio.create_task(self._async_shutdown())
        def finished(task):
            try:
                task.result()
            except Exception as error:
                self.log_message.emit("ERROR", f"Shutdown cleanup: {error}")
            finally:
                self.loop.stop()
        self._shutdown_task.add_done_callback(finished)
