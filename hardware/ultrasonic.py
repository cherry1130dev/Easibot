"""
HC-SR04 Ultrasonic Distance Sensor Driver.
Manages proximity detection, distance smoothing, and autonomous wake-up triggers
using gpiozero.DistanceSensor on Raspberry Pi, with automatic mock fallback.
"""

import time
import logging
import threading
from typing import Optional, Callable

import config
from hardware.mock_hardware import MockUltrasonic

logger = logging.getLogger("easibot.ultrasonic")

# Check if gpiozero is available (on Raspberry Pi OS)
try:
    from gpiozero import DistanceSensor
    GPIOZERO_AVAILABLE = True
except (ImportError, NotImplementedError):
    GPIOZERO_AVAILABLE = False


class UltrasonicSensor:
    """Manages HC-SR04 proximity sensing and wake triggers."""

    def __init__(
        self,
        on_wake_callback: Optional[Callable[[], None]] = None,
        mock_override: Optional[bool] = None
    ):
        self.mock_mode = mock_override if mock_override is not None else config.MOCK_HARDWARE
        self.on_wake_callback = on_wake_callback
        self.sensor_device: Optional[Any] = None
        self.current_distance: float = -1.0
        self.is_running = False
        self.last_wake_time = 0.0
        self._thread: Optional[threading.Thread] = None
        self._recent_readings = []
        self._lock = threading.Lock()

        if not self.mock_mode and GPIOZERO_AVAILABLE:
            try:
                # HC-SR04 on gpiozero (max_distance in meters)
                self.sensor_device = DistanceSensor(
                    echo=config.PIN_ECHO,
                    trigger=config.PIN_TRIG,
                    max_distance=3.5,
                    threshold_distance=config.WAKE_DISTANCE_CM / 100.0
                )
                logger.info(
                    "Physical HC-SR04 sensor initialized (TRIG=GPIO%d, ECHO=GPIO%d)",
                    config.PIN_TRIG,
                    config.PIN_ECHO
                )
            except Exception as e:
                logger.warning("Failed to initialize physical HC-SR04 (%s). Using mock sensor.", e)
                self.mock_mode = True
                self.sensor_device = MockUltrasonic(on_wake_callback=self._handle_wake_trigger)
        else:
            self.mock_mode = True
            self.sensor_device = MockUltrasonic(on_wake_callback=self._handle_wake_trigger)

    def start(self):
        """Starts distance sampling thread."""
        self.is_running = True
        if self.mock_mode and hasattr(self.sensor_device, "start"):
            self.sensor_device.start()

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Ultrasonic sensor monitor loop active.")

    def stop(self):
        self.is_running = False
        if self.mock_mode and hasattr(self.sensor_device, "stop"):
            self.sensor_device.stop()
        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info("Ultrasonic sensor stopped.")

    def get_distance(self) -> float:
        """Returns smoothed distance in centimeters."""
        if self.mock_mode and hasattr(self.sensor_device, "get_distance"):
            return self.sensor_device.get_distance()
        with self._lock:
            return self.current_distance

    def _monitor_loop(self):
        """Polls distance and triggers wake when object is within threshold."""
        while self.is_running:
            try:
                if not self.mock_mode and self.sensor_device:
                    # gpiozero returns distance in meters (0.0 to 3.5)
                    raw_meters = self.sensor_device.distance
                    dist_cm = raw_meters * 100.0
                    
                    with self._lock:
                        self._recent_readings.append(dist_cm)
                        if len(self._recent_readings) > 3:
                            self._recent_readings.pop(0)
                        # Moving average filter
                        self.current_distance = round(sum(self._recent_readings) / len(self._recent_readings), 1)

                    # Check proximity condition
                    if 2.0 <= self.current_distance <= config.WAKE_DISTANCE_CM:
                        self._check_and_trigger_wake()

                elif self.mock_mode and hasattr(self.sensor_device, "get_distance"):
                    with self._lock:
                        self.current_distance = self.sensor_device.get_distance()

            except Exception as e:
                logger.debug("Ultrasonic reading error: %s", e)

            time.sleep(config.ULTRASONIC_SAMPLE_INTERVAL)

    def _check_and_trigger_wake(self):
        """Validates cooldown timer before invoking wake callback."""
        now = time.time()
        if (now - self.last_wake_time) >= config.ULTRASONIC_COOLDOWN_SEC:
            self.last_wake_time = now
            logger.info("Proximity detected! Distance: %.1f cm. Triggering wake callback.", self.current_distance)
            self._handle_wake_trigger()

    def _handle_wake_trigger(self):
        if self.on_wake_callback:
            try:
                threading.Thread(target=self.on_wake_callback, daemon=True).start()
            except Exception as e:
                logger.error("Error executing wake callback: %s", e)
