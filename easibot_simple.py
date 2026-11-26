"""
Easibot Simple Edition - Fast Single-File AI Multilingual Assistant Robot
========================================================================
Optimized for Raspberry Pi Zero W / Zero 2 W & Laptop Mock Mode.
Features:
  - Ultra-Fast Gemini 3.5 Flash-Lite (1-2s replies, English/Telugu/Hindi + Audio)
  - Continuous Multi-Turn Voice Chat (remembers context, auto-listens for follow-ups!)
  - Smart VAD Voice Recorder (stops 1s after you finish speaking; auto-exits on silence)
  - Auto-Switching Audio: USB Mic / Zebronics Bluetooth Neckband / Laptop Mic
  - Fast NumPy ILI9341 2.8" SPI TFT LCD (dirty-frame caching = minimal CPU lag)
  - HC-SR04 Ultrasonic Proximity Wake-Up (configurable via PIN_TRIG / PIN_ECHO in .env)
  - Embedded Flask Web Dashboard on Port 5000

Run:
  python easibot_simple.py
"""

import os
import re
import io
import sys
import json
import time
import wave
import math
import array
import shutil
import asyncio
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional, Literal

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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MOCK_HARDWARE = os.getenv("MOCK_HARDWARE", "false" if sys.platform.startswith("linux") else "true").lower() in ("1", "true", "yes")

# GPIO Pins (BCM) - customizable in .env
PIN_TRIG = int(os.getenv("PIN_TRIG", "23"))   # Default GPIO 23 (Pin 16)
PIN_ECHO = int(os.getenv("PIN_ECHO", "27"))   # Default GPIO 27 (Pin 13)
PIN_TFT_DC = 24
PIN_TFT_RST = 25
PIN_TFT_LED = 18

WAKE_DISTANCE_CM = float(os.getenv("WAKE_DISTANCE_CM", "60.0"))
COOLDOWN_SEC = float(os.getenv("ULTRASONIC_COOLDOWN_SEC", "15.0"))
MAX_RECORD_SEC = float(os.getenv("RECORD_DURATION_SEC", "7.0"))
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
    "state": "idle",
    "emotion": "happy",
    "language": os.getenv("DEFAULT_LANGUAGE", "auto"),
    "detected_lang": "en",
    "distance_cm": -1.0,
    "speaker_on": True,
    "continuous_chat": True,
    "reply_native": "Hello! I am Easibot. Ready!",
    "reply_romanized": "Hello! I am Easibot. Ready!",
    "mic_info": "Detecting...",
    "speaker_info": "Detecting...",
    "messages": [],
}
chat_history = []  # Last 8 turns for follow-up context (e.g. mitochondria -> follow-up)
last_wake_time = 0.0
voice_busy_lock = threading.Lock()


# ==============================================================================
# 2. FAST MULTILINGUAL AI ENGINE (GEMINI 3.5 FLASH-LITE + CONTEXT MEMORY)
# ==============================================================================
class RobotReply(BaseModel):
    detected_language: Literal["en", "te", "hi"] = Field(description="'en', 'te', or 'hi'")
    user_transcript: str = Field(description="Short summary/transcript of what the user asked")
    reply_native: str = Field(description="Concise 1-2 sentence reply in native script (Telugu/Hindi/English)")
    reply_english: str = Field(description="English translation of reply_native")
    reply_romanized: str = Field(description="Latin/English phonetic transliteration for TFT screen")
    emotion: Literal["happy", "thinking", "listening", "speaking", "neutral"] = Field(description="Robot expression")
    end_conversation: bool = Field(description="True ONLY if user says bye/stop/goodbye/no more questions")


SYSTEM_PROMPT = (
    "You are Easibot, a fast, friendly multilingual robot assistant on a Raspberry Pi. "
    "Understand English (en), Telugu (te), Hindi (hi), and code-mixed speech. "
    "Use the conversation history to answer follow-up questions naturally. "
    "Keep replies crisp and short (1-2 clear sentences) for fast voice TTS and a small 320x240 screen. "
    "If the audio is just silence or background noise with no speech, set user_transcript='' and end_conversation=true."
)

genai_client = None
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    try:
        from google import genai
        from google.genai import types
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        log.info("Gemini AI client ready (primary model: %s)", GEMINI_MODEL)
    except Exception as e:
        log.warning("Gemini init failed: %s", e)


