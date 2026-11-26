"""
Easibot Simple Edition - Single-File AI Multilingual Assistant Robot
===================================================================
Supports Raspberry Pi Zero W / Zero 2 W & Laptop Mock Mode.
Features:
  - Google Gemini AI (English, Telugu, Hindi + Native Audio Recognition)
  - Auto-Switching Audio: USB Mic / Bluetooth Neckband (Zebronics) / Laptop Mic
  - Auto-Switching Output: Bluetooth Speaker / USB / HDMI via edge-tts & gTTS
  - Fast NumPy ILI9341 2.8" SPI TFT LCD Display with Animated Robot Eyes
  - HC-SR04 Ultrasonic Proximity Wake-Up (60cm threshold, 15s cooldown)
  - Embedded Lightweight Flask Web Dashboard on Port 5000

Run:
  python easibot_simple.py
"""

import os
import re
import sys
import json
import time
import wave
import math
import shutil
import asyncio
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template_string
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("easibot")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
MOCK_HARDWARE = os.getenv("MOCK_HARDWARE", "false" if sys.platform.startswith("linux") else "true").lower() in ("1", "true", "yes")

# GPIO Pins (BCM)
PIN_TRIG = 23          # HC-SR04 TRIG (Pin 16)
PIN_ECHO = 27          # HC-SR04 ECHO (Pin 13 via 1k/2k voltage divider)
PIN_TFT_DC = 24        # TFT DC/RS (Pin 18)
PIN_TFT_RST = 25       # TFT RESET (Pin 22)
PIN_TFT_LED = 18       # TFT Backlight (Pin 12)

WAKE_DISTANCE_CM = float(os.getenv("WAKE_DISTANCE_CM", "60.0"))
COOLDOWN_SEC = float(os.getenv("ULTRASONIC_COOLDOWN_SEC", "15.0"))
RECORD_SEC = float(os.getenv("RECORD_DURATION_SEC", "5.0"))
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

TEMP_DIR = BASE_DIR / "temp_audio"
TEMP_DIR.mkdir(exist_ok=True)

TTS_VOICES = {"en": "en-IN-NeerjaNeural", "te": "te-IN-ShrutiNeural", "hi": "hi-IN-SwaraNeural"}
EMOTION_COLORS = {
    "neutral": (0, 212, 255), "happy": (72, 239, 128),
    "listening": (56, 189, 248), "thinking": (245, 158, 11),
    "speaking": (168, 85, 247), "error": (239, 68, 68),
}

# Global Thread-Safe Robot State
state_lock = threading.Lock()
robot = {
    "state": "idle",          # idle, listening, thinking, speaking, error
    "emotion": "happy",
    "language": os.getenv("DEFAULT_LANGUAGE", "auto"),
    "detected_lang": "en",
    "distance_cm": -1.0,
    "speaker_on": True,
    "reply_native": "Hello! I am Easibot. Ready!",
    "reply_romanized": "Hello! I am Easibot. Ready!",
    "mic_info": "Detecting...",
    "speaker_info": "Detecting...",
    "messages": [],
}
last_wake_time = 0.0
voice_busy_lock = threading.Lock()


# ==============================================================================
# 2. MULTILINGUAL AI ENGINE (GOOGLE GEMINI)
# ==============================================================================
class RobotReply(BaseModel):
    detected_language: str = Field(description="'en', 'te', or 'hi'")
    reply_native: str = Field(description="Reply in native script (Telugu/Hindi/English)")
    reply_english: str = Field(description="English translation")
    reply_romanized: str = Field(description="Latin/English phonetic transliteration")
    emotion: str = Field(description="'happy', 'thinking', 'listening', 'speaking', or 'neutral'")


SYSTEM_PROMPT = (
    "You are Easibot, a friendly multilingual robot assistant on a Raspberry Pi. "
    "Understand English (en), Telugu (te), Hindi (hi), and code-mixed speech. "
    "Keep answers short (1-2 clear sentences for a tiny 320x240 screen and quick voice TTS). "
    "Always return JSON with detected_language, reply_native, reply_english, reply_romanized, and emotion."
)

genai_client = None
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    try:
        from google import genai
        from google.genai import types
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        log.info("Gemini AI client ready (model: %s)", GEMINI_MODEL)
    except Exception as e:
        log.warning("Gemini init failed: %s", e)


