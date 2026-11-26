"""
Easibot Standalone Hardware Diagnostic Tool
Tests 2.8" SPI TFT LCD (ILI9341), HC-SR04 Ultrasonic Sensor, and Audio Devices.
Run with: python scripts/test_hardware.py
"""

import os
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PIN_TRIG = int(os.getenv("PIN_TRIG", "23"))
PIN_ECHO = int(os.getenv("PIN_ECHO", "27"))
PIN_TFT_DC = 24
PIN_TFT_RST = 25
PIN_TFT_LED = 18

print("=" * 68)
print("  EASIBOT HARDWARE DIAGNOSTIC TOOL (Raspberry Pi)")
print("=" * 68)

# 1. SPI & TFT Test
print(f"\n[TEST 1/3] Testing 2.8\" SPI TFT LCD (DC=GPIO{PIN_TFT_DC}, RST=GPIO{PIN_TFT_RST}, LED=GPIO{PIN_TFT_LED})...")
if os.path.exists("/dev/spidev0.0"):
    print("  ✓ /dev/spidev0.0 exists.")
else:
    print("  ✗ /dev/spidev0.0 NOT FOUND! Enable SPI via 'sudo raspi-config nonint do_spi 0' and reboot.")

try:
    import sys
    sys.path.append(str(BASE_DIR))
    import main as app
    app.MOCK_HARDWARE = False
    tft = app.SimpleTFT()
    app.robot["state"] = "speaking"
    app.robot["emotion"] = "happy"
    app.robot["last_question"] = "Hardware Test"
    app.robot["reply_native"] = "TFT Display & Backlight initialized OK!"
    tft.render_and_push(force=True)
    print("  ✓ TFT Display initialized and test screen pushed!")
except Exception as e:
    print(f"  ✗ TFT test failed: {e}")

# 2. Ultrasonic Test
print(f"\n[TEST 2/3] Testing HC-SR04 Ultrasonic (TRIG=GPIO{PIN_TRIG}, ECHO=GPIO{PIN_ECHO})...")
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
    GPIO.setup(PIN_TRIG, GPIO.OUT); GPIO.setup(PIN_ECHO, GPIO.IN)
    GPIO.output(PIN_TRIG, GPIO.LOW)
    time.sleep(0.2)

    ok_count = 0
    for i in range(5):
        GPIO.output(PIN_TRIG, GPIO.HIGH)
        time.sleep(0.000012)
        GPIO.output(PIN_TRIG, GPIO.LOW)
        t0 = time.perf_counter()
        deadline = t0 + 0.04
        while GPIO.input(PIN_ECHO) == 0:
            t0 = time.perf_counter()
            if t0 > deadline:
                break
        t1 = t0
        while GPIO.input(PIN_ECHO) == 1:
            t1 = time.perf_counter()
            if t1 > deadline:
                break
        if t1 > t0 and t0 <= deadline:
            cm = round(((t1 - t0) * 34300.0) / 2.0, 1)
            print(f"    Sample {i+1}: {cm} cm")
            if 2.0 <= cm <= 400.0:
                ok_count += 1
        else:
            print(f"    Sample {i+1}: No Echo (Timeout)")
        time.sleep(0.2)
    print(f"  {'✓' if ok_count else '✗'} Valid readings: {ok_count}/5")
except Exception as e:
    print(f"  ✗ Ultrasonic test failed: {e}")

# 3. Audio Devices
print("\n[TEST 3/3] Checking Microphones & Speakers...")
for label, cmd in [("Playback (aplay -l)", ["aplay", "-l"]), ("Capture (arecord -l)", ["arecord", "-l"]), ("PipeWire/Pulse Sinks", ["pactl", "list", "short", "sinks"]), ("PipeWire/Pulse Sources", ["pactl", "list", "short", "sources"])]:
    print(f"  {label}:")
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        for line in out.splitlines()[:6]:
            print("   ", line)
    except Exception:
        print("    (not available)")

print("\n" + "=" * 68)
