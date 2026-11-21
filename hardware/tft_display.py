"""
2.8-inch SPI TFT LCD Controller (ILI9341 - KMRTM28028-SPI).
Renders status bar, animated expressive robot eyes, and multilingual subtitles.
Includes automatic fallback to romanized script if Indic shaping is unavailable.
"""

import time
import math
import logging
import threading
from pathlib import Path
from typing import Optional, Tuple, List

from PIL import Image, ImageDraw, ImageFont

import config
from core.state_manager import RobotState, Emotion
from hardware.mock_hardware import MockTFTDisplay

logger = logging.getLogger("easibot.display")

# Try importing hardware libraries for Raspberry Pi
IMPORT_ERROR = None
try:
    import board
    import digitalio
    from adafruit_rgb_display import ili9341
    RPI_HARDWARE_AVAILABLE = True
except Exception as e:
    RPI_HARDWARE_AVAILABLE = False
    IMPORT_ERROR = str(e)


class FontManager:
    """Finds and loads TrueType fonts with multilingual support."""

    def __init__(self):
        self.font_latin_small = self._find_font("latin", 13)
        self.font_latin_med = self._find_font("latin", 16)
        self.font_latin_bold = self._find_font("latin", 18)
        
        self.font_telugu = self._find_font("telugu", 15)
        self.font_devanagari = self._find_font("devanagari", 15)

    def _find_font(self, category: str, size: int) -> ImageFont.ImageFont:
        candidates = config.FONT_CANDIDATES.get(category, [])
        for p in candidates:
            path = Path(p)
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size)
                except Exception:
                    continue
        # Fallback to default bitmap font if no TTF found
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def get_font_for_language(self, lang_code: str, size_variant: str = "med") -> ImageFont.ImageFont:
        if lang_code == "te" and self.font_telugu:
            return self.font_telugu
        if lang_code == "hi" and self.font_devanagari:
            return self.font_devanagari
        
        if size_variant == "small":
            return self.font_latin_small
        if size_variant == "bold":
            return self.font_latin_bold
        return self.font_latin_med

    def can_render_native_script(self, text: str, lang_code: str) -> bool:
        """Verifies if the font can render Indic script characters without missing glyphs."""
        if lang_code == "en":
            return True
        font = self.get_font_for_language(lang_code)
        if font is None:
            return False
        # Check if PIL supports basic getbbox or mask
        try:
            dummy_img = Image.new("RGB", (10, 10))
            draw = ImageDraw.Draw(dummy_img)
            bbox = draw.textbbox((0, 0), text[:5], font=font)
            return bbox[2] > bbox[0]
        except Exception:
            return False


