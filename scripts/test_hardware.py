"""
Easibot Hardware Diagnostic & Pinout Verification Tool
Tests SPI TFT LCD (ILI9341), HC-SR04 Ultrasonic Sensor, and Microphone/Speaker on Raspberry Pi.
Run with: python scripts/test_hardware.py
"""

import sys
import os
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

print("=" * 70)
print("  EASIBOT HARDWARE DIAGNOSTIC TOOL (Raspberry Pi Zero 2 W)")
print("=" * 70)

# ==============================================================================
# TEST 1: TFT Display & Backlight (ILI9341 - KMRTM28028-SPI)
# ==============================================================================
print("\n[TEST 1/3] Testing 2.8\" SPI TFT LCD & Backlight...")
print(f"  Pins configured: CS=GPIO{config.PIN_TFT_CS}, DC=GPIO{config.PIN_TFT_DC}, RST=GPIO{config.PIN_TFT_RST}, LED=GPIO{config.PIN_TFT_BACKLIGHT}")

# Step 1A: Check SPI Device
if os.path.exists("/dev/spidev0.0"):
    print("  ✓ /dev/spidev0.0 exists (SPI interface is enabled).")
else:
    print("  ✗ /dev/spidev0.0 NOT FOUND! Run 'sudo raspi-config nonint do_spi 0' and reboot.")

# Step 1B: Turn on Backlight via RPi.GPIO
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(config.PIN_TFT_BACKLIGHT, GPIO.OUT)
    GPIO.output(config.PIN_TFT_BACKLIGHT, GPIO.HIGH)
    print(f"  ✓ Backlight GPIO {config.PIN_TFT_BACKLIGHT} set to HIGH (Screen should be lit).")
except Exception as e:
    print(f"  ⚠ Could not set Backlight GPIO: {e}")

# Step 1C: Initialize Adafruit ILI9341 and draw test screen
try:
    import board
    import digitalio
    from adafruit_rgb_display import ili9341
    from PIL import Image, ImageDraw, ImageFont

    spi = board.SPI()
    cs_pin = digitalio.DigitalInOut(getattr(board, f"D{config.PIN_TFT_CS}"))
    dc_pin = digitalio.DigitalInOut(getattr(board, f"D{config.PIN_TFT_DC}"))
    rst_pin = digitalio.DigitalInOut(getattr(board, f"D{config.PIN_TFT_RST}"))

    disp = ili9341.ILI9341(
        spi,
        cs=cs_pin,
        dc=dc_pin,
        rst=rst_pin,
        width=240,
        height=320,
        rotation=90,
        baudrate=config.SPI_BAUDRATE
    )

    # Draw vibrant test image
    test_img = Image.new("RGB", (320, 240), (12, 16, 28))
    draw = ImageDraw.Draw(test_img)
    # Header bar
    draw.rectangle([(0, 0), (320, 35)], fill=(0, 212, 255))
    draw.text((15, 8), "EASIBOT HARDWARE TEST", fill=(0, 0, 0))
    # Eye test circles
    draw.rounded_rectangle([(70, 70), (130, 130)], radius=15, fill=(0, 212, 255))
    draw.rounded_rectangle([(190, 70), (250, 130)], radius=15, fill=(0, 212, 255))
    # Status card
    draw.rounded_rectangle([(20, 160), (300, 220)], radius=8, fill=(22, 28, 44), outline=(45, 55, 72))
    draw.text((35, 175), "TFT DISPLAY INITIALIZED OK!", fill=(72, 239, 128))
    draw.text((35, 195), "ILI9341 SPI Communications Active", fill=(160, 174, 192))

    disp.image(test_img)
    print("  ✓ TFT Display initialized and test image pushed to ILI9341!")
except Exception as e:
    print(f"  ✗ TFT Display initialization failed: {e}")
    print("    Check SPI wiring: MOSI->GPIO10 (Pin 19), SCK->GPIO11 (Pin 23), CS->GPIO8 (Pin 24), DC->GPIO24 (Pin 18), RST->GPIO25 (Pin 22), VCC->3.3V, LED->GPIO18 or 3.3V")

