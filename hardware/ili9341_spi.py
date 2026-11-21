"""
Direct Linux spidev + RPi.GPIO driver for ILI9341 2.8" TFT LCD.
Bypasses Adafruit Blinka/gpiod to avoid '[Errno 16] Device or resource busy' on CE0/GPIO 8.
"""

import time
import logging
from typing import Optional
from PIL import Image

logger = logging.getLogger("easibot.ili9341_spi")

try:
    import spidev
    import RPi.GPIO as GPIO
    SPIDEV_HARDWARE_AVAILABLE = True
except (ImportError, RuntimeError):
    SPIDEV_HARDWARE_AVAILABLE = False


class ILI9341DirectSPI:
    """Direct SPI driver for ILI9341 using /dev/spidev0.0 and RPi.GPIO."""

    def __init__(
        self,
        port: int = 0,
        device: int = 0,
        dc_pin: int = 24,
        rst_pin: int = 25,
        led_pin: int = 18,
        speed_hz: int = 24000000,
        rotation: int = 90
    ):
        self.port = port
        self.device = device
        self.dc_pin = dc_pin
        self.rst_pin = rst_pin
        self.led_pin = led_pin
        self.speed_hz = speed_hz
        self.rotation = rotation

        self.width = 320 if rotation in (90, 270) else 240
        self.height = 240 if rotation in (90, 270) else 320

        # Setup GPIO for DC, RST, and LED
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.dc_pin, GPIO.OUT)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        if self.led_pin:
            GPIO.setup(self.led_pin, GPIO.OUT)
            GPIO.output(self.led_pin, GPIO.HIGH)

        # Open hardware SPI
        self.spi = spidev.SpiDev()
        self.spi.open(self.port, self.device)
        self.spi.max_speed_hz = self.speed_hz
        self.spi.mode = 0

        self.reset()
        self._init_display()
        logger.info("ILI9341DirectSPI initialized on /dev/spidev%d.%d at %d Hz", self.port, self.device, self.speed_hz)

    def reset(self):
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.01)
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.12)

    def _command(self, cmd: int):
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([cmd])

    def _data(self, val):
        GPIO.output(self.dc_pin, GPIO.HIGH)
        if isinstance(val, int):
            self.spi.writebytes([val])
        else:
            self.spi.writebytes(list(val))

    def _init_display(self):
        # Software Reset
        self._command(0x01)
        time.sleep(0.1)

        # Power control A & B
        self._command(0xCB)
        self._data([0x39, 0x2C, 0x00, 0x34, 0x02])
        self._command(0xCF)
        self._data([0x00, 0xC1, 0x30])

        # Driver Timing control
        self._command(0xE8)
        self._data([0x85, 0x00, 0x78])
        self._command(0xEA)
        self._data([0x00, 0x00])

        # Power on Sequence
        self._command(0xED)
        self._data([0x64, 0x03, 0x12, 0x81])

        # Pump ratio
        self._command(0xF7)
        self._data([0x20])

        # Power control 1 & 2
        self._command(0xC0)
        self._data([0x23])
        self._command(0xC1)
        self._data([0x10])

        # VCOM control 1 & 2
        self._command(0xC5)
        self._data([0x3E, 0x28])
        self._command(0xC7)
        self._data([0x86])

        # Memory Access Control (MADCTL) - Orientation
        # 0xE8 or 0x28 for landscape 320x240 (BGR color order)
        madctl = 0xE8 if self.rotation == 90 else (0x28 if self.rotation == 270 else 0x48)
        self._command(0x36)
        self._data([madctl])

        # Pixel Format (COLMOD) - 16-bit RGB565
        self._command(0x3A)
        self._data([0x55])

        # Frame Rate
        self._command(0xB1)
        self._data([0x00, 0x18])

        # Display Function Control
        self._command(0xB6)
        self._data([0x08, 0x82, 0x27])

        # Sleep OUT
        self._command(0x11)
        time.sleep(0.12)

        # Display ON
        self._command(0x29)
        time.sleep(0.02)

    def set_window(self, x0: int, y0: int, x1: int, y1: int):
        self._command(0x2A)  # Column address
        self._data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._command(0x2B)  # Page address
        self._data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._command(0x2C)  # Memory write

    def image(self, img: Image.Image):
        """Displays a PIL Image (320x240 RGB)."""
        w, h = img.size
        self.set_window(0, 0, w - 1, h - 1)

        # Fast RGB888 -> RGB565 conversion
        rgb_img = img.convert("RGB")
        raw = rgb_img.tobytes()

        # Build 16-bit big-endian RGB565 byte buffer
        # In python: convert in C or fast bytearray
        num_pixels = w * h
        buf = bytearray(num_pixels * 2)

        for i in range(num_pixels):
            r = raw[i * 3]
            g = raw[i * 3 + 1]
            b = raw[i * 3 + 2]
            # 5 bits R, 6 bits G, 5 bits B
            buf[i * 2] = (r & 0xF8) | (g >> 5)
            buf[i * 2 + 1] = ((g & 0x1C) << 3) | (b >> 3)

        # Transmit in 4096-byte chunks
        GPIO.output(self.dc_pin, GPIO.HIGH)
        chunk = 4096
        for offset in range(0, len(buf), chunk):
            self.spi.writebytes(buf[offset : offset + chunk])

    def close(self):
        try:
            self.spi.close()
        except Exception:
            pass