def _normalize_lang(lang: str) -> str:
    l = (lang or "en").lower().strip()
    if l.startswith("te"):
        return "te"
    if l.startswith("hi"):
        return "hi"
    return "en"


def ask_gemini(text_query: Optional[str] = None, audio_wav: Optional[bytes] = None, lang_pref: str = "auto") -> RobotReply:
    """Queries fast Gemini Flash-Lite with conversation history and text or raw .wav audio."""
    if not genai_client:
        return RobotReply(
            detected_language="en", user_transcript=text_query or "",
            reply_native="API Key not set. Ready in offline mode!",
            reply_english="API Key not set.", reply_romanized="API Key not set.",
            emotion="neutral", end_conversation=False
        )

    instr = SYSTEM_PROMPT
    if lang_pref in ("en", "te", "hi"):
        instr += f" IMPORTANT: Reply strictly in language '{lang_pref}'."

    # Include last 6 turns of conversation memory for natural follow-up questions
    with state_lock:
        hist_lines = [f"{h['role']}: {h['text']}" for h in chat_history[-6:]]
    history_ctx = ("Recent conversation:\n" + "\n".join(hist_lines) + "\n\n") if hist_lines else ""

    cfg = types.GenerateContentConfig(
        system_instruction=instr,
        response_mime_type="application/json",
        response_schema=RobotReply,
        temperature=0.6,
    )

    if audio_wav:
        contents = [
            types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"),
            f"{history_ctx}Listen to the user's audio above, transcribe it, and answer naturally."
        ]
    else:
        contents = f"{history_ctx}User: {text_query}"

    models = [GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"]
    for m in dict.fromkeys(models):
        try:
            t0 = time.time()
            resp = genai_client.models.generate_content(model=m, contents=contents, config=cfg)
            log.info("Gemini (%s) replied in %.2fs", m, time.time() - t0)
            if getattr(resp, "parsed", None):
                res = resp.parsed if isinstance(resp.parsed, RobotReply) else RobotReply(**resp.parsed)
            else:
                raw = (resp.text or "{}").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                res = RobotReply(**json.loads(raw))
            res.detected_language = _normalize_lang(res.detected_language)
            return res
        except Exception as e:
            log.warning("Gemini model %s failed: %s", m, e)

    return RobotReply(
        detected_language="en", user_transcript=text_query or "",
        reply_native="Sorry, I could not reach Gemini right now.",
        reply_english="Sorry, I could not reach Gemini right now.",
        reply_romanized="Sorry, I could not reach Gemini right now.",
        emotion="neutral", end_conversation=False
    )


# ==============================================================================
# 3. SMART AUDIO: AUTO-DETECT USB MIC / BLUETOOTH NECKBAND + FAST VAD RECORDING
# ==============================================================================
_cached_mic_mode = None  # Cache detected mic for instant zero-lag follow-up listening!


def _find_usb_alsa_mic() -> Optional[str]:
    """Finds USB microphone card via 'arecord -l' -> returns 'plughw:X,Y'."""
    if not shutil.which("arecord"):
        return None
    try:
        out = subprocess.check_output(["arecord", "-l"], text=True, stderr=subprocess.DEVNULL)
        usb_cards, any_cards = [], []
        for line in out.splitlines():
            m = re.match(r"card (\d+):.*device (\d+):", line)
            if m:
                dev_str = f"plughw:{m.group(1)},{m.group(2)}"
                any_cards.append(dev_str)
                if any(k in line.lower() for k in ("usb", "pnp", "mic", "webcam", "audio")):
                    usb_cards.append(dev_str)
        return usb_cards[0] if usb_cards else (any_cards[0] if any_cards else None)
    except Exception:
        return None


def _find_bluetooth_source() -> Optional[str]:
    """Checks PipeWire/PulseAudio for Bluetooth mic (e.g. Zebronics neckband)."""
    if not shutil.which("pactl"):
        return None
    try:
        sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True, stderr=subprocess.DEVNULL)
        for s in sources.splitlines():
            if ("bluez_input" in s or "bluez_source" in s) and "monitor" not in s:
                return s.split()[1]
        cards = subprocess.check_output(["pactl", "list", "cards", "short"], text=True, stderr=subprocess.DEVNULL)
        for line in cards.splitlines():
            if "bluez_card" in line:
                card_name = line.split()[1]
                for prof in ("headset-head-unit", "headset-head-unit-msbc", "headset-head-unit-cvsd", "handsfree_head_unit"):
                    if subprocess.run(["pactl", "set-card-profile", card_name, prof], stderr=subprocess.DEVNULL).returncode == 0:
                        time.sleep(0.8)
                        sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True, stderr=subprocess.DEVNULL)
                        for s in sources.splitlines():
                            if "bluez" in s and "monitor" not in s:
                                return s.split()[1]
    except Exception:
        pass
    return None