class RobotFacePainter:
    """Paints status bar, robot eyes, and subtitles onto a 320x240 image canvas."""

    def __init__(self):
        self.width = config.TFT_WIDTH
        self.height = config.TFT_HEIGHT
        self.fonts = FontManager()
        self.animation_tick = 0
        self.blink_progress = 0.0
        self.is_blinking = False

    def update_animation(self):
        """Advances animation counters (called at ~15-20 FPS)."""
        self.animation_tick += 1
        
        # Periodic blinking (every ~60-80 ticks)
        if not self.is_blinking and (self.animation_tick % 75 == 0):
            self.is_blinking = True
            self.blink_progress = 0.0

        if self.is_blinking:
            self.blink_progress += 0.25
            if self.blink_progress >= 1.0:
                self.is_blinking = False
                self.blink_progress = 0.0

    def draw_frame(
        self,
        state: RobotState,
        emotion: Emotion,
        distance_cm: float,
        active_lang: str,
        detected_lang: str,
        reply_native: str,
        reply_romanized: str,
        ip_address: str
    ) -> Image.Image:
        """Renders complete 320x240 display frame."""
        self.update_animation()

        img = Image.new("RGB", (self.width, self.height), config.COLOR_BG)
        draw = ImageDraw.Draw(img)

        # 1. Render Top Status Bar (Height: 26px)
        self._draw_status_bar(draw, state, distance_cm, active_lang, detected_lang, ip_address)

        # 2. Render Animated Robot Eyes (Center area: y=28 to 155)
        self._draw_eyes(draw, state, emotion)

        # 3. Render Subtitle / Dialogue Card (Bottom area: y=160 to 235)
        self._draw_subtitles(draw, reply_native, reply_romanized, detected_lang)

        return img

    def _draw_status_bar(
        self,
        draw: ImageDraw.ImageDraw,
        state: RobotState,
        distance_cm: float,
        active_lang: str,
        detected_lang: str,
        ip_address: str
    ):
        # Bar background
        draw.rectangle([(0, 0), (self.width, 26)], fill=config.COLOR_CARD)
        draw.line([(0, 26), (self.width, 26)], fill=config.COLOR_BORDER, width=1)

        # Status badge indicator
        status_colors = {
            RobotState.IDLE: (148, 163, 184),      # Slate gray
            RobotState.WAKING: (245, 158, 11),     # Amber
            RobotState.LISTENING: (56, 189, 248),  # Sky blue
            RobotState.THINKING: (168, 85, 247),   # Purple
            RobotState.SPEAKING: (74, 222, 128),   # Green
            RobotState.ERROR: (239, 68, 68),       # Red
        }
        badge_color = status_colors.get(state, (0, 212, 255))
        draw.ellipse([(8, 8), (18, 18)], fill=badge_color)

        # State text
        font_small = self.fonts.font_latin_small
        state_str = state.value.upper()
        draw.text((24, 6), state_str, fill=config.COLOR_TEXT_PRIMARY, font=font_small)

        # Active language badge (Center)
        lang_labels = {"en": "EN", "te": "తెలుగు", "hi": "हिंदी", "auto": "AUTO"}
        lang_str = lang_labels.get(active_lang, active_lang.upper())
        lang_font = self.fonts.get_font_for_language(active_lang, "small")
        lang_x = 135
        # Badge background pill
        draw.rounded_rectangle([(lang_x - 5, 4), (lang_x + 55, 22)], radius=4, fill=(30, 41, 59), outline=(71, 85, 105))
        draw.text((lang_x + 4, 5), lang_str, fill=config.COLOR_ACCENT, font=lang_font)

        # Ultrasonic distance indicator (Right side)
        if distance_cm > 0:
            dist_str = f"{int(distance_cm)}cm"
        else:
            dist_str = "--"
        dist_text = f"Proximity: {dist_str}"
        draw.text((225, 6), dist_text, fill=config.COLOR_TEXT_MUTED, font=font_small)

    def _draw_eyes(self, draw: ImageDraw.ImageDraw, state: RobotState, emotion: Emotion):
        """Draws dynamic, expressive robot eyes with specular highlights."""
        eye_color = config.EMOTION_COLORS.get(emotion.value, config.COLOR_ACCENT)
        
        # Center positions for left and right eyes
        left_center = (95, 92)
        right_center = (225, 92)
        base_w, base_h = 60, 56
        radius = 16

        # Calculate blink / vertical squeeze factor
        blink_factor = 1.0
        if self.is_blinking:
            # Squeeze down to 10% height at peak blink
            squeeze = math.sin(self.blink_progress * math.pi)
            blink_factor = max(0.1, 1.0 - squeeze * 0.9)

        # Animation modulations
        y_offset = 0
        x_offset = 0

        if state == RobotState.SPEAKING:
            # Bouncing mouth/eye vibration
            y_offset = int(math.sin(self.animation_tick * 0.8) * 4)
        elif state == RobotState.THINKING:
            # Eyes drift side to side looking upwards
            x_offset = int(math.sin(self.animation_tick * 0.3) * 8)
            y_offset = -4
        elif state == RobotState.LISTENING:
            # Subtle pulsating size
            base_w += int(math.sin(self.animation_tick * 0.4) * 4)
            base_h += int(math.sin(self.animation_tick * 0.4) * 4)

        current_h = max(4, int(base_h * blink_factor))

        # Render Left & Right Eye
        for center in (left_center, right_center):
            cx = center[0] + x_offset
            cy = center[1] + y_offset

            if emotion == Emotion.HAPPY and blink_factor > 0.5:
                # Draw cute happy curved arcs: ^ ^
                arc_bbox = [cx - base_w // 2, cy - current_h // 2, cx + base_w // 2, cy + current_h // 2 + 10]
                draw.arc(arc_bbox, start=190, end=350, fill=eye_color, width=7)
                continue

            # Standard rounded rectangle eye
            x0 = cx - base_w // 2
            y0 = cy - current_h // 2
            x1 = cx + base_w // 2
            y1 = cy + current_h // 2

            # Outer subtle glow if listening or thinking
            if state in (RobotState.LISTENING, RobotState.THINKING):
                draw.rounded_rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], radius=radius + 2, fill=(20, 45, 65))

            draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=eye_color)

            # Specular highlight (cute reflection dot) if open
            if blink_factor > 0.6:
                highlight_r = 5
                hx = x1 - 16
                hy = y0 + 12
                draw.ellipse([hx - highlight_r, hy - highlight_r, hx + highlight_r, hy + highlight_r], fill=(255, 255, 255))

        # Soundwave arches above eyes when listening
        if state == RobotState.LISTENING:
            wave_amp = int(math.sin(self.animation_tick * 0.5) * 6)
            draw.arc([75, 48 - wave_amp, 115, 68], start=200, end=340, fill=(56, 189, 248), width=3)
            draw.arc([205, 48 - wave_amp, 245, 68], start=200, end=340, fill=(56, 189, 248), width=3)

    def _draw_subtitles(
        self,
        draw: ImageDraw.ImageDraw,
        reply_native: str,
        reply_romanized: str,
        lang_code: str
    ):
        """Draws rounded subtitle container with wrapped dialogue."""
        card_rect = [(10, 160), (self.width - 10, self.height - 8)]
        draw.rounded_rectangle(card_rect, radius=8, fill=config.COLOR_CARD, outline=config.COLOR_BORDER, width=1)

        # Decide whether to render native Indic script or fallback to romanized
        display_text = reply_native.strip()
        font = self.fonts.get_font_for_language(lang_code, "med")

        if lang_code in ("te", "hi"):
            can_render = self.fonts.can_render_native_script(display_text, lang_code)
            if not can_render and reply_romanized:
                display_text = reply_romanized
                font = self.fonts.font_latin_med

        # Wrap text to fit inside 300px width
        wrapped_lines = self._wrap_text(display_text, font, max_width=290, max_lines=3)

        # Draw lines centered or left-aligned
        y_text = 168
        for line in wrapped_lines:
            draw.text((20, y_text), line, fill=config.COLOR_TEXT_PRIMARY, font=font)
            y_text += 22

    def _wrap_text(self, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> List[str]:
        """Simple greedy text wrap."""
        if not text:
            return [""]
        words = text.split()
        lines = []
        current_line = []

        dummy = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(dummy)

        for word in words:
            test_line = " ".join(current_line + [word])
            try:
                bbox = draw.textbbox((0, 0), test_line, font=font)
                width = bbox[2] - bbox[0]
            except Exception:
                width = len(test_line) * 9

            if width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]

            if len(lines) >= max_lines:
                break

        if current_line and len(lines) < max_lines:
            lines.append(" ".join(current_line))

        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] += "..."

        return lines or [text[:40]]


