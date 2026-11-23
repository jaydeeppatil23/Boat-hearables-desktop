"""A stereo earbud locator with explicit output selection and safe cancellation."""

import threading

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal


class EarbudsAudioRinger(QObject):
    playback_started = pyqtSignal(str)
    playback_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_playing = False
        self.thread = None
        self._stop_event = threading.Event()

    @staticmethod
    def output_devices():
        """Prefer WASAPI stereo outputs on Windows, avoiding duplicate drivers."""
        devices = sd.query_devices()
        apis = sd.query_hostapis()
        outputs = [(index, device) for index, device in enumerate(devices)
                   if device["max_output_channels"] >= 2]
        wasapi = [(index, device) for index, device in outputs
                  if "WASAPI" in apis[device["hostapi"]]["name"]]
        return [(index, device["name"]) for index, device in (wasapi or outputs)]

    def start(self, channel="both", device=None):
        self.stop()
        if self.thread and self.thread.is_alive():
            self.error_occurred.emit("The audio output is still stopping. Try again.")
            return
        if device is None or channel not in ("left", "right", "both"):
            self.error_occurred.emit("Select a stereo earbud audio output first.")
            return
        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._play_loop,
                                       args=(self._stop_event, channel, device), daemon=True)
        self.thread.start()

    def stop(self):
        self._stop_event.set()
        self.is_playing = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.6)
        if self.thread and not self.thread.is_alive():
            self.thread = None

    @staticmethod
    def _stereo_block(sample_rate, channel):
        duration, pause = 0.15, 0.15
        t = np.arange(int(sample_rate * duration)) / sample_rate
        phase = 2 * np.pi * (2000 * t + 0.5 * (1200 / duration) * t ** 2)
        envelope = np.sin(np.pi * np.linspace(0, 1, len(t))) ** 2
        tone = 0.22 * np.sin(phase) * envelope
        mono = np.concatenate((tone, np.zeros(int(sample_rate * pause))))
        silent = np.zeros_like(mono)
        left = silent if channel == "right" else mono
        right = silent if channel == "left" else mono
        return np.column_stack((left, right)).astype(np.float32)

    def _play_loop(self, stop_event, channel, device):
        try:
            info = sd.query_devices(device, "output")
            if info["max_output_channels"] < 2:
                raise ValueError("Choose a stereo output instead of a hands-free headset output.")
            sample_rate = int(info["default_samplerate"])
            sd.check_output_settings(device=device, samplerate=sample_rate, channels=2, dtype="float32")
            block = self._stereo_block(sample_rate, channel)
            with sd.OutputStream(device=device, samplerate=sample_rate, channels=2, dtype="float32") as stream:
                if stop_event.is_set():
                    return
                self.is_playing = True
                self.playback_started.emit(channel)
                for _ in range(100):
                    if stop_event.is_set():
                        break
                    stream.write(block)
        except Exception as error:
            self.error_occurred.emit(f"Couldn't play the locator sound: {error}")
        finally:
            self.is_playing = False
            self.playback_stopped.emit()
