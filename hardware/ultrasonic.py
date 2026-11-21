"""
HC-SR04 Ultrasonic Distance Sensor Driver.
Manages proximity detection, distance smoothing, and autonomous wake-up triggers
using direct RPi.GPIO pulse timing and gpiozero.DistanceSensor on Raspberry Pi,
with automatic mock fallback for laptop development.
"""

import time
import logging
import threading
from typing import Optional, Callable, Any

import config
from hardware.mock_hardware import MockUltrasonic

logger = logging.getLogger("easibot.ultrasonic")

# Check available Raspberry Pi GPIO libraries
RPI_GPIO_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    RPI_GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_GPIO_AVAILABLE = False

GPIOZERO_AVAILABLE = False
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
        self._use_direct_gpio = False
        self.current_distance: float = -1.0
        self.is_running = False
        self.last_wake_time = 0.0
        self._thread: Optional[threading.Thread] = None
        self._recent_readings = []
        self._lock = threading.Lock()

        if not self.mock_mode:
            # 1. Try Direct RPi.GPIO pulse measurement (most reliable on Raspberry Pi OS Bookworm)
            if RPI_GPIO_AVAILABLE:
                try:
                    GPIO.setmode(GPIO.BCM)
                    GPIO.setwarnings(False)
                    GPIO.setup(config.PIN_TRIG, GPIO.OUT)
                    GPIO.setup(config.PIN_ECHO, GPIO.IN)
                    GPIO.output(config.PIN_TRIG, False)
                    self._use_direct_gpio = True
                    logger.info("HC-SR04 initialized using direct RPi.GPIO (TRIG=%d, ECHO=%d)", config.PIN_TRIG, config.PIN_ECHO)
                except Exception as e:
                    logger.warning("Failed to setup direct RPi.GPIO for ultrasonic: %s", e)

            # 2. Try gpiozero fallback if direct GPIO not available
            if not self._use_direct_gpio and GPIOZERO_AVAILABLE:
                try:
                    self.sensor_device = DistanceSensor(
                        echo=config.PIN_ECHO,
                        trigger=config.PIN_TRIG,
                        max_distance=3.5,
                        threshold_distance=config.WAKE_DISTANCE_CM / 100.0
                    )
                    logger.info("HC-SR04 initialized using gpiozero (TRIG=%d, ECHO=%d)", config.PIN_TRIG, config.PIN_ECHO)
                except Exception as e:
                    logger.warning("Failed to setup gpiozero DistanceSensor: %s", e)

            # If both hardware setups failed, fallback to mock
            if not self._use_direct_gpio and not self.sensor_device:
                logger.warning("No physical ultrasonic driver available. Using mock sensor.")
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

    def _read_distance_cm(self) -> float:
        """Reads hardware distance in centimeters."""
        if self._use_direct_gpio:
            try:
                # 10us pulse on TRIG
                GPIO.output(config.PIN_TRIG, True)
                time.sleep(0.00001)
                GPIO.output(config.PIN_TRIG, False)

                pulse_start = time.time()
                pulse_end = time.time()
                timeout = pulse_start + 0.04  # 40ms timeout

                # Wait for ECHO to rise
                while GPIO.input(config.PIN_ECHO) == 0:
                    pulse_start = time.time()
                    if pulse_start > timeout:
                        return -1.0

                # Wait for ECHO to fall
                while GPIO.input(config.PIN_ECHO) == 1:
                    pulse_end = time.time()
                    if pulse_end > timeout:
                        return -1.0

                if pulse_end > pulse_start:
                    duration = pulse_end - pulse_start
                    dist = (duration * 34300.0) / 2.0
                    if 2.0 <= dist <= 400.0:
                        return round(dist, 1)
            except Exception as e:
                logger.debug("Direct GPIO ultrasonic read error: %s", e)
            return -1.0

        if self.sensor_device and hasattr(self.sensor_device, "distance"):
            try:
                raw_meters = self.sensor_device.distance
                dist = raw_meters * 100.0
                if 2.0 <= dist <= 400.0:
                    return round(dist, 1)
            except Exception:
                pass
            return -1.0

        return -1.0

    def _monitor_loop(self):
        """Polls distance and triggers wake when object is within threshold."""
        while self.is_running:
            try:
                if not self.mock_mode:
                    dist_cm = self._read_distance_cm()
                    if dist_cm > 0:
                        with self._lock:
                            self._recent_readings.append(dist_cm)
                            if len(self._recent_readings) > 3:
                                self._recent_readings.pop(0)
                            # Moving average filter
                            self.current_distance = round(sum(self._recent_readings) / len(self._recent_readings), 1)

                        # Check proximity condition
                        if 2.0 <= self.current_distance <= config.WAKE_DISTANCE_CM:
                            self._check_and_trigger_wake()
                    else:
                        with self._lock:
                            self.current_distance = -1.0

                elif self.mock_mode and hasattr(self.sensor_device, "get_distance"):
                    with self._lock:
                        self.current_distance = self.sensor_device.get_distance()

            except Exception as e:
                logger.debug("Ultrasonic loop error: %s", e)

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
