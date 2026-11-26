"""
Easibot Configuration Module
Contains all pinouts, AI settings, audio parameters, and system paths.
Supports runtime detection of Raspberry Pi hardware vs. Laptop Mock Mode.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory paths
BASE_DIR = Path(__file__).resolve().parent
TEMP_AUDIO_DIR = BASE_DIR / "temp_audio"
TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file
load_dotenv(BASE_DIR / ".env")

# ==============================================================================
# Hardware vs Laptop Mock Detection
# ==============================================================================
# Set MOCK_HARDWARE=true in .env to run without physical Raspberry Pi GPIO/SPI
MOCK_HARDWARE = os.getenv("MOCK_HARDWARE", "true").lower() in ("true", "1", "yes")

# ==============================================================================
# Google Gemini AI Settings
# ==============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Default language preference: 'auto', 'en', 'te', or 'hi'
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "auto").lower()

# Supported languages
SUPPORTED_LANGUAGES = {
    "auto": "Auto Detect",
    "en": "English",
    "te": "తెలుగు (Telugu)",
    "hi": "हिंदी (Hindi)"
}

# ==============================================================================
# 2.8" SPI TFT LCD (ILI9341 - KMRTM28028-SPI)
# Target Pinout for Raspberry Pi Zero 2 W:
#   VCC   -> 3.3V (Pin 1)
#   GND   -> GND (Pin 6)
#   CS    -> GPIO 8 / CE0 (Pin 24)
#   RESET -> GPIO 25 (Pin 22)
#   DC/RS -> GPIO 24 (Pin 18)
#   MOSI  -> GPIO 10 (Pin 19)
#   SCK   -> GPIO 11 (Pin 23)
#   LED   -> GPIO 18 (Pin 12) or 3.3V
# ==============================================================================
TFT_WIDTH = 320
TFT_HEIGHT = 240
TFT_ROTATION = 90  # Landscape orientation

# BCM GPIO Pin numbers
PIN_TFT_CS = 8       # CE0
PIN_TFT_DC = 24      # Data/Command
PIN_TFT_RST = 25     # Reset
PIN_TFT_BACKLIGHT = 18  # Backlight PWM / GPIO control
SPI_BAUDRATE = 24000000  # 24MHz for stable SPI on Pi Zero 2 W

# Display theme colors (RGB tuples)
COLOR_BG = (12, 16, 28)         # Deep slate dark
COLOR_CARD = (22, 28, 44)       # Elevated container
COLOR_ACCENT = (0, 212, 255)    # Neon cyan
COLOR_TEXT_PRIMARY = (255, 255, 255)
COLOR_TEXT_MUTED = (160, 174, 192)
COLOR_BORDER = (45, 55, 72)

# Eye colors by emotion
EMOTION_COLORS = {
    "neutral": (0, 212, 255),      # Neon Cyan
    "happy": (72, 239, 128),       # Bright Emerald Green
    "listening": (56, 189, 248),    # Sky Blue
    "thinking": (245, 158, 11),     # Amber Gold
    "speaking": (168, 85, 247),     # Electric Violet
    "error": (239, 68, 68),        # Crimson Red
}

# ==============================================================================
# HC-SR04 Ultrasonic Distance Sensor
# Pinout:
#   VCC  -> 5V (Pin 2)
#   GND  -> GND (Pin 9)
#   TRIG -> GPIO 23 (Pin 16)
#   ECHO -> GPIO 27 (Pin 13) (via 1k / 2k ohm voltage divider to protect 3.3V Pi pin)
# ==============================================================================
PIN_TRIG = int(os.getenv("PIN_TRIG", "23"))
PIN_ECHO = int(os.getenv("PIN_ECHO", "27"))

# Proximity trigger threshold
WAKE_DISTANCE_CM = float(os.getenv("WAKE_DISTANCE_CM", "60.0"))
ULTRASONIC_COOLDOWN_SEC = float(os.getenv("ULTRASONIC_COOLDOWN_SEC", "15.0"))
ULTRASONIC_SAMPLE_INTERVAL = 0.2  # Poll every 200ms

# ==============================================================================
# Voice & Audio Pipeline Settings
# ==============================================================================
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
RECORD_DURATION_SEC = float(os.getenv("RECORD_DURATION_SEC", "5.0"))
ENABLE_SPEAKER_BY_DEFAULT = os.getenv("ENABLE_SPEAKER_BY_DEFAULT", "true").lower() in ("true", "1", "yes")

# Microsoft Edge TTS Voices (High-quality Neural)
EDGE_TTS_VOICES = {
    "en": "en-IN-NeerjaNeural",     # Indian English female
    "te": "te-IN-ShrutiNeural",     # Telugu female
    "hi": "hi-IN-SwaraNeural",      # Hindi female
}

# gTTS language fallback codes
GTTS_LANG_CODES = {
    "en": "en",
    "te": "te",
    "hi": "hi",
}

# Welcome greetings by language
WELCOME_GREETINGS = {
    "en": {
        "text": "Hello! I am Easibot. How can I help you today?",
        "romanized": "Hello! I am Easibot. How can I help you today?",
        "lang": "en"
    },
    "te": {
        "text": "నమస్కారం! నేను ఈసీబాట్. నేను మీకు ఎలా సహాయపడగలను?",
        "romanized": "Namaskaram! Nenu Easibot. Nenu meeku ela sahayapadagalanu?",
        "lang": "te"
    },
    "hi": {
        "text": "नमस्ते! मैं ईसीबॉट हूँ। मैं आपकी क्या मदद कर सकता हूँ?",
        "romanized": "Namaste! Main Easibot hoon. Main aapki kya madad kar sakta hoon?",
        "lang": "hi"
    }
}

# ==============================================================================
# Web Dashboard Settings
# ==============================================================================
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")

# ==============================================================================
# Font Paths for Indic & Multilingual Text Rendering
# Searches Raspberry Pi OS paths, Windows system fonts, and local assets
# ==============================================================================
FONT_CANDIDATES = {
    "latin": [
        FONTS_DIR / "NotoSans-Regular.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ],
    "telugu": [
        FONTS_DIR / "NotoSansTelugu-Regular.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf"),
        Path("/usr/share/fonts/truetype/fonts-telu-extra/Pothana2000.ttf"),
        Path("/usr/share/fonts/truetype/lohit-telugu/Lohit-Telugu.ttf"),
        Path("C:/Windows/Fonts/Nirmala.ttf"),
        Path("C:/Windows/Fonts/gautami.ttf"),
    ],
    "devanagari": [
        FONTS_DIR / "NotoSansDevanagari-Regular.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
        Path("/usr/share/fonts/truetype/fonts-deva-extra/Gargi.ttf"),
        Path("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf"),
        Path("C:/Windows/Fonts/Nirmala.ttf"),
        Path("C:/Windows/Fonts/mangal.ttf"),
    ]
}
