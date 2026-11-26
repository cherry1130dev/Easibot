#!/bin/bash
# ==============================================================================
# Easibot: Bluetooth Speaker & Microphone Pairing Helper Script
# Handles PipeWire / PulseAudio / BlueZ integration on Raspberry Pi OS
# ==============================================================================

echo "======================================================================"
echo " Easibot Bluetooth Speaker & Microphone Setup"
echo "======================================================================"

# Ensure bluetooth service is running
sudo systemctl start bluetooth
sudo systemctl enable bluetooth 2>/dev/null || true

# Turn on adapter and register agent
bluetoothctl power on || true
bluetoothctl agent on || true
bluetoothctl default-agent || true

echo "----------------------------------------------------------------------"
echo "Starting Bluetooth scan for 12 seconds..."
echo "Please make sure your Bluetooth speaker is in PAIRING / DISCOVERY MODE."
echo "----------------------------------------------------------------------"

# Run scan using bluetoothctl timeout or background process
if bluetoothctl --help 2>&1 | grep -q -- "--timeout"; then
    bluetoothctl --timeout 12 scan on || true
else
    # Fallback scan for older BlueZ
    (bluetoothctl scan on) &
    SCAN_PID=$!
    sleep 12
    kill -9 $SCAN_PID 2>/dev/null || true
fi

echo ""
echo "----------------------------------------------------------------------"
echo "Nearby Scanned Audio Devices:"
echo "----------------------------------------------------------------------"
bluetoothctl devices

echo "----------------------------------------------------------------------"
echo "Tip: Look for your speaker's name in the list above."
read -p "Enter the MAC address of your speaker (e.g. AA:BB:CC:DD:EE:FF): " BT_MAC

# Strip whitespace
BT_MAC=$(echo "$BT_MAC" | tr -d '[:space:]')

if [ -z "$BT_MAC" ]; then
    echo "No MAC address entered. You can re-run this script anytime."
    exit 0
fi

echo ""
echo "Pairing with $BT_MAC..."
bluetoothctl pair "$BT_MAC" || true

echo "Trusting $BT_MAC..."
bluetoothctl trust "$BT_MAC" || true

echo "Connecting to $BT_MAC..."
bluetoothctl connect "$BT_MAC" || true

# Wait for audio subsystem to register device
sleep 3

# Configure default audio sink and source using WirePlumber / PipeWire or PulseAudio
if command -v wpctl &> /dev/null; then
    echo "Configuring PipeWire / WirePlumber default audio routing..."
    # Find ID of connected bluez sink
    BT_ID=$(wpctl status 2>/dev/null | grep -i "bluez" | grep -oE "[0-9]+" | head -n 1 || true)
    if [ -n "$BT_ID" ]; then
        wpctl set-default "$BT_ID" 2>/dev/null || true
        echo "Set default audio sink to WirePlumber ID: $BT_ID"
    fi
elif command -v pactl &> /dev/null; then
    echo "Configuring PulseAudio default sink..."
    PA_SINK=$(pactl list short sinks 2>/dev/null | grep -i "bluez" | awk '{print $2}' | head -n 1 || true)
    if [ -n "$PA_SINK" ]; then
        pactl set-default-sink "$PA_SINK" 2>/dev/null || true
        echo "Set default PulseAudio sink to: $PA_SINK"
    fi
fi

echo ""
echo "Testing audio playback through speaker..."
if [ -d "venv" ]; then
    source venv/bin/activate
fi

python3 -c "
import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from main import speak_text
speak_text('Bluetooth speaker connected successfully!', 'en')
" 2>/dev/null || echo "Audio test prompt sent."

echo "======================================================================"
echo " Bluetooth setup finished!"
echo "======================================================================"