def _chunk_rms(pcm_bytes: bytes) -> float:
    """Fast RMS audio energy calculation on 16-bit signed PCM bytes."""
    if len(pcm_bytes) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _record_raw_stream_vad(cmd: list, wait_speech_sec: float = 4.0, max_sec: float = MAX_RECORD_SEC) -> Optional[bytes]:
    """
    Streams raw 16kHz mono PCM from arecord/parecord and stops 1.0s after user stops speaking!
    Returns WAV bytes if speech was detected, or None if user stayed silent.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    chunk_bytes = 6400  # 0.2 seconds at 16000Hz * 2 bytes
    noise_samples = []
    recorded_chunks = []
    speech_started = False
    silence_chunks = 0
    max_chunks = int(max_sec / 0.2)
    wait_chunks = int(wait_speech_sec / 0.2)
    threshold = 350.0

    try:
        for idx in range(max_chunks):
            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            rms = _chunk_rms(data)

            # Calibrate background noise in first 0.4s
            if idx < 2:
                noise_samples.append(rms)
                recorded_chunks.append(data)
                threshold = max(250.0, (sum(noise_samples) / len(noise_samples)) * 2.3)
                continue

            recorded_chunks.append(data)

            if rms > threshold:
                speech_started = True
                silence_chunks = 0
            elif speech_started:
                silence_chunks += 1
                # Stop 1.0s (5 chunks) after user finishes speaking!
                if silence_chunks >= 5:
                    log.info("Speech ended cleanly at %.1fs", (idx + 1) * 0.2)
                    break
            elif idx >= wait_chunks:
                # Nobody spoke within wait window -> exit cleanly without wasting API call!
                log.info("Silence timeout (no speech detected).")
                return None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except Exception:
            proc.kill()

    if not speech_started:
        return None

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes(b"".join(recorded_chunks))
    return buf.getvalue()


def record_voice(wait_speech_sec: float = 4.0) -> Optional[bytes]:
    """Auto-detects USB Mic / Bluetooth Neckband / Laptop Mic and records with fast VAD."""
    global _cached_mic_mode

    # Try cached mic first for zero-delay follow-ups
    if _cached_mic_mode is None:
        usb_dev = _find_usb_alsa_mic()
        if usb_dev and shutil.which("arecord"):
            _cached_mic_mode = ("usb", usb_dev)
            robot["mic_info"] = f"USB Mic ({usb_dev})"
        else:
            bt_src = _find_bluetooth_source()
            if bt_src and shutil.which("parecord"):
                _cached_mic_mode = ("bt", bt_src)
                robot["mic_info"] = f"Bluetooth Mic ({bt_src[:20]})"
            elif shutil.which("parecord"):
                _cached_mic_mode = ("pa", None)
                robot["mic_info"] = "System Mic (parecord)"
            else:
                _cached_mic_mode = ("sd", None)

    mode, dev = _cached_mic_mode
    try:
        if mode == "usb":
            cmd = ["arecord", "-D", dev, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "-q"]
            return _record_raw_stream_vad(cmd, wait_speech_sec=wait_speech_sec)
        elif mode == "bt":
            cmd = ["parecord", "-d", dev, "--raw", "--rate=16000", "--channels=1", "--format=s16le"]
            return _record_raw_stream_vad(cmd, wait_speech_sec=wait_speech_sec)
        elif mode == "pa":
            cmd = ["parecord", "--raw", "--rate=16000", "--channels=1", "--format=s16le"]
            return _record_raw_stream_vad(cmd, wait_speech_sec=wait_speech_sec)
        else:
            import sounddevice as sd
            robot["mic_info"] = "Default Mic (sounddevice)"
            rec = sd.rec(int(min(4.0, MAX_RECORD_SEC) * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()
            raw = rec.tobytes()
            if _chunk_rms(raw) < 120.0:
                return None
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(raw)
            return buf.getvalue()
    except Exception as e:
        log.warning("Mic recording error (%s) — resetting mic cache.", e)
        _cached_mic_mode = None
        robot["mic_info"] = "No Mic Found"
        return None


def play_ready_beep():
    """Plays a super quick 0.12s soft chime so user knows robot is listening for next question."""
    if not robot["speaker_on"]:
        return
    beep_path = TEMP_DIR / "ready_beep.wav"
    if not beep_path.exists():
        # Generate tiny 0.12s 587Hz chime once and cache on disk
        frames = bytearray()
        for i in range(int(16000 * 0.12)):
            env = math.sin(math.pi * i / (16000 * 0.12))
            val = int(6000.0 * env * math.sin(2.0 * math.pi * 587.0 * i / 16000))
            frames.extend(val.to_bytes(2, "little", signed=True))
        with wave.open(str(beep_path), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(frames)

    if sys.platform.startswith("linux"):
        for cmd in (["pw-play", str(beep_path)], ["paplay", str(beep_path)], ["aplay", "-q", str(beep_path)]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
    elif sys.platform.startswith("win"):
        subprocess.run(["powershell", "-c", f"(New-Object Media.SoundPlayer '{beep_path}').PlaySync()"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def speak_text(text: str, lang: str = "en"):
    """Synthesizes TTS (edge-tts -> gTTS fallback) and plays on best available speaker."""
    if not text.strip() or not robot["speaker_on"]:
        return

    mp3_path = TEMP_DIR / f"tts_{int(time.time()*1000)}.mp3"
    voice = TTS_VOICES.get(lang, TTS_VOICES["en"])
    synthesized = False

    try:
        import edge_tts
        async def _synth():
            await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(mp3_path)), timeout=6.0)
        asyncio.run(_synth())
        synthesized = mp3_path.exists() and mp3_path.stat().st_size > 300
    except Exception as e:
        log.warning("edge-tts failed (%s), using gTTS fallback...", e)

    if not synthesized:
        try:
            from gtts import gTTS
            gTTS(text=text, lang=lang if lang in ("en", "te", "hi") else "en").save(str(mp3_path))
            synthesized = mp3_path.exists() and mp3_path.stat().st_size > 300
        except Exception as e:
            log.error("gTTS failed: %s", e)

    if not synthesized:
        return

    try:
        if sys.platform.startswith("linux"):
            if shutil.which("pactl") and robot["speaker_info"] == "Detecting...":
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
# 4. ZERO-LAG 2.8" SPI TFT DISPLAY (DIRTY-FRAME CACHING + NUMPY)
# ==============================================================================
class SimpleTFT:
    def __init__(self):
        self.spi = None
        self.GPIO = None
        self.mock = MOCK_HARDWARE
        self.font_sm = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 13)
        self.font_md = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 16)
        self.tick = 0
        self._last_signature = None

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
        for d in [BASE_DIR / "assets" / "fonts", Path("/usr/share/fonts/truetype/noto"), Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts")]:
            for n in names:
                p = d / n
                if p.exists():
                    try:
                        return ImageFont.truetype(str(p), size)
                    except Exception:
                        pass
        return ImageFont.load_default()

    def _cmd(self, c):
        self.GPIO.output(PIN_TFT_DC, self.GPIO.LOW); self.spi.writebytes([c])

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
            if data: self._dat(data)
            if cmd in (0x01, 0x11): time.sleep(0.12)

    def render_and_push(self, force: bool = False):
        self.tick += 1
        with state_lock:
            st, emo = robot["state"], robot["emotion"]
            dist, lang = robot["distance_cm"], robot["detected_lang"]
            txt = robot["reply_native"] if lang == "en" else (robot["reply_romanized"] or robot["reply_native"])

        blink = 1 if (self.tick % 12 == 0 and st == "idle") else 0
        bounce = (self.tick % 2) if st == "speaking" else 0
        sig = (st, emo, txt, int(dist // 4) if dist > 0 else -1, lang, blink, bounce)

        # Skip redraw if nothing changed -> saves 90% CPU for voice & Gemini!
        if not force and sig == self._last_signature:
            return
        self._last_signature = sig

        img = Image.new("RGB", (320, 240), (12, 16, 28))
        d = ImageDraw.Draw(img)

        d.rectangle([(0, 0), (320, 26)], fill=(22, 28, 44))
        d.text((10, 6), st.upper(), fill=EMOTION_COLORS.get(emo, (0, 212, 255)), font=self.font_sm)
        d.text((135, 6), f"[{lang.upper()}]", fill=(0, 212, 255), font=self.font_sm)
        d.text((225, 6), f"{int(dist)}cm" if dist > 0 else "-- cm", fill=(160, 174, 192), font=self.font_sm)

        color = EMOTION_COLORS.get(emo, (0, 212, 255))
        dy = -4 if bounce else 0
        h = 10 if blink else 54
        for cx in (95, 225):
            if emo == "happy" and not blink:
                d.arc([cx - 30, 65, cx + 30, 125], start=190, end=350, fill=color, width=7)
            else:
                d.rounded_rectangle([cx - 30, 92 - h // 2 + dy, cx + 30, 92 + h // 2 + dy], radius=14, fill=color)
                if not blink:
                    d.ellipse([cx + 10, 92 - h // 2 + 8 + dy, cx + 18, 92 - h // 2 + 16 + dy], fill=(255, 255, 255))

        d.rounded_rectangle([(10, 160), (310, 232)], radius=8, fill=(22, 28, 44), outline=(45, 55, 72))
        words, lines, cur = txt.split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 <= 34:
                cur = f"{cur} {w}".strip()
            else:
                lines.append(cur); cur = w
        if cur: lines.append(cur)
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
    if MOCK_HARDWARE:
        robot["distance_cm"] = 120.0
        return

    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
        GPIO.setup(PIN_TRIG, GPIO.OUT); GPIO.setup(PIN_ECHO, GPIO.IN)
        GPIO.output(PIN_TRIG, GPIO.LOW)
        time.sleep(0.3)
        log.info("Ultrasonic HC-SR04 active on TRIG=GPIO%d, ECHO=GPIO%d", PIN_TRIG, PIN_ECHO)
    except Exception as e:
        log.warning("Ultrasonic GPIO init failed: %s", e)
        return

    no_echo_warned, valid_count = False, 0

    while True:
        # Pause pinging during active conversation to keep 100% CPU free for voice/AI
        if robot["state"] != "idle":
            time.sleep(0.5)
            continue

        try:
            GPIO.output(PIN_TRIG, GPIO.HIGH)
            time.sleep(0.000012)
            GPIO.output(PIN_TRIG, GPIO.LOW)

            t0 = time.perf_counter()
            deadline = t0 + 0.035

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
                    log.warning("Ultrasonic: No ECHO on GPIO%d. Check 5V VCC & 1k/2k divider!", PIN_ECHO)
        except Exception:
            pass
        time.sleep(0.3)


def maybe_wake_robot(dist: float):
    global last_wake_time
    now = time.time()
    if robot["state"] == "idle" and (now - last_wake_time) >= COOLDOWN_SEC:
        last_wake_time = now
        log.info("Proximity wake triggered at %.1f cm!", dist)
        threading.Thread(target=run_voice_cycle, args=(True,), daemon=True).start()


# ==============================================================================
# 6. CONTINUOUS MULTI-TURN CONVERSATION PIPELINE
# ==============================================================================
def handle_reply(user_text: str, res: RobotReply, speak: bool = True):
    u_txt = user_text or res.user_transcript or "[Voice]"
    with state_lock:
        robot["detected_lang"] = res.detected_language
        robot["reply_native"] = res.reply_native
        robot["reply_romanized"] = res.reply_romanized
        robot["emotion"] = res.emotion
        chat_history.append({"role": "User", "text": u_txt})
        chat_history.append({"role": "Easibot", "text": res.reply_english})
        if len(chat_history) > 12:
            del chat_history[:-12]

        robot["messages"].append({"sender": "YOU", "text": u_txt, "lang": res.detected_language})
        robot["messages"].append({"sender": "BOT", "text": res.reply_native, "en": res.reply_english, "lang": res.detected_language})
        robot["messages"] = robot["messages"][-30:]

    if speak and robot["speaker_on"]:
        with state_lock:
            robot["state"], robot["emotion"] = "speaking", "speaking"
        speak_text(res.reply_native, res.detected_language)


def run_voice_cycle(from_wake: bool = False):
    """Continuous multi-turn chat loop: listens -> answers -> speaks -> immediately listens for follow-up!"""
    global last_wake_time
    if not voice_busy_lock.acquire(blocking=False):
        return

    try:
        turn = 0
        while True:
            turn += 1
            if turn == 1 and from_wake and robot["speaker_on"]:
                with state_lock:
                    robot["state"], robot["emotion"] = "speaking", "happy"
                    robot["reply_native"] = "Hi! Ask me anything."
                speak_text("Hi! Ask me anything.", "en")
            else:
                play_ready_beep()

            with state_lock:
                robot["state"], robot["emotion"] = "listening", "listening"
                robot["reply_native"] = "Listening..." if turn == 1 else "Listening for next question..."

            # Wait up to 4.5s for speech to begin; if silent, exit continuous chat gracefully
            wav = record_voice(wait_speech_sec=4.5)
            if not wav:
                with state_lock:
                    robot["state"], robot["emotion"] = "idle", "happy"
                    robot["reply_native"] = "Ready! Ask anytime." if turn > 1 else "No speech heard."
                break

            with state_lock:
                robot["state"], robot["emotion"] = "thinking", "thinking"
                robot["reply_native"] = "Thinking..."

            res = ask_gemini(audio_wav=wav, lang_pref=robot["language"])
            if not res.user_transcript.strip() and res.end_conversation:
                with state_lock:
                    robot["state"], robot["emotion"] = "idle", "happy"
                    robot["reply_native"] = "Ready! Ask anytime."
                break

            handle_reply(res.user_transcript, res, speak=True)

            # Stop loop if user said bye or continuous chat disabled
            if res.end_conversation or not robot["continuous_chat"]:
                with state_lock:
                    robot["state"], robot["emotion"] = "idle", "happy"
                break

        last_wake_time = time.time()
    finally:
        with state_lock:
            if robot["state"] in ("listening", "thinking", "speaking"):
                robot["state"], robot["emotion"] = "idle", "happy"
        voice_busy_lock.release()


# ==============================================================================
# 7. EMBEDDED SIMPLE WEB DASHBOARD (FLASK)
# ==============================================================================
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Easibot Fast Dashboard</title>
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
  button.mic { background:#f43f5e; color:#fff; width:100%; margin-top:10px; }
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
      <label><input type="checkbox" id="spkOn" checked onchange="toggleSpk()"> 🔊 Speaker</label>
      <label><input type="checkbox" id="contOn" checked onchange="toggleCont()"> 🔁 Continuous Chat</label>
    </div>
    <button class="mic" onclick="fetch('/api/listen',{method:'POST'})">🎙️ Start Continuous Voice Chat</button>
  </div>

  <div class="card">
    <div id="chat"></div>
    <form onsubmit="sendMsg(event)" class="row">
      <input id="txt" style="flex:1" placeholder="Ask anything (follow-ups remembered!)..." autocomplete="off">
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
function toggleCont() { fetch('/api/continuous', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({on:document.getElementById('contOn').checked})}); }
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
    def _finish():
        handle_reply(msg, res, data.get("speak", True))
        with state_lock:
            robot["state"], robot["emotion"] = "idle", "happy"
    threading.Thread(target=_finish, daemon=True).start()
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


@app.route("/api/continuous", methods=["POST"])
def api_continuous():
    robot["continuous_chat"] = bool((request.get_json() or {}).get("on", True))
    return jsonify({"ok": True})


# ==============================================================================
# 8. MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    log.info("Starting Easibot Fast Edition (Model=%s, MOCK=%s, TRIG=GPIO%d, ECHO=GPIO%d)...", GEMINI_MODEL, MOCK_HARDWARE, PIN_TRIG, PIN_ECHO)

    tft = SimpleTFT()
    tft.render_and_push(force=True)
    threading.Thread(target=ultrasonic_worker, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False), daemon=True).start()

    log.info("Web Dashboard available at http://localhost:%d", WEB_PORT)

    try:
        while True:
            tft.render_and_push()
            time.sleep(0.35)
    except KeyboardInterrupt:
        log.info("Easibot stopped.")
