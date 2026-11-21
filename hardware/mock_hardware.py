"""
Mock Hardware Layer for Laptop / Development Environment.
Simulates the ILI9341 2.8" SPI TFT LCD (with live image generation and web preview)
and the HC-SR04 Ultrasonic Distance Sensor.
"""

import time
import logging
import threading
from io import BytesIO
from pathlib import Path
from typing import Optional, Callable

from PIL import Image, ImageDraw

import config
from core.state_manager import RobotState, Emotion

logger = logging.getLogger("easibot.mock_hardware")


class MockTFTDisplay:
    """Simulated 2.8-inch ILI9341 Display (320x240 landscape)."""

    def __init__(self, painter=None):
        self.width = config.TFT_WIDTH
        self.height = config.TFT_HEIGHT
        self.painter = painter
        self.preview_path = Path(config.BASE_DIR) / "web" / "static" / "img" / "tft_preview.png"
        self.preview_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_image: Optional[Image.Image] = None
        self._last_save_time = 0.0
        self._lock = threading.Lock()
        logger.info("MockTFTDisplay initialized (320x240 landscape preview mode).")

    def initialize(self) -> bool:
        logger.info("MockTFTDisplay ready. Live screen preview will be saved to %s", self.preview_path)
        return True

    def display_image(self, img: Image.Image):
        """Accepts a rendered PIL Image and updates the live preview."""
        with self._lock:
            self.current_image = img
            now = time.time()
            # Throttle disk writes to ~10 FPS to save laptop SSD / CPU
            if now - self._last_save_time >= 0.1:
                try:
                    img.save(str(self.preview_path), format="PNG")
                    self._last_save_time = now
                except Exception as e:
                    logger.debug("Failed to write mock display preview: %s", e)

    def get_preview_bytes(self, format: str = "JPEG") -> bytes:
        """Returns binary bytes of the current display frame for HTTP streaming."""
        with self._lock:
            if self.current_image:
                buf = BytesIO()
                self.current_image.save(buf, format=format)
                return buf.getvalue()
            # Return blank image if none rendered yet
            blank = Image.new("RGB", (self.width, self.height), config.COLOR_BG)
            buf = BytesIO()
            blank.save(buf, format=format)
            return buf.getvalue()

    def clear(self):
        blank = Image.new("RGB", (self.width, self.height), config.COLOR_BG)
        self.display_image(blank)

    def close(self):
        logger.info("MockTFTDisplay closed.")


class MockUltrasonic:
    """Simulated HC-SR04 Proximity Sensor."""

    def __init__(self, on_wake_callback: Optional[Callable[[], None]] = None):
        self.on_wake_callback = on_wake_callback
        self.current_distance: float = 120.0  # Default: user is 1.2m away
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_wake_time = 0.0

    def start(self):
        self.is_running = True
        self._thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._thread.start()
        logger.info("MockUltrasonic sensor loop started.")

    def stop(self):
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info("MockUltrasonic sensor stopped.")

    def get_distance(self) -> float:
        with self._lock:
            return self.current_distance

    def set_distance(self, distance_cm: float):
        """Allows test code or web dashboard to manually set distance."""
        with self._lock:
            self.current_distance = max(2.0, min(400.0, float(distance_cm)))
            logger.info("MockUltrasonic distance manually set to %.1f cm", self.current_distance)
            self._check_wake_threshold()

    def trigger_proximity_approach(self, distance_cm: float = 40.0):
        """Simulates an approaching person within wake threshold."""
        self.set_distance(distance_cm)

    def _check_wake_threshold(self):
        if self.current_distance <= config.WAKE_DISTANCE_CM:
            now = time.time()
            if (now - self.last_wake_time) >= config.ULTRASONIC_COOLDOWN_SEC:
                self.last_wake_time = now
                logger.info(
                    "Mock Ultrasonic triggered wake! Distance=%.1f cm (threshold=%.1f cm)",
                    self.current_distance,
                    config.WAKE_DISTANCE_CM
                )
                if self.on_wake_callback:
                    threading.Thread(target=self.on_wake_callback, daemon=True).start()

    def _sim_loop(self):
        """Gentle oscillation to make distance meter look alive in dashboard."""
        import math
        t = 0.0
        while self.is_running:
            time.sleep(config.ULTRASONIC_SAMPLE_INTERVAL)
            t += config.ULTRASONIC_SAMPLE_INTERVAL
            with self._lock:
                # If distance has not been overridden by user recently, oscillate between 95 and 140 cm
                if self.current_distance > 70.0:
                    self.current_distance = round(110.0 + 15.0 * math.sin(t * 0.5), 1)
