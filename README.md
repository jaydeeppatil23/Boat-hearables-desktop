# boAt Airdopes Windows Desktop Hub

A modern, minimalist desktop controller and reverse-engineered Bluetooth protocol implementation for **supported boAt audio gear** (and compatible **Bluetrum AB32**-based TWS earbuds).

---

## 🎧 Features

* **Minimalist Apple/Nothing-inspired UI:** Clean dark aesthetic with rounded cards and zero visual clutter.
* **Live Battery Telemetry:** Real-time percentage & charging status for Left Bud, Right Bud, and Case.
* **BEAST™ Mode Toggle:** One-click switch for 55ms low latency gaming mode.
* **Spatial Audio (3D Soundstage):** Direct DSP 3D audio toggle.
* **Equalizer Presets:** DSP sound profiles (Signature, Bass Boost, Balanced, Pop, Rock, Vocal).
* **Earbud Locator / Ringer:** Pulsing acoustic chirp panned to Left, Right, or Both buds with instant stop.
* **Touch Controls Remapper:** Rebind single, double, triple taps, and long presses to custom media actions.
* **Idle Sleep Timer:** Configure auto power-off interval.
* **Protocol Log Drawer:** Collapsible live packet sniffer for monitoring raw Bluetooth communication.

---

## 📁 Project Structure

```
boat hearables desktop/
├── main.py                   # Application entry point
├── boat_controller_app.py     # Main GUI layout & Bleak async integration
├── protocol.py               # Bluetrum BLE protocol definitions & packet encoders
├── audio_ringer.py           # Stereo-panned locating audio synthesizer
├── run_boat_controller.bat   # Windows one-click launcher
├── requirements.txt          # Python dependencies
├── README.md                 # Project documentation
└── research/                 # Decompiled APK sources, DEX dumps & test scripts
```

---

## 🚀 Quick Start

1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
2. Launch the app:
   * Double-click `run_boat_controller.bat`
   * Or run `python main.py`
3. Click **Scan**, select your earbuds (for ex. `★ Plus 222_BLE`), and enjoy!