class TFTDisplay:
    """Production TFT Display Controller with hardware / mock auto-selection."""

    def __init__(self, mock_override: Optional[bool] = None):
        self.mock_mode = mock_override if mock_override is not None else config.MOCK_HARDWARE
        self.painter = RobotFacePainter()
        self.display_device: Optional[Any] = None
        self._running = False
        self._render_thread: Optional[threading.Thread] = None
        self._state_ref = None

        if not self.mock_mode and RPI_HARDWARE_AVAILABLE:
            try:
                self._init_rpi_hardware()
            except Exception as e:
                logger.warning("Failed to initialize physical ILI9341 display (%s). Falling back to mock.", e)
                self.mock_mode = True
                self.display_device = MockTFTDisplay(painter=self.painter)
        else:
            if not self.mock_mode and not RPI_HARDWARE_AVAILABLE:
                logger.warning("Physical display requested, but hardware libraries not available: %s. Using mock.", IMPORT_ERROR)
            self.mock_mode = True
            self.display_device = MockTFTDisplay(painter=self.painter)

    def _init_rpi_hardware(self):
        """Initializes Adafruit CircuitPython ILI9341 on Raspberry Pi."""
        # 1. Turn on LCD Backlight (GPIO 18)
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(config.PIN_TFT_BACKLIGHT, GPIO.OUT)
            GPIO.output(config.PIN_TFT_BACKLIGHT, GPIO.HIGH)
            logger.info("TFT Backlight GPIO %d set to HIGH", config.PIN_TFT_BACKLIGHT)
        except Exception as e:
            logger.debug("RPi.GPIO backlight setup note: %s", e)

        # 2. Initialize SPI and Control Pins
        spi = board.SPI()
        cs_pin = digitalio.DigitalInOut(getattr(board, f"D{config.PIN_TFT_CS}"))
        dc_pin = digitalio.DigitalInOut(getattr(board, f"D{config.PIN_TFT_DC}"))
        rst_pin = digitalio.DigitalInOut(getattr(board, f"D{config.PIN_TFT_RST}"))

        self.display_device = ili9341.ILI9341(
            spi,
            cs=cs_pin,
            dc=dc_pin,
            rst=rst_pin,
            width=240,
            height=320,
            rotation=config.TFT_ROTATION,
            baudrate=config.SPI_BAUDRATE
        )
        logger.info("Physical ILI9341 display initialized successfully over SPI (320x240 landscape).")

    def start_animation_loop(self, state_manager):
        """Starts background rendering loop (~15 FPS)."""
        self._state_ref = state_manager
        self._running = True
        self._render_thread = threading.Thread(target=self._animation_worker, daemon=True)
        self._render_thread.start()
        logger.info("TFT Display animation loop started.")

    def stop_animation_loop(self):
        self._running = False
        if self._render_thread:
            self._render_thread.join(timeout=1.0)
        logger.info("TFT Display animation loop stopped.")

    def _animation_worker(self):
        """Renders frames at ~15-20 FPS for smooth eye movement with minimal Pi Zero CPU usage."""
        while self._running:
            try:
                if self._state_ref:
                    frame = self.painter.draw_frame(
                        state=self._state_ref.state,
                        emotion=self._state_ref.emotion,
                        distance_cm=self._state_ref.current_distance,
                        active_lang=self._state_ref.active_language,
                        detected_lang=self._state_ref.detected_language,
                        reply_native=self._state_ref.last_reply_native,
                        reply_romanized=self._state_ref.last_reply_romanized,
                        ip_address=self._state_ref._ip_address
                    )
                    self._push_frame(frame)
            except Exception as e:
                logger.error("Error in display render loop: %s", e)

            # ~16 FPS sleep
            time.sleep(0.06)

    def _push_frame(self, img: Image.Image):
        """Sends frame to ILI9341 or Mock Display."""
        if self.mock_mode or not hasattr(self.display_device, "image"):
            if hasattr(self.display_device, "display_image"):
                self.display_device.display_image(img)
        else:
            try:
                self.display_device.image(img)
            except Exception as e:
                logger.debug("Hardware display image error: %s", e)
