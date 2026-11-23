# ⚡ boAt Airdopes Control Hub (Windows)

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com)
[![Protocol](https://img.shields.io/badge/Protocol-BLE%20GATT%20%2F%20SPP-0082FC?style=for-the-badge&logo=bluetooth&logoColor=white)](https://bluetooth.com)
[![License](https://img.shields.io/badge/License-GPLv3-red?style=for-the-badge)](LICENSE)

**A modern, minimalist Windows desktop companion and reverse-engineered BLE controller for boAt TWS earbuds.**

*Brings mobile-exclusive companion features—real-time battery telemetry, BEAST™ low-latency gaming mode, 3D spatial audio, 10-band DSP sound profiles, and independent bud locators—natively to your PC.*

</div>

---

## 🎯 Background & Motivation

Official companion apps (such as the *boAt Hearables* app) are exclusively built for Android and iOS. When connecting earbuds to a Windows PC:
* **No independent battery meters:** Windows only shows an aggregate percentage (often delayed or missing case battery level).
* **No BEAST™ Mode toggle:** Gamers are stuck with high default audio latency (~200ms) with no way to enable 55ms low-latency mode without switching back to their phone.
* **No EQ or Spatial Audio control:** Equalizer curves and 3D soundstage toggles cannot be adjusted from the desktop.

This project solves this through **clean-room protocol reverse engineering** of the vendor BLE GATT communication stack, providing a standalone native Windows desktop application with zero cloud dependence.

---

## ✨ Features

* 🔋 **Real-Time Battery Telemetry:** Individual percentage levels and live charging indicators (`⚡`) for **Left Earbud**, **Right Earbud**, and the **Charging Case**.
* 🚀 **BEAST™ Mode Toggle:** Switch between standard and gaming modes, with device-confirmed state. Latency depends on the earbud model.
* 🌐 **3D Spatial Audio:** Toggle hardware DSP spatial expansion for wider, more immersive soundstages.
* 🎚️ **DSP Sound Profiles:** Switch between tuned hardware equalizer curves (*Signature, Bass Boost, Balanced, Pop, Rock, Vocal*) applied directly into the earbud's DSP.
* 🔔 **Acoustic Earbud Locator:** Plays a quieter 2.0–3.2 kHz chirp on an explicitly selected Windows stereo output, panned to **Left**, **Right**, or **Both Buds**. Includes stop control and a 30-second limit.
* ✋ **Touch Gesture Remapper:** Reconfigure single tap, double tap, triple tap, and long press gestures to custom actions (*Play/Pause, Track Skip, Volume, Gaming Mode, Assistant*).
* ⏱️ **Auto-Shutdown Sleep Timer:** Configure custom idle auto power-off thresholds (5m, 10m, 30m, or disabled).
* 🛠️ **Connection Diagnostics:** Timestamped, bounded Bluetooth logs with copy and clear controls.
* 🖥️ **Desktop Controls:** Compact device panel, a single battery row, mode switches, and separate dialogs for discovery, finder, and settings. Supports keyboard controls and scrolling in smaller windows.
* 🔄 **Connection Recovery:** Live discovery, remembered device selection, bounded retries, optional reconnection after a dropped connection, and clean shutdown.

---

## 🔬 Protocol & Reverse Engineering Specifications

The communication protocol was reverse-engineered by dissecting the Bluetrum Technology SDK inside the companion APK.

### 1. Bluetooth Architecture
* **Primary Control Channel:** Bluetooth Low Energy (BLE) GATT
  * **Service UUID:** `0000fdb3-0000-1000-8000-00805f9b34fb`
  * **Write Characteristic (TX):** `0000ff17-0000-1000-8000-00805f9b34fb` (Write Without Response)
  * **Notify Characteristic (RX):** `0000ff18-0000-1000-8000-00805f9b34fb` (Notify / Read)
* **Research only:** Bluetooth Classic RFCOMM / SPP (Port 1, UUID `00001101-...`). The desktop app currently implements the BLE control channel; it does not provide an SPP fallback.

### 2. Packet Framing Format
All commands follow a 5-byte header followed by a variable-length TLV payload:

| Byte Index | Field | Description |
|:---:|:---|:---|
| `0` | **Sequence Number** | Cyclic frame sequence (`0x00` – `0x0F`) |
| `1` | **Command ID** | Target operation opcode |
| `2` | **Command Type** | `0x01` = Request, `0x02` = Response, `0x03` = Notification |
| `3` | **Fragmentation** | `((Total - 1) << 4) \| (Index & 0x0F)` (`0x00` for single packet) |
| `4` | **Payload Length** | Byte count of subsequent payload ($N$) |
| `5 .. 5+N` | **Payload (TLV)** | Parameter Type, Length, and Value |

The decoder handles multiple frames per notification and ordered fragments with a sequence number for each frame. Device-info replies (`0x27`) and bundled notifications (`0x28`) contain TLVs; direct notifications use the info ID as the command. Setting replies acknowledge acceptance (`0x00` = success) and are not on/off state values. Mode changes are followed by a state query.

### 3. Decoded Command Map

| Opcode | Name | Payload Example | Description |
|:---:|:---|:---|:---|
| `0x27` | `CMD_DEVICE_INFO` | `[0x01, 0x00]` | Query Battery Telemetry |
| `0x27` | `CMD_DEVICE_INFO` | `[0x08, 0x00]` | Query BEAST Mode Status |
| `0x27` | `CMD_DEVICE_INFO` | `[0x18, 0x00]` | Query Spatial Audio Status |
| `0x25` | `CMD_WORK_MODE` | `[0x01]` / `[0x00]` | Enable / Disable BEAST™ Low Latency |
| `0x32` | `CMD_SPATIAL_AUDIO`| `[0x01]` / `[0x00]` | Enable / Disable 3D Spatial Audio |
| `0x20` | `CMD_EQ` | `[10, 0x20] + 10-byte gains` | Write 10-band signed DSP gains |
| `0x22` | `CMD_KEY` | `[KeyType, 0x01, FuncID]` | Remap earbud touch gesture |
| `0x23` | `CMD_AUTO_SHUTDOWN`| `[Minutes]` | Set idle sleep timer |
| `0x2A` | `CMD_FIND_DEVICE` | `[0x01]` / `[0x00]` | Hardware locator beep trigger / cancel |

#### Battery Telemetry Response Format (`0x27` / Type `0x01`):
The device responds with 3 consecutive bytes representing `[Left, Right, Case]`:
* **Bits 0–6 (`byte & 0x7F`):** Remaining battery percentage (`0`–`100%`).
* **Bit 7 (`byte & 0x80`):** Charging state flag (`1` = Charging, `0` = Discharging).

Some devices omit battery components. Missing fields and values outside `0`–`100` are displayed as unavailable rather than as a valid percentage.

---

## 🎧 Supported Devices

Tested and confirmed on:
* **boAt Airdopes Plus 222**

Other models may work when they expose the same Bluetrum control characteristics and protocol. These models still require individual hardware verification:
* boAt Airdopes Plus 221 / 223 / 224
* boAt Airdopes Plus Neo / Wave / Aura
* boAt Airdopes Plus Spark ANC / 421 ANC / 422 ANC / 423 ANC
* boAt Rockerz 351 ANC

Discovery uses case-insensitive names, service advertisements, and the Bluetrum manufacturer ID. These are **possible-match hints**, not proof of support. On connection, the app validates the control write and notification characteristics and selects the supported GATT write mode. Classic-only earbuds and devices using another vendor protocol cannot use these controls. Battery fields and sound features also vary by model; missing data is shown as unavailable.

---

## 📁 Repository Structure

```
boat hearables desktop/
├── main.py                   # Application entry point
├── boat_controller_app.py    # Device controls, dialogs & user actions
├── ble_worker.py             # Async discovery, GATT validation & recovery
├── ui_components.py          # Shared theme, battery readouts & mode switches
├── assets/                   # Small SVG control indicators
├── protocol.py               # Packet framing, fragment decoding & telemetry helpers
├── audio_ringer.py           # Output-selected stereo locator with cancellation
├── tests/                    # Focused protocol, connection, audio & UI regressions
├── run_boat_controller.bat   # Windows one-click launcher
├── requirements.txt          # Python dependencies
├── LICENSE                   # GNU GPLv3 License
└── README.md                 # Project documentation
```

---

## 🚀 Getting Started

### Prerequisites
* Windows 10 or Windows 11 (with Bluetooth 4.0+ hardware).
* Python 3.10 or higher.

### Installation

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/jaydeeppatil23/boat-hearables-desktop.git
   cd boat-hearables-desktop
   ```

2. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Launch the app:**
   * Double-click **`run_boat_controller.bat`**
   * Or run via terminal:
     ```powershell
     python main.py
     ```

4. **Connect:**
   * Turn on Windows Bluetooth and pair your earbuds in Windows Settings for music and calls.
   * Open the case or take your earbuds out. The app scans automatically in the **Bluetooth devices** dialog; use **Scan again** to refresh.
   * Select your earbuds. **Possible match** identifies a discovery hint; support is checked when connecting.
   * Enable **Show other Bluetooth LE devices** if your earbuds advertise with another name.
   * Click **Connect**. The chooser closes when connected and opens the device controls. Use **Devices** to return to the chooser or disconnect.
   * Choose an equalizer profile and click **Apply**. The idle power-off timer is under **Settings**. Mode switches wait for a state update; unconfirmed changes are reported rather than shown as successful.

### Connection and finder tips

* Audio and device controls use separate connections. A BLE control connection does not select or route Windows audio.
* If connecting fails, keep the earbuds awake and nearby, close the phone companion app, and scan again. **Settings** contains **Connection help** for setup guidance and **Diagnostics** for the underlying error.
* **Reconnect after connection loss**, under **Settings**, is enabled by default and can be turned off. Retries are bounded and can be cancelled; the app does not automatically connect at startup.
* Open **Find earbuds** and select the **stereo output belonging to your earbuds**. Remove the earbuds before playing. Left/right targeting requires stereo audio and may not work in hands-free or mono modes. The finder can work independently of the BLE control connection. Closing the finder stops its sound.
* Press **Ctrl+R** to scan when available and **Esc** to stop the locator sound.

### Focused validation

Run the hardware-independent regression checks:

```powershell
python -B -m unittest discover -s tests -v
```

These checks simulate Bluetooth devices and audio streams and include offscreen UI checks. They do not establish compatibility with untested physical models.

---

## ⚖️ Disclaimer

This is an unofficial, independent open-source project developed for interoperability and personal use under clean-room protocol analysis principles. 

All product names, logos, and brands (including **boAt**, **Airdopes**, and **BEAST**) are property of their respective owners (Imagine Marketing Limited / Bluetrum Technology). Their use here is strictly for identification and compatibility documentation purposes.

---

## 📜 License

Distributed under the **GNU General Public License v3.0**. See [`LICENSE`](LICENSE) for details.