def ask_gemini(text_query: Optional[str] = None, audio_wav: Optional[bytes] = None, lang_pref: str = "auto") -> RobotReply:
    """Queries Gemini 3.5 Flash with either text or raw .wav audio bytes."""
    if not genai_client:
        return RobotReply(
            detected_language="en", reply_native="API Key not set. Ready in offline mode!",
            reply_english="API Key not set.", reply_romanized="API Key not set.", emotion="neutral"
        )

    instr = SYSTEM_PROMPT
    if lang_pref in ("en", "te", "hi"):
        instr += f" IMPORTANT: Reply strictly in language '{lang_pref}'."

    cfg = types.GenerateContentConfig(
        system_instruction=instr,
        response_mime_type="application/json",
        response_schema=RobotReply,
        temperature=0.7,
    )

    if audio_wav:
        contents = [
            types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"),
            "Listen to this audio, understand English/Telugu/Hindi, and reply."
        ]
    else:
        contents = f"User: {text_query}"

    models = [GEMINI_MODEL, "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
    for m in dict.fromkeys(models):
        try:
            resp = genai_client.models.generate_content(model=m, contents=contents, config=cfg)
            if getattr(resp, "parsed", None):
                return resp.parsed if isinstance(resp.parsed, RobotReply) else RobotReply(**resp.parsed)
            raw = (resp.text or "{}").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return RobotReply(**json.loads(raw))
        except Exception as e:
            log.warning("Gemini model %s failed: %s", m, e)

    return RobotReply(
        detected_language="en", reply_native="Sorry, I could not reach Gemini right now.",
        reply_english="Sorry, I could not reach Gemini right now.",
        reply_romanized="Sorry, I could not reach Gemini right now.", emotion="error"
    )


# ==============================================================================
# 3. SMART AUTO-SWITCHING AUDIO (USB MIC / BLUETOOTH NECKBAND / FALLBACKS)
# ==============================================================================
def _find_usb_alsa_mic() -> Optional[str]:
    """Finds USB microphone card via 'arecord -l' -> returns 'plughw:X,Y'."""
    if not shutil.which("arecord"):
        return None
    try:
        out = subprocess.check_output(["arecord", "-l"], text=True, stderr=subprocess.DEVNULL)
        usb_cards = []
        any_cards = []
        for line in out.splitlines():
            m = re.match(r"card (\d+):.*device (\d+):", line)
            if m:
                dev_str = f"plughw:{m.group(1)},{m.group(2)}"
                any_cards.append((dev_str, line))
                if any(k in line.lower() for k in ("usb", "pnp", "mic", "webcam", "audio")):
                    usb_cards.append((dev_str, line))
        if usb_cards:
            log.info("Detected USB Mic: %s (%s)", usb_cards[0][0], usb_cards[0][1].strip())
            return usb_cards[0][0]
        if any_cards:
            log.info("Detected ALSA Mic: %s", any_cards[0][0])
            return any_cards[0][0]
    except Exception:
        pass
    return None


def _find_bluetooth_source() -> Optional[str]:
    """Checks PipeWire/PulseAudio for an active Bluetooth mic (e.g., Zebronics neckband)."""
    if not shutil.which("pactl"):
        return None
    try:
        # Ensure Bluetooth headset profile is activated if no USB mic exists and BT card is in a2dp
        cards = subprocess.check_output(["pactl", "list", "cards", "short"], text=True, stderr=subprocess.DEVNULL)
        for line in cards.splitlines():
            if "bluez_card" in line:
                card_name = line.split()[1]
                # Check if a bluez input source already exists
                sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True, stderr=subprocess.DEVNULL)
                for s in sources.splitlines():
                    if "bluez_input" in s or ("bluez_source" in s and "monitor" not in s):
                        return s.split()[1]
                # Try switching Zebronics neckband to HFP/HSP headset profile so its mic becomes active
                for prof in ("headset-head-unit", "headset-head-unit-msbc", "headset-head-unit-cvsd", "handsfree_head_unit"):
                    r = subprocess.run(["pactl", "set-card-profile", card_name, prof], stderr=subprocess.DEVNULL)
                    if r.returncode == 0:
                        time.sleep(1.0)
                        sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True, stderr=subprocess.DEVNULL)
                        for s in sources.splitlines():
                            if "bluez" in s and "monitor" not in s:
                                return s.split()[1]
    except Exception:
        pass
    return None