# ==============================================================================
# TEST 2: Ultrasonic Sensor (HC-SR04)
# ==============================================================================
print("\n[TEST 2/3] Testing HC-SR04 Ultrasonic Distance Sensor...")
print(f"  Pins configured: TRIG=GPIO{config.PIN_TRIG} (Pin 16), ECHO=GPIO{config.PIN_ECHO} (Pin 13 via voltage divider)")

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(config.PIN_TRIG, GPIO.OUT)
    GPIO.setup(config.PIN_ECHO, GPIO.IN)
    GPIO.output(config.PIN_TRIG, False)
    time.sleep(0.2)

    print("  Sampling 5 distance readings:")
    successful_readings = 0
    for i in range(5):
        # 10us trigger pulse
        GPIO.output(config.PIN_TRIG, True)
        time.sleep(0.00001)
        GPIO.output(config.PIN_TRIG, False)

        pulse_start = time.time()
        pulse_end = time.time()
        timeout = pulse_start + 0.05  # 50ms timeout

        # Wait for echo to go HIGH
        while GPIO.input(config.PIN_ECHO) == 0:
            pulse_start = time.time()
            if pulse_start > timeout:
                break

        # Wait for echo to go LOW
        while GPIO.input(config.PIN_ECHO) == 1:
            pulse_end = time.time()
            if pulse_end > timeout:
                break

        if pulse_end > pulse_start and (pulse_start <= timeout):
            duration = pulse_end - pulse_start
            distance_cm = round((duration * 34300) / 2.0, 1)
            if 2.0 <= distance_cm <= 400.0:
                print(f"    Sample {i+1}: {distance_cm} cm (Echo duration: {duration*1000:.2f} ms)")
                successful_readings += 1
            else:
                print(f"    Sample {i+1}: Out of range ({distance_cm} cm)")
        else:
            print(f"    Sample {i+1}: No Echo pulse received (Timeout)")

        time.sleep(0.2)

    if successful_readings > 0:
        print(f"  ✓ Ultrasonic Sensor working ({successful_readings}/5 valid readings).")
    else:
        print("  ✗ Ultrasonic Sensor received NO ECHO!")
        print("    WIRING CHECKLIST FOR HC-SR04:")
        print("    1. VCC MUST be connected to 5V (Pin 2 or 4). HC-SR04 will NOT work on 3.3V!")
        print("    2. GND MUST be connected to Pi Ground (Pin 6, 9, or 14).")
        print("    3. TRIG -> GPIO 23 (Pin 16).")
        print("    4. ECHO -> 1k ohm resistor -> GPIO 27 (Pin 13) and 2k ohm resistor to GND.")
except Exception as e:
    print(f"  ✗ Ultrasonic test error: {e}")

# ==============================================================================
# TEST 3: Audio Devices & Microphone
# ==============================================================================
print("\n[TEST 3/3] Checking Microphone & Speaker Devices...")

# Check ALSA playback & capture devices
import subprocess

print("  Playback Sinks (Speakers):")
try:
    res = subprocess.run(["aplay", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in res.stdout.strip().split("\n")[:4]:
        print("   ", line)
except Exception:
    pass

print("\n  Capture Sources (Microphones):")
has_mic = False
try:
    res = subprocess.run(["arecord", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if "card" in res.stdout:
        print("    ✓ Detected Hardware Recording Device(s):")
        for line in res.stdout.strip().split("\n"):
            print("     ", line)
        has_mic = True
    else:
        print("    ⚠ NO HARDWARE ALSA MICROPHONE DETECTED ('arecord -l' is empty).")
except Exception:
    pass

# Check PipeWire / PulseAudio sources
try:
    res = subprocess.run(["pactl", "list", "short", "sources"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.stdout.strip():
        print("    PipeWire/PulseAudio Audio Sources:")
        for line in res.stdout.strip().split("\n"):
            print("     ", line)
            if "bluez" in line or "usb" in line:
                has_mic = True
except Exception:
    pass

if not has_mic:
    print("\n  [IMPORTANT NOTE ABOUT MICROPHONE ON RASPBERRY PI ZERO 2 W]:")
    print("  - The Raspberry Pi Zero 2 W has NO ONBOARD MICROPHONE.")
    print("  - Most portable Bluetooth speakers (like Mini boost 4) only provide audio OUTPUT (A2DP).")
    print("  - To give voice queries directly to the robot:")
    print("    1. Plug a standard mini USB microphone into the Pi Zero's USB OTG port, OR")
    print("    2. Use the Web Dashboard at http://10.133.141.91:5000 from your phone/laptop to type or send queries!")

print("\n" + "=" * 70)
print("  DIAGNOSTIC COMPLETE")
print("=" * 70)
