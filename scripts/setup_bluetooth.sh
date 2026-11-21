#!/bin/bash
# ==============================================================================
# Easibot: Bluetooth Speaker & Microphone Pairing Helper Script
# Handles PipeWire / PulseAudio / BlueZ integration on Raspberry Pi OS
# ==============================================================================

set -e

echo "======================================================================"
echo " Easibot Bluetooth Speaker & Microphone Setup"
echo "======================================================================"

# Ensure bluetooth service is running
sudo systemctl start bluetooth
sudo systemctl enable bluetooth

echo "Starting Bluetooth scan for 10 seconds..."
echo "Please ensure your Bluetooth speaker is in PAIRING MODE."
echo "----------------------------------------------------------------------"

# Enable agent and power
bluetoothctl power on
bluetoothctl default-agent

# Scan for devices
timeout 10s bluetoothctl scan on || true

echo "----------------------------------------------------------------------"
echo "Scanned audio devices:"
bluetoothctl devices | grep -E "Audio|Speaker|Headset|Handsfree|Earbuds" || bluetoothctl devices

echo "----------------------------------------------------------------------"
read -p "Enter the MAC address of your Bluetooth speaker (e.g. AA:BB:CC:DD:EE:FF): " BT_MAC

if [ -z "$BT_MAC" ]; then
    echo "No MAC address entered. Exiting."
    exit 1
fi

echo "Pairing with $BT_MAC..."
bluetoothctl pair "$BT_MAC" || true

echo "Trusting $BT_MAC..."
bluetoothctl trust "$BT_MAC"

echo "Connecting to $BT_MAC..."
bluetoothctl connect "$BT_MAC"

# Wait for audio subsystem to register
sleep 3

# Configure default audio sink and source using WirePlumber / PipeWire or PulseAudio
if command -v wpctl &> /dev/null; then
    echo "Configuring PipeWire / WirePlumber default audio routing..."
    # Find ID of connected bluez sink
    BT_ID=$(wpctl status | grep -i "bluez" | grep -oE "[0-9]+" | head -n 1 || true)
    if [ -n "$BT_ID" ]; then
        wpctl set-default "$BT_ID"
        echo "Set default audio sink to WirePlumber ID: $BT_ID"
    fi
elif command -v pactl &> /dev/null; then
    echo "Configuring PulseAudio default sink..."
    PA_SINK=$(pactl list short sinks | grep -i "bluez" | awk '{print $2}' | head -n 1 || true)
    if [ -n "$PA_SINK" ]; then
        pactl set-default-sink "$PA_SINK"
        echo "Set default PulseAudio sink to: $PA_SINK"
    fi
fi

echo "Testing audio playback..."
if command -v mpg123 &> /dev/null; then
    # Play test chime
    python3 -c "
import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from core.audio_service import AudioService
svc = AudioService()
p = svc.synthesize_speech('Bluetooth audio connected successfully!', 'en')
if p: svc.play_audio(p)
" || true
fi

echo "======================================================================"
echo " Bluetooth setup complete!"
echo "======================================================================"
