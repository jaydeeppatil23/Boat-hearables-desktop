"""
Bluetrum BLE Protocol Definitions & Packet Helpers for boAt Earbuds.
"""

# BLE Service & Characteristic UUIDs
BLUETRUM_SERVICE_UUID = "0000fdb3-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID       = "0000ff17-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID      = "0000ff18-0000-1000-8000-00805f9b34fb"

# Bluetrum Command Opcodes
CMD_EQ            = 0x20  # Sound Equalizer
CMD_KEY           = 0x22  # Touch Gesture Mapping
CMD_AUTO_SHUTDOWN = 0x23  # Sleep / Idle Timer
CMD_WORK_MODE     = 0x25  # BEAST / Low Latency Mode
CMD_DEVICE_INFO   = 0x27  # Device Info & Telemetry Query
CMD_FIND_DEVICE   = 0x2A  # Hardware Locator Buzzer
CMD_NAME          = 0x2D  # NVRAM Device Renaming
CMD_SPATIAL_AUDIO = 0x32  # Spatial Audio / 3D Sound

# Device Info Query TLV Types
INFO_TYPE_POWER         = 0x01  # Battery status (Left, Right, Case)
INFO_TYPE_WORK_MODE     = 0x08  # Work mode (BEAST Mode status)
INFO_TYPE_SPATIAL_AUDIO = 0x18  # Spatial audio status (24 decimal)
INFO_TYPE_MAX_PACKET    = 0xFF  # MTU Handshake (-1 signed byte)

# 10-Band EQ Presets
EQ_PRESETS = {
    "Signature": bytes([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    "Bass Boost": bytes([(b + 256) % 256 for b in [4, 4, 3, 1, 0, 0, 0, 1, 3, 4]]),
    "Balanced":   bytes([(b + 256) % 256 for b in [2, 1, 0, 0, 0, 0, 0, 0, 1, 2]]),
    "Pop":        bytes([(b + 256) % 256 for b in [1, 2, 3, 3, 2, 0, 1, 2, 3, 3]]),
    "Rock":       bytes([(b + 256) % 256 for b in [4, 2, 1, 0, -1, 0, 1, 2, 3, 4]]),
    "Vocal":      bytes([(b + 256) % 256 for b in [-2, -1, 1, 3, 4, 4, 3, 1, 0, -1]]),
}

# Touch Gesture Remapping Definitions
KEY_FUNCTIONS = {
    "None / Disabled": 0,
    "Voice Assistant": 2,
    "Previous Track": 3,
    "Next Track": 4,
    "Volume Up": 5,
    "Volume Down": 6,
    "Play / Pause": 7,
    "BEAST Gaming Mode": 8,
    "ANC Mode Toggle": 9,
}

KEY_TYPES = {
    "Left Single Tap": 1,
    "Right Single Tap": 2,
    "Left Double Tap": 3,
    "Right Double Tap": 4,
    "Left Triple Tap": 5,
    "Right Triple Tap": 6,
    "Left Long Press": 7,
    "Right Long Press": 8,
}


def make_packet(seq: int, cmd: int, cmd_type: int, payload: bytes) -> bytes:
    """
    Constructs a Bluetrum framed packet.
    Format: [Seq & 0x0F, Command ID, Command Type, FragByte (0x00), Payload Length] + Payload
    """
    s = seq & 0x0F
    return bytes([s, cmd, cmd_type, 0x00, len(payload)]) + payload
