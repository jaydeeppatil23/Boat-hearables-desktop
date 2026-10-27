"""
Audio Ringer Module for boAt Earbuds
Plays pulsing locating chirp tones panned to Left, Right, or Both channels.
"""

import threading
import time
import numpy as np
import sounddevice as sd

class EarbudsAudioRinger:
    def __init__(self):
        self.is_playing = False
        self.thread = None
        self.channel_mode = "both" # "left", "right", "both"
        self.sample_rate = 44100

    def start(self, channel: str = "both"):
        self.stop()
        self.channel_mode = channel.lower()
        self.is_playing = True
        self.thread = threading.Thread(target=self._play_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.is_playing = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        self.thread = None

    def _play_loop(self):
        # Generate 2.5kHz chirping pulses (pleasant locating beep)
        duration = 0.15 # pulse duration
        pause = 0.15    # silence between pulses
        t = np.linspace(0, duration, int(self.sample_rate * duration), False)
        
        # Chirp sweep from 2000Hz to 3200Hz
        freq = np.linspace(2000, 3200, len(t))
        tone = 0.5 * np.sin(2 * np.pi * freq * t)
        # Apply smooth fade envelope
        envelope = np.sin(np.pi * np.linspace(0, 1, len(t)))
        tone = tone * envelope

        silence = np.zeros(int(self.sample_rate * pause))

        if self.channel_mode == "left":
            left_buf = np.concatenate([tone, silence])
            right_buf = np.zeros_like(left_buf)
        elif self.channel_mode == "right":
            right_buf = np.concatenate([tone, silence])
            left_buf = np.zeros_like(right_buf)
        else: # both
            mono = np.concatenate([tone, silence])
            left_buf = mono
            right_buf = mono

        stereo_block = np.column_stack((left_buf, right_buf)).astype(np.float32)

        try:
            with sd.OutputStream(samplerate=self.sample_rate, channels=2, dtype='float32') as stream:
                while self.is_playing:
                    stream.write(stereo_block)
        except Exception as e:
            print("Audio ring playback error:", e)