def record_voice(duration: float = RECORD_SEC) -> Optional[bytes]:
    """Records 16kHz mono WAV using whichever mic is available: USB Mic -> Bluetooth Neckband -> Default."""
    wav_path = TEMP_DIR / f"rec_{int(time.time()*1000)}.wav"
    try:
        # Priority 1: Physical USB Microphone via ALSA (highest voice clarity, leaves Bluetooth free for A2DP output!)
        usb_dev = _find_usb_alsa_mic()
        if usb_dev and shutil.which("arecord"):
            robot["mic_info"] = f"USB Mic ({usb_dev})"
            cmd = ["arecord", "-D", usb_dev, "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(int(duration)), str(wav_path)]
            if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 and wav_path.exists():
                return wav_path.read_bytes()

        # Priority 2: Bluetooth Neckband / Headset Mic (e.g. Zebronics) via PipeWire / PulseAudio
        bt_src = _find_bluetooth_source()
        if bt_src:
            robot["mic_info"] = f"Bluetooth Mic ({bt_src[:22]})"
            if shutil.which("parecord"):
                cmd = ["timeout", str(int(duration) + 1), "parecord", "-d", bt_src, "--rate=16000", "--channels=1", "--format=s16le", "--file-format=wav", str(wav_path)]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if wav_path.exists() and wav_path.stat().st_size > 1000:
                    return wav_path.read_bytes()

        # Priority 3: PipeWire / PulseAudio default mic
        for tool in ("pw-record", "parecord"):
            if shutil.which(tool):
                robot["mic_info"] = f"System Mic ({tool})"
                args = [tool, "--rate", "16000", "--channels", "1", str(wav_path)] if tool == "pw-record" else [tool, "--rate=16000", "--channels=1", "--file-format=wav", str(wav_path)]
                subprocess.run(["timeout", str(int(duration)), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if wav_path.exists() and wav_path.stat().st_size > 1000:
                    return wav_path.read_bytes()

        # Priority 4: sounddevice (Laptop / Windows mic or default PortAudio)
        try:
            import sounddevice as sd
            robot["mic_info"] = "Default Mic (sounddevice)"
            rec = sd.rec(int(duration * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(rec.tobytes())
            return wav_path.read_bytes()
        except Exception as e:
            log.warning("No working microphone found (%s)", e)
            robot["mic_info"] = "No Mic Found"
            return None
    finally:
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)


def speak_text(text: str, lang: str = "en"):
    """Synthesizes TTS (edge-tts -> gTTS fallback) and plays on available speaker (Bluetooth -> USB/HDMI)."""
    if not text.strip() or not robot["speaker_on"]:
        return

    mp3_path = TEMP_DIR / f"tts_{int(time.time()*1000)}.mp3"
    voice = TTS_VOICES.get(lang, TTS_VOICES["en"])
    synthesized = False

    # 1. Try edge-tts
    try:
        import edge_tts
        async def _synth():
            await edge_tts.Communicate(text, voice).save(str(mp3_path))
        asyncio.run(_synth())
        synthesized = mp3_path.exists() and mp3_path.stat().st_size > 300
    except Exception as e:
        log.warning("edge-tts failed (%s), falling back to gTTS...", e)

    # 2. Try gTTS fallback
    if not synthesized:
        try:
            from gtts import gTTS
            gTTS(text=text, lang=lang if lang in ("en", "te", "hi") else "en").save(str(mp3_path))
            synthesized = mp3_path.exists() and mp3_path.stat().st_size > 300
        except Exception as e:
            log.error("gTTS also failed: %s", e)

    if not synthesized:
        return

    # 3. Play on best available speaker
    try:
        if sys.platform.startswith("linux"):
            # Ensure Bluetooth sink is set as default if connected
            if shutil.which("pactl"):
                try:
                    sinks = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True, stderr=subprocess.DEVNULL)
                    bt_sinks = [l.split()[1] for l in sinks.splitlines() if "bluez" in l]
                    if bt_sinks:
                        subprocess.run(["pactl", "set-default-sink", bt_sinks[0]], stderr=subprocess.DEVNULL)
                        robot["speaker_info"] = f"Bluetooth ({bt_sinks[0][:20]})"
                    else:
                        robot["speaker_info"] = "ALSA / System Speaker"
                except Exception:
                    pass

            for player in (["mpg123", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["cvlc", "--play-and-exit"]):
                if shutil.which(player[0]):
                    subprocess.run([*player, str(mp3_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
        elif sys.platform.startswith("win"):
            robot["speaker_info"] = "Windows Speaker"
            if shutil.which("ffplay"):
                subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                ps = f"$w=New-Object -ComObject WMPlayer.OCX;$w.URL='{mp3_path}';$w.controls.play();while($w.playState -ne 1){{Start-Sleep -Milliseconds 100}}"
                subprocess.run(["powershell", "-c", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        mp3_path.unlink(missing_ok=True)


# ==============================================================================
# 4. FAST 2.8" SPI TFT DISPLAY (DIRECT SPIDEV + NUMPY)
# ==============================================================================
class SimpleTFT:
    def __init__(self):
        self.spi = None
        self.GPIO = None
        self.mock = MOCK_HARDWARE
        self.font_sm = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 13)
        self.font_md = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 16)
        self.font_te = self._load_font(["NotoSansTelugu-Regular.ttf", "Nirmala.ttf"], 15)
        self.font_hi = self._load_font(["NotoSansDevanagari-Regular.ttf", "Nirmala.ttf"], 15)
        self.tick = 0

        if not self.mock:
            try:
                import spidev, RPi.GPIO as GPIO
                self.GPIO = GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                for p in (PIN_TFT_DC, PIN_TFT_RST, PIN_TFT_LED):
                    GPIO.setup(p, GPIO.OUT)
                GPIO.output(PIN_TFT_LED, GPIO.HIGH)

                self.spi = spidev.SpiDev()
                self.spi.open(0, 0)
                self.spi.max_speed_hz = 24000000
                self.spi.mode = 0
                self._init_ili9341()
                log.info("TFT Display ready on /dev/spidev0.0 (Backlight GPIO %d ON)", PIN_TFT_LED)
            except Exception as e:
                log.warning("TFT hardware init skipped (%s) -> Mock mode", e)
                self.mock = True

    def _load_font(self, names, size):
        search_dirs = [BASE_DIR / "assets" / "fonts", Path("/usr/share/fonts/truetype/noto"), Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts")]
        for d in search_dirs:
            for n in names:
                p = d / n
                if p.exists():
                    try:
                        return ImageFont.truetype(str(p), size)
                    except Exception:
                        pass
        return ImageFont.load_default()

    def _cmd(self, c):
        self.GPIO.output(PIN_TFT_DC, self.GPIO.LOW)
        self.spi.writebytes([c])

    def _dat(self, d):
        self.GPIO.output(PIN_TFT_DC, self.GPIO.HIGH)
        self.spi.writebytes([d] if isinstance(d, int) else list(d))

    def _init_ili9341(self):
        self.GPIO.output(PIN_TFT_RST, self.GPIO.LOW); time.sleep(0.05)
        self.GPIO.output(PIN_TFT_RST, self.GPIO.HIGH); time.sleep(0.12)
        for cmd, data in [
            (0x01, None), (0xCB, [0x39, 0x2C, 0x00, 0x34, 0x02]), (0xCF, [0x00, 0xC1, 0x30]),
            (0xE8, [0x85, 0x00, 0x78]), (0xEA, [0x00, 0x00]), (0xED, [0x64, 0x03, 0x12, 0x81]),
            (0xF7, [0x20]), (0xC0, [0x23]), (0xC1, [0x10]), (0xC5, [0x3E, 0x28]),
            (0xC7, [0x86]), (0x36, [0xE8]), (0x3A, [0x55]), (0xB1, [0x00, 0x18]),
            (0xB6, [0x08, 0x82, 0x27]), (0x11, None), (0x29, None)
        ]:
            self._cmd(cmd)
            if data:
                self._dat(data)
            if cmd in (0x01, 0x11):
                time.sleep(0.12)

    def render_and_push(self):
        self.tick += 1
        img = Image.new("RGB", (320, 240), (12, 16, 28))
        d = ImageDraw.Draw(img)

        with state_lock:
            st, emo = robot["state"], robot["emotion"]
            dist, lang = robot["distance_cm"], robot["detected_lang"]
            txt = robot["reply_native"] if lang == "en" else (robot["reply_romanized"] or robot["reply_native"])

        # Top Status Bar
        d.rectangle([(0, 0), (320, 26)], fill=(22, 28, 44))
        d.text((10, 6), st.upper(), fill=EMOTION_COLORS.get(emo, (0, 212, 255)), font=self.font_sm)
        d.text((135, 6), f"[{lang.upper()}]", fill=(0, 212, 255), font=self.font_sm)
        d.text((225, 6), f"{int(dist)}cm" if dist > 0 else "-- cm", fill=(160, 174, 192), font=self.font_sm)

        # Animated Robot Eyes
        color = EMOTION_COLORS.get(emo, (0, 212, 255))
        blink = 0.15 if (self.tick % 20 == 0) else 1.0
        dy = int(math.sin(self.tick * 0.7) * 4) if st == "speaking" else 0
        h = max(6, int(54 * blink))
        for cx in (95, 225):
            if emo == "happy" and blink > 0.5:
                d.arc([cx - 30, 65, cx + 30, 125], start=190, end=350, fill=color, width=7)
            else:
                d.rounded_rectangle([cx - 30, 92 - h // 2 + dy, cx + 30, 92 + h // 2 + dy], radius=14, fill=color)
                if blink > 0.5:
                    d.ellipse([cx + 10, 92 - h // 2 + 8 + dy, cx + 18, 92 - h // 2 + 16 + dy], fill=(255, 255, 255))

        # Subtitle Card
        d.rounded_rectangle([(10, 160), (310, 232)], radius=8, fill=(22, 28, 44), outline=(45, 55, 72))
        words, lines, cur = txt.split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 <= 34:
                cur = f"{cur} {w}".strip()
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        for i, line in enumerate(lines[:3]):
            d.text((18, 168 + i * 20), line, fill=(255, 255, 255), font=self.font_md)

        if not self.mock and self.spi:
            self._cmd(0x2A); self._dat([0, 0, 1, 0x3F])
            self._cmd(0x2B); self._dat([0, 0, 0, 0xEF])
            self._cmd(0x2C)
            try:
                import numpy as np
                arr = np.asarray(img, dtype=np.uint16)
                buf = (((arr[:, :, 0] & 0xF8) << 8) | ((arr[:, :, 1] & 0xFC) << 3) | (arr[:, :, 2] >> 3)).astype(">u2").tobytes()
            except ImportError:
                raw = img.tobytes()
                buf = bytearray(320 * 240 * 2)
                for i in range(320 * 240):
                    buf[i * 2] = (raw[i * 3] & 0xF8) | (raw[i * 3 + 1] >> 5)
                    buf[i * 2 + 1] = ((raw[i * 3 + 1] & 0x1C) << 3) | (raw[i * 3 + 2] >> 3)
            self.GPIO.output(PIN_TFT_DC, self.GPIO.HIGH)
            write_fn = getattr(self.spi, "writebytes2", self.spi.writebytes)
            for off in range(0, len(buf), 4096):
                write_fn(buf[off : off + 4096])


# ==============================================================================
# 5. ULTRASONIC SENSOR (HIGH-PRECISION PULSE TIMING)
# ==============================================================================
def ultrasonic_worker():
    """Monitors HC-SR04 using perf_counter() so microsecond pulses aren't missed."""
    if MOCK_HARDWARE:
        robot["distance_cm"] = 120.0
        return

    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(PIN_TRIG, GPIO.OUT)
        GPIO.setup(PIN_ECHO, GPIO.IN)
        GPIO.output(PIN_TRIG, GPIO.LOW)
        time.sleep(0.3)
        log.info("Ultrasonic HC-SR04 active on TRIG=GPIO%d, ECHO=GPIO%d", PIN_TRIG, PIN_ECHO)
    except Exception as e:
        log.warning("Ultrasonic GPIO init failed: %s", e)
        return

    no_echo_warned = False
    valid_count = 0

    while True:
        try:
            # 10us trigger pulse
            GPIO.output(PIN_TRIG, GPIO.HIGH)
            time.sleep(0.000012)
            GPIO.output(PIN_TRIG, GPIO.LOW)

            t0 = time.perf_counter()
            deadline = t0 + 0.035  # 35ms timeout (~600cm)

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
                dist = round(((t1 - t0) * 34300.0) / 2.0, 1)
                if 2.0 <= dist <= 400.0:
                    valid_count += 1
                    if valid_count == 1:
                        log.info("Ultrasonic first valid reading: %.1f cm", dist)
                    with state_lock:
                        robot["distance_cm"] = dist
                    if dist <= WAKE_DISTANCE_CM:
                        maybe_wake_robot(dist)
            else:
                with state_lock:
                    robot["distance_cm"] = -1.0
                if not no_echo_warned and valid_count == 0:
                    no_echo_warned = True
                    log.warning("Ultrasonic: No ECHO on GPIO%d. Ensure VCC=5V (Pin 2) and ECHO->1k/2k divider->GPIO%d!", PIN_ECHO, PIN_ECHO)
        except Exception:
            pass
        time.sleep(0.25)


def maybe_wake_robot(dist: float):
    global last_wake_time
    now = time.time()
    if robot["state"] == "idle" and (now - last_wake_time) >= COOLDOWN_SEC:
        last_wake_time = now
        log.info("Proximity wake triggered at %.1f cm!", dist)
        threading.Thread(target=run_voice_cycle, args=(True,), daemon=True).start()


# ==============================================================================
# 6. CONVERSATION PIPELINE
# ==============================================================================
def handle_reply(user_text: str, res: RobotReply, speak: bool = True):
    with state_lock:
        robot["detected_lang"] = res.detected_language
        robot["reply_native"] = res.reply_native
        robot["reply_romanized"] = res.reply_romanized
        robot["emotion"] = res.emotion
        if user_text:
            robot["messages"].append({"sender": "YOU", "text": user_text, "lang": res.detected_language})
        robot["messages"].append({"sender": "BOT", "text": res.reply_native, "en": res.reply_english, "lang": res.detected_language})
        robot["messages"] = robot["messages"][-30:]

    if speak and robot["speaker_on"]:
        with state_lock:
            robot["state"] = "speaking"
            robot["emotion"] = "speaking"
        speak_text(res.reply_native, res.detected_language)

    with state_lock:
        robot["state"] = "idle"
        robot["emotion"] = "happy"


def run_voice_cycle(from_wake: bool = False):
    if not voice_busy_lock.acquire(blocking=False):
        return
    try:
        if from_wake and robot["speaker_on"]:
            with state_lock:
                robot["state"], robot["emotion"] = "speaking", "happy"
                robot["reply_native"] = "Hello! I am listening..."
            speak_text("Hello! I am listening.", "en")

        with state_lock:
            robot["state"], robot["emotion"] = "listening", "listening"
            robot["reply_native"] = "Listening..."

        wav = record_voice(RECORD_SEC)
        if not wav:
            with state_lock:
                robot["state"], robot["emotion"] = "idle", "neutral"
                robot["reply_native"] = "No mic detected. Use Web Chat!"
            return

        with state_lock:
            robot["state"], robot["emotion"] = "thinking", "thinking"
            robot["reply_native"] = "Thinking..."

        res = ask_gemini(audio_wav=wav, lang_pref=robot["language"])
        handle_reply("[Voice Input]", res, speak=True)
    finally:
        voice_busy_lock.release()


# ==============================================================================
# 7. EMBEDDED SIMPLE WEB DASHBOARD (FLASK)
# ==============================================================================
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Easibot Simple Dashboard</title>
<style>
  body { background:#0b1120; color:#f1f5f9; font-family:system-ui,sans-serif; max-width:720px; margin:0 auto; padding:16px; }
  .card { background:#162032; border:1px solid #26334d; border-radius:12px; padding:16px; margin-bottom:14px; }
  .row { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }
  .badge { background:#0284c7; padding:4px 10px; border-radius:20px; font-size:12px; font-weight:700; text-transform:uppercase; }
  #chat { height:320px; overflow-y:auto; background:#0b1120; border:1px solid #26334d; border-radius:8px; padding:12px; margin-bottom:12px; }
  .msg { margin-bottom:10px; padding:8px 12px; border-radius:8px; max-width:85%; }
  .YOU { background:#1e3a5f; margin-left:auto; }
  .BOT { background:#1e293b; border-left:3px solid #00d4ff; }
  .sub { font-size:12px; color:#94a3b8; margin-top:4px; }
  input, select, button { padding:10px 14px; border-radius:8px; border:1px solid #334155; background:#0f172a; color:#fff; font-size:14px; }
  button { background:#00d4ff; color:#041226; font-weight:700; cursor:pointer; border:none; }
  button.mic { background:#f43f5e; color:#fff; width:100%; margin-top:8px; }
</style>
</head>
<body>
  <div class="card">
    <div class="row">
      <h2 style="margin:0">🤖 Easibot</h2>
      <span id="state" class="badge">IDLE</span>
    </div>
    <p class="sub">Distance: <b id="dist">--</b> cm | Mic: <span id="mic">--</span> | Speaker: <span id="spk">--</span></p>
    <div class="row">
      <select id="lang" onchange="setLang()">
        <option value="auto">Auto (EN / తెలుగు / हिंदी)</option>
        <option value="en">English</option>
        <option value="te">తెలుగు (Telugu)</option>
        <option value="hi">हिंदी (Hindi)</option>
      </select>
      <label><input type="checkbox" id="spkOn" checked onchange="toggleSpk()"> 🔊 Speak on Speaker</label>
    </div>
    <button class="mic" onclick="fetch('/api/listen',{method:'POST'})">🎙️ Trigger Voice Listen (USB / Bluetooth Mic)</button>
  </div>

  <div class="card">
    <div id="chat"></div>
    <form onsubmit="sendMsg(event)" class="row">
      <input id="txt" style="flex:1" placeholder="Type in English, Telugu, or Hindi..." autocomplete="off">
      <button type="submit">Send</button>
    </form>
  </div>

<script>
async function refresh() {
  const d = await (await fetch('/api/status')).json();
  document.getElementById('state').textContent = d.state;
  document.getElementById('dist').textContent = d.distance_cm > 0 ? d.distance_cm : '--';
  document.getElementById('mic').textContent = d.mic_info;
  document.getElementById('spk').textContent = d.speaker_info;
  const chat = document.getElementById('chat');
  chat.innerHTML = d.messages.map(m =>
    `<div class="msg ${m.sender}"><b>${m.sender} [${m.lang.toUpperCase()}]</b><div>${m.text}</div>` +
    (m.en && m.lang!=='en' ? `<div class="sub">EN: ${m.en}</div>` : '') + `</div>`
  ).join('');
  chat.scrollTop = chat.scrollHeight;
}
async function sendMsg(e) {
  e.preventDefault();
  const el = document.getElementById('txt'); const msg = el.value.trim(); if(!msg) return;
  el.value = '';
  await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:msg, speak:document.getElementById('spkOn').checked})});
  refresh();
}
function setLang() { fetch('/api/lang', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({lang:document.getElementById('lang').value})}); }
function toggleSpk() { fetch('/api/speaker', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({on:document.getElementById('spkOn').checked})}); }
setInterval(refresh, 1000); refresh();
</script>
</body>
</html>"""

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify(robot)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json() or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "empty"}), 400
    with state_lock:
        robot["state"], robot["emotion"] = "thinking", "thinking"
    res = ask_gemini(text_query=msg, lang_pref=robot["language"])
    threading.Thread(target=handle_reply, args=(msg, res, data.get("speak", True)), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/listen", methods=["POST"])
def api_listen():
    threading.Thread(target=run_voice_cycle, args=(False,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/lang", methods=["POST"])
def api_lang():
    robot["language"] = (request.get_json() or {}).get("lang", "auto")
    return jsonify({"ok": True})


@app.route("/api/speaker", methods=["POST"])
def api_speaker():
    robot["speaker_on"] = bool((request.get_json() or {}).get("on", True))
    return jsonify({"ok": True})


# ==============================================================================
# 8. MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    log.info("Starting Easibot Simple Edition (MOCK_HARDWARE=%s)...", MOCK_HARDWARE)

    tft = SimpleTFT()
    threading.Thread(target=ultrasonic_worker, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False), daemon=True).start()

    log.info("Web Dashboard available at http://localhost:%d", WEB_PORT)

    # Display animation loop (~5 FPS: smooth eyes, ultra-low CPU so ultrasonic never drops echoes!)
    try:
        while True:
            tft.render_and_push()
            time.sleep(0.2)
    except KeyboardInterrupt:
        log.info("Easibot stopped.")
