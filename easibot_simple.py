"""
Easibot Simple Edition - Fast Single-File AI Multilingual Assistant Robot
========================================================================
Optimized for Raspberry Pi Zero W / Zero 2 W & Laptop Mock Mode.
Features:
  - Ultra-Fast Gemini 3.5 Flash-Lite (1-2s replies, English/Telugu/Hindi + Audio)
  - Instant Predefined Commands & Study Concepts (0ms local reply for greetings, diode, resistor, raspberry pi, etc.)
  - Response-Based Dynamic TFT UI Screen:
      * Idle / Listening / Thinking -> Big Animated Robot Eyes + Countdown Bar
      * Speaking / Answer Hold      -> Compact Header + Full-Screen Auto-Wrapped Response Card
  - Ultrasonic Interrupt: Wave near HC-SR04 while thinking/speaking to interrupt & listen instantly
  - Continuous Multi-Turn Voice Chat (remembers context, auto-listens for follow-ups)
  - Auto-Switching Audio: USB Mic / Zebronics Bluetooth Neckband / Laptop Mic + PipeWire/Pulse Speaker Fix
  - Embedded Flask Web Dashboard on Port 5000 (with Test Speaker button & TFT Mirror)

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
from flask import Flask, request, jsonify, render_template_string, Response
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
INTERRUPT_DISTANCE_CM = float(os.getenv("INTERRUPT_DISTANCE_CM", "35.0"))
COOLDOWN_SEC = float(os.getenv("ULTRASONIC_COOLDOWN_SEC", "15.0"))
LISTEN_TIMEOUT_SEC = float(os.getenv("LISTEN_TIMEOUT_SEC", "5.0"))
MAX_RECORD_SEC = float(os.getenv("RECORD_DURATION_SEC", "7.0"))
RESPONSE_HOLD_SEC = 8.0
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

TEMP_DIR = BASE_DIR / "temp_audio"
TEMP_DIR.mkdir(exist_ok=True)

TTS_VOICES = {"en": "en-IN-NeerjaNeural", "te": "te-IN-ShrutiNeural", "hi": "hi-IN-SwaraNeural"}
EMOTION_COLORS = {
    "neutral": (0, 212, 255), "happy": (72, 239, 128),
    "listening": (56, 189, 248), "thinking": (245, 158, 11),
    "speaking": (168, 85, 247), "error": (239, 68, 68),
}

# Global Thread-Safe Robot State & Interrupt Control
state_lock = threading.Lock()
robot = {
    "state": "idle",
    "emotion": "happy",
    "language": os.getenv("DEFAULT_LANGUAGE", "auto"),
    "detected_lang": "en",
    "distance_cm": -1.0,
    "speaker_on": True,
    "continuous_chat": True,
    "last_question": "",
    "reply_native": "Hello! I am Easibot. Ready!",
    "reply_romanized": "Hello! I am Easibot. Ready!",
    "response_hold_until": 0.0,
    "listen_remaining": 0.0,
    "listen_total": LISTEN_TIMEOUT_SEC,
    "speech_active": False,
    "mic_info": "Detecting...",
    "speaker_info": "Detecting...",
    "messages": [],
}
chat_history = []

active_gen_id = 0
last_wake_time = 0.0
interrupt_armed_at = 0.0
active_audio_proc: Optional[subprocess.Popen] = None
active_rec_proc: Optional[subprocess.Popen] = None
proc_lock = threading.Lock()


def interrupt_now(reason: str = "Interrupt"):
    """Instantly stops active TTS playback, recording, and invalidates in-flight AI calls."""
    global active_gen_id, active_audio_proc, active_rec_proc
    with state_lock:
        active_gen_id += 1
    with proc_lock:
        for p in (active_audio_proc, active_rec_proc):
            if p and p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        active_audio_proc = None
        active_rec_proc = None
    log.info("⚡ %s triggered! Cancelled current task (gen_id=%d).", reason, active_gen_id)


# ==============================================================================
# 2. PREDEFINED INSTANT COMMANDS & STUDY CONCEPTS (0ms LOCAL REPLIES)
# ==============================================================================
PREDEFINED_CONCEPTS = {
    ("hi", "hello", "hallo", "hii", "hey", "helo"): (
        "en", "Hello! I am Easibot. What would you like to learn or ask today?", "happy", False
    ),
    ("whatsup", "whats up", "whattup", "watup", "sup"): (
        "en", "All good and ready to help! Ask me anything or test a study topic.", "happy", False
    ),
    ("how are you", "how r u", "how do you do"): (
        "en", "I am running smoothly and feeling great! How can I help you?", "happy", False
    ),
    ("good morning",): (
        "en", "Good morning! Hope you have a productive day ahead. What can I help with?", "happy", False
    ),
    ("good evening",): (
        "en", "Good evening! Ready to assist you with any questions.", "happy", False
    ),
    ("who are you", "what is your name", "your name"): (
        "en", "I am Easibot, your multilingual AI assistant robot powered by Raspberry Pi and Gemini!", "happy", False
    ),
    ("namaskaram", "ela unnav", "ela unnavu"): (
        "te", "నమస్కారం! నేను చాలా బాగున్నాను. మీకు ఎలా సహాయపడగలను?", "happy", False
    ),
    ("namaste", "kaise ho", "kya haal hai"): (
        "hi", "नमस्ते! मैं बिल्कुल ठीक हूँ। बताइए, मैं आपकी क्या मदद कर सकता हूँ?", "happy", False
    ),
    ("bye", "goodbye", "stop", "exit", "thank you bye", "ok bye"): (
        "en", "Goodbye! Wave near my sensor whenever you need me again.", "happy", True
    ),
    ("thanks", "thank you", "thank u"): (
        "en", "You're very welcome! Do you have another question?", "happy", False
    ),
    ("diode",): (
        "en", "A diode is a two-terminal semiconductor component that lets electric current flow in only one direction, acting like a one-way valve.", "speaking", False
    ),
    ("resistor", "resister"): (
        "en", "A resistor is a passive component that opposes and controls electric current in a circuit, measured in Ohms.", "speaking", False
    ),
    ("capacitor",): (
        "en", "A capacitor stores electrical energy temporarily in an electric field and releases it when needed to smooth voltage.", "speaking", False
    ),
    ("transistor",): (
        "en", "A transistor is a semiconductor device used either to amplify weak electrical signals or to act as a fast electronic switch.", "speaking", False
    ),
    ("led",): (
        "en", "An LED, or Light Emitting Diode, is a special diode that glows and emits light when current flows forward through it.", "speaking", False
    ),
    ("raspberry", "raspberry pi", "rasberry"): (
        "en", "Raspberry Pi is a compact, credit-card-sized single-board computer used for coding, robotics, IoT, and AI projects like me!", "happy", False
    ),
    ("arduino",): (
        "en", "Arduino is an open-source microcontroller platform built for reading sensors, controlling motors, and rapid electronics prototyping.", "speaking", False
    ),
    ("ultrasonic", "hc-sr04", "hcsr04"): (
        "en", "An ultrasonic sensor measures distance by sending high-frequency sound waves and timing how fast the echo bounces back.", "speaking", False
    ),
    ("mitochondria", "mitocandra", "mitrocandra", "mitocondria", "mitochondrion"): (
        "en", "Mitochondria are the powerhouse of the cell because they convert nutrients into ATP, the chemical energy cells need.", "speaking", False
    ),
    ("ohms law", "ohm's law", "ohm law"): (
        "en", "Ohm's Law states that Voltage equals Current multiplied by Resistance, written as V equals I times R.", "speaking", False
    ),
}


class RobotReply(BaseModel):
    detected_language: Literal["en", "te", "hi"] = Field(description="'en', 'te', or 'hi'")
    user_transcript: str = Field(description="Short summary/transcript of what the user asked")
    reply_native: str = Field(description="Concise 1-2 sentence reply in native script (Telugu/Hindi/English)")
    reply_english: str = Field(description="English translation of reply_native")
    reply_romanized: str = Field(description="Latin/English phonetic transliteration for TFT screen")
    emotion: Literal["happy", "thinking", "listening", "speaking", "neutral"] = Field(description="Robot expression")
    end_conversation: bool = Field(description="True ONLY if user says bye/stop/goodbye/no more questions")


def match_predefined(query: str, lang_pref: str = "auto") -> Optional[RobotReply]:
    clean = re.sub(r"[^\w\s']", " ", (query or "").lower()).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return None
    words = set(clean.split())
    for keys, (lang, text, emo, end_conv) in PREDEFINED_CONCEPTS.items():
        if lang_pref in ("te", "hi") and lang != lang_pref:
            continue
        for k in keys:
            if clean == k or (len(words) <= 6 and (f" {k} " in f" {clean} " or clean.endswith(f" {k}"))):
                return RobotReply(
                    detected_language=lang, user_transcript=query.strip(),
                    reply_native=text, reply_english=text, reply_romanized=text,
                    emotion=emo, end_conversation=end_conv
                )
    return None


# ==============================================================================
# 3. FAST MULTILINGUAL AI ENGINE (GEMINI 3.5 FLASH-LITE + CONTEXT MEMORY)
# ==============================================================================
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
    return "te" if l.startswith("te") else ("hi" if l.startswith("hi") else "en")


def ask_gemini(text_query: Optional[str] = None, audio_wav: Optional[bytes] = None, lang_pref: str = "auto", gen_id: int = 0) -> Optional[RobotReply]:
    if text_query:
        instant = match_predefined(text_query, lang_pref)
        if instant:
            log.info("⚡ Predefined instant reply matched for: '%s'", text_query)
            return instant

    if not genai_client:
        return RobotReply(
            detected_language="en", user_transcript=text_query or "",
            reply_native="API Key not set. Predefined study commands work offline!",
            reply_english="API Key not set.", reply_romanized="API Key not set.",
            emotion="neutral", end_conversation=False
        )

    instr = SYSTEM_PROMPT
    if lang_pref in ("en", "te", "hi"):
        instr += f" IMPORTANT: Reply strictly in language '{lang_pref}'."

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
        if gen_id and gen_id != active_gen_id:
            return None
        try:
            t0 = time.time()
            resp = genai_client.models.generate_content(model=m, contents=contents, config=cfg)
            if gen_id and gen_id != active_gen_id:
                return None
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
# 4. SMART AUDIO: AUTO-DETECT USB MIC / BLUETOOTH + RELIABLE SPEAKER ROUTING
# ==============================================================================
_cached_mic_mode = None


def _find_usb_alsa_mic() -> Optional[str]:
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


def _ensure_linux_speaker_ready():
    """Ensures Bluetooth or USB/ALSA sink is selected, unmuted, and at 100% volume."""
    if not sys.platform.startswith("linux"):
        return
    if shutil.which("pactl"):
        try:
            sinks = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True, stderr=subprocess.DEVNULL)
            lines = [l.split()[1] for l in sinks.splitlines() if len(l.split()) >= 2]
            bt_sinks = [s for s in lines if "bluez" in s]
            target = bt_sinks[0] if bt_sinks else (lines[0] if lines else None)
            if target:
                subprocess.run(["pactl", "set-default-sink", target], stderr=subprocess.DEVNULL)
                subprocess.run(["pactl", "set-sink-mute", target, "0"], stderr=subprocess.DEVNULL)
                subprocess.run(["pactl", "set-sink-volume", target, "100%"], stderr=subprocess.DEVNULL)
                robot["speaker_info"] = f"Bluetooth ({target[:18]})" if bt_sinks else f"System ({target[:18]})"
                return
        except Exception:
            pass
    robot["speaker_info"] = "ALSA Speaker"


def _chunk_rms(pcm_bytes: bytes) -> float:
    if len(pcm_bytes) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


def _record_raw_stream_vad(cmd: list, wait_speech_sec: float = LISTEN_TIMEOUT_SEC, max_sec: float = MAX_RECORD_SEC, gen_id: int = 0) -> Optional[bytes]:
    global active_rec_proc
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    with proc_lock:
        active_rec_proc = proc

    chunk_bytes = 6400
    noise_samples, recorded_chunks = [], []
    speech_started, silence_chunks = False, 0
    max_chunks = int(max_sec / 0.2)
    wait_chunks = int(wait_speech_sec / 0.2)
    threshold = 350.0

    with state_lock:
        robot["listen_total"] = wait_speech_sec
        robot["listen_remaining"] = wait_speech_sec
        robot["speech_active"] = False

    try:
        for idx in range(max_chunks):
            if gen_id and gen_id != active_gen_id:
                return None

            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            rms = _chunk_rms(data)

            elapsed = (idx + 1) * 0.2
            with state_lock:
                if not speech_started:
                    robot["listen_total"] = wait_speech_sec
                    robot["listen_remaining"] = max(0.0, round(wait_speech_sec - elapsed, 1))
                else:
                    robot["listen_total"] = max_sec
                    robot["listen_remaining"] = max(0.0, round(max_sec - elapsed, 1))

            if idx < 2:
                noise_samples.append(rms)
                recorded_chunks.append(data)
                threshold = max(240.0, (sum(noise_samples) / len(noise_samples)) * 2.2)
                continue

            recorded_chunks.append(data)

            if rms > threshold:
                if not speech_started:
                    speech_started = True
                    with state_lock:
                        robot["speech_active"] = True
                silence_chunks = 0
            elif speech_started:
                silence_chunks += 1
                if silence_chunks >= 5:
                    log.info("Speech ended cleanly at %.1fs", elapsed)
                    break
            elif idx >= wait_chunks:
                log.info("Listening timeout (%.1fs elapsed, no speech).", wait_speech_sec)
                return None
    finally:
        with proc_lock:
            if active_rec_proc == proc:
                active_rec_proc = None
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


def record_voice(wait_speech_sec: float = LISTEN_TIMEOUT_SEC, gen_id: int = 0) -> Optional[bytes]:
    global _cached_mic_mode

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
            return _record_raw_stream_vad(["arecord", "-D", dev, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "-q"], wait_speech_sec, gen_id=gen_id)
        elif mode == "bt":
            return _record_raw_stream_vad(["parecord", "-d", dev, "--raw", "--rate=16000", "--channels=1", "--format=s16le"], wait_speech_sec, gen_id=gen_id)
        elif mode == "pa":
            return _record_raw_stream_vad(["parecord", "--raw", "--rate=16000", "--channels=1", "--format=s16le"], wait_speech_sec, gen_id=gen_id)
        else:
            import sounddevice as sd
            robot["mic_info"] = "Default Mic (sounddevice)"
            rec_sec = min(wait_speech_sec, MAX_RECORD_SEC)
            with state_lock:
                robot["listen_total"] = rec_sec
                robot["listen_remaining"] = rec_sec
                robot["speech_active"] = False
            rec = sd.rec(int(rec_sec * 16000), samplerate=16000, channels=1, dtype="int16")
            start = time.time()
            while time.time() - start < rec_sec:
                if gen_id and gen_id != active_gen_id:
                    sd.stop()
                    return None
                with state_lock:
                    robot["listen_remaining"] = max(0.0, round(rec_sec - (time.time() - start), 1))
                time.sleep(0.25)
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
    if not robot["speaker_on"]:
        return
    beep_path = TEMP_DIR / "ready_beep.wav"
    if not beep_path.exists():
        frames = bytearray()
        for i in range(int(16000 * 0.12)):
            env = math.sin(math.pi * i / (16000 * 0.12))
            val = int(6000.0 * env * math.sin(2.0 * math.pi * 587.0 * i / 16000))
            frames.extend(val.to_bytes(2, "little", signed=True))
        with wave.open(str(beep_path), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(frames)

    if sys.platform.startswith("linux"):
        _ensure_linux_speaker_ready()
        for cmd in (["pw-play", str(beep_path)], ["paplay", str(beep_path)], ["aplay", "-q", str(beep_path)]):
            if shutil.which(cmd[0]) and subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
    elif sys.platform.startswith("win"):
        subprocess.run(["powershell", "-c", f"(New-Object Media.SoundPlayer '{beep_path}').PlaySync()"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run_player_checked(cmd: list, gen_id: int = 0) -> bool:
    """Runs audio player subprocess and returns True ONLY if exit code == 0."""
    global active_audio_proc
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with proc_lock:
            active_audio_proc = proc
        _, err = proc.communicate()
        with proc_lock:
            if active_audio_proc == proc:
                active_audio_proc = None
        if gen_id and gen_id != active_gen_id:
            return True  # Interrupted cleanly
        if proc.returncode == 0:
            return True
        log.warning("Player %s failed (code %d): %s", cmd[0], proc.returncode, (err or b"").decode(errors="ignore")[:120])
        return False
    except Exception as e:
        log.warning("Player %s exception: %s", cmd[0], e)
        return False


def speak_text(text: str, lang: str = "en", gen_id: int = 0):
    """Synthesizes TTS (edge-tts -> gTTS -> espeak) and reliably plays via Pulse/PipeWire/ALSA."""
    if not text.strip() or not robot["speaker_on"]:
        return
    if gen_id and gen_id != active_gen_id:
        return

    log.info("🔊 Speaking [%s]: %s", lang, text[:60])
    mp3_path = TEMP_DIR / f"tts_{int(time.time()*1000)}.mp3"
    wav_path = TEMP_DIR / f"tts_{int(time.time()*1000)}.wav"
    voice = TTS_VOICES.get(lang, TTS_VOICES["en"])
    synthesized = False

    # 1. Try edge-tts
    try:
        import edge_tts
        async def _synth():
            await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(mp3_path)), timeout=6.0)
        asyncio.run(_synth())
        synthesized = mp3_path.exists() and mp3_path.stat().st_size > 300
    except Exception as e:
        log.warning("edge-tts failed (%s), trying gTTS...", e)

    # 2. Try gTTS fallback
    if not synthesized:
        try:
            from gtts import gTTS
            gTTS(text=text, lang=lang if lang in ("en", "te", "hi") else "en").save(str(mp3_path))
            synthesized = mp3_path.exists() and mp3_path.stat().st_size > 300
        except Exception as e:
            log.warning("gTTS failed (%s)", e)

    if gen_id and gen_id != active_gen_id:
        mp3_path.unlink(missing_ok=True)
        return

    try:
        if sys.platform.startswith("linux"):
            _ensure_linux_speaker_ready()
            played = False

            if synthesized:
                # Decode MP3 -> WAV using mpg123/ffmpeg and play via pw-play/paplay (100% PipeWire Bluetooth compatible!)
                if shutil.which("mpg123"):
                    if subprocess.run(["mpg123", "-q", "-w", str(wav_path), str(mp3_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 and wav_path.exists():
                        for cmd in (["pw-play", str(wav_path)], ["paplay", str(wav_path)], ["aplay", "-q", str(wav_path)]):
                            if shutil.which(cmd[0]) and _run_player_checked(cmd, gen_id):
                                played = True
                                break

                # Fallback direct MP3 players (try PulseAudio output before ALSA)
                if not played:
                    for cmd in (
                        ["mpg123", "-o", "pulse", "-q", str(mp3_path)],
                        ["mpg123", "-q", str(mp3_path)],
                        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3_path)],
                        ["cvlc", "--play-and-exit", "--quiet", str(mp3_path)],
                    ):
                        if shutil.which(cmd[0]) and _run_player_checked(cmd, gen_id):
                            played = True
                            break

            # Ultimate offline fallback: espeak-ng / espeak
            if not played:
                for esp in ("espeak-ng", "espeak"):
                    if shutil.which(esp):
                        _run_player_checked([esp, text], gen_id)
                        break

        elif sys.platform.startswith("win") and synthesized:
            robot["speaker_info"] = "Windows Speaker"
            if shutil.which("ffplay") and _run_player_checked(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3_path)], gen_id):
                pass
            else:
                ps = f"$w=New-Object -ComObject WMPlayer.OCX;$w.URL='{mp3_path}';$w.controls.play();while($w.playState -ne 1){{Start-Sleep -Milliseconds 100}}"
                subprocess.run(["powershell", "-c", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        mp3_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)


# ==============================================================================
# 5. RESPONSE-BASED DYNAMIC 2.8" SPI TFT DISPLAY (320x240)
# ==============================================================================
class SimpleTFT:
    def __init__(self):
        self.spi = None
        self.GPIO = None
        self.mock = MOCK_HARDWARE
        self.font_xs = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 11)
        self.font_sm = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 13)
        self.font_md = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 15)
        self.font_lg = self._load_font(["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"], 17)
        self.tick = 0
        self._last_signature = None
        self.last_image: Optional[Image.Image] = None

        if not self.mock:
            try:
                import spidev, RPi.GPIO as GPIO
                self.GPIO = GPIO
                GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
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

    def _wrap_text(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int, max_lines: int) -> list:
        words = (text or "").split()
        lines, cur = [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            try:
                tw = draw.textbbox((0, 0), test, font=font)[2]
            except Exception:
                tw = len(test) * 8
            if tw <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:-3] + "..." if len(lines[-1]) > 3 else "..."
        return lines or [""]

    def render_and_push(self, force: bool = False):
        self.tick += 1
        now = time.time()
        with state_lock:
            st, emo = robot["state"], robot["emotion"]
            dist, lang = robot["distance_cm"], robot["detected_lang"]
            q_txt = robot["last_question"]
            txt = robot["reply_native"] if lang == "en" else (robot["reply_romanized"] or robot["reply_native"])
            hold_resp = (st == "speaking") or (st == "idle" and now < robot["response_hold_until"])
            rem = int(math.ceil(robot["listen_remaining"])) if st == "listening" else 0
            tot = max(1.0, robot["listen_total"])
            speech_act = robot["speech_active"]

        mode = "response" if hold_resp else "face"
        blink = 1 if (mode == "face" and self.tick % 12 == 0 and st == "idle") else 0
        pulse = (self.tick % 2) if st == "speaking" else 0
        sig = (mode, st, emo, txt, q_txt, int(dist // 4) if dist > 0 else -1, lang, blink, pulse, rem, speech_act)

        if not force and sig == self._last_signature:
            return
        self._last_signature = sig

        img = Image.new("RGB", (320, 240), (12, 16, 28))
        d = ImageDraw.Draw(img)
        accent = EMOTION_COLORS.get(emo, (0, 212, 255))

        # Top Status Bar
        d.rectangle([(0, 0), (320, 28)], fill=(22, 28, 44))
        d.line([(0, 28), (320, 28)], fill=(45, 55, 72), width=1)

        if mode == "response":
            # Compact mini-robot eyes badge on top-left when displaying full response screen!
            eye_h = 8 if pulse else 12
            d.rounded_rectangle([(8, 14 - eye_h // 2), (16, 14 + eye_h // 2)], radius=3, fill=accent)
            d.rounded_rectangle([(20, 14 - eye_h // 2), (28, 14 + eye_h // 2)], radius=3, fill=accent)
            d.text((36, 7), "SPEAKING" if st == "speaking" else "ANSWER", fill=accent, font=self.font_sm)
        else:
            d.ellipse([(10, 9), (18, 17)], fill=accent)
            d.text((24, 7), st.upper(), fill=accent, font=self.font_sm)

        d.text((140, 7), f"[{lang.upper()}]", fill=(0, 212, 255), font=self.font_sm)
        d.text((245, 7), f"{int(dist)}cm" if dist > 0 else "-- cm", fill=(160, 174, 192), font=self.font_sm)

        if mode == "response":
            # --- RESPONSE-BASED UI SCREEN (Full-screen clean reading layout!) ---
            y_cursor = 34
            if q_txt:
                q_short = q_txt if len(q_txt) <= 42 else q_txt[:39] + "..."
                d.rounded_rectangle([(10, y_cursor), (310, y_cursor + 22)], radius=6, fill=(18, 25, 42))
                d.text((18, y_cursor + 4), f"Q: {q_short}", fill=(148, 163, 184), font=self.font_xs)
                y_cursor += 28

            # Spacious Response Card filling the rest of the screen
            d.rounded_rectangle([(10, y_cursor), (310, 232)], radius=10, fill=(22, 28, 44), outline=accent, width=2)

            # Auto-pick font size based on response length so the full answer fits cleanly!
            if len(txt) <= 85:
                fnt, line_h, max_l = self.font_lg, 24, 6
            elif len(txt) <= 155:
                fnt, line_h, max_l = self.font_md, 20, 7
            else:
                fnt, line_h, max_l = self.font_sm, 17, 9

            lines = self._wrap_text(d, txt, fnt, max_w=278, max_lines=max_l)
            ty = y_cursor + 10
            for line in lines:
                d.text((20, ty), line, fill=(255, 255, 255), font=fnt)
                ty += line_h
        else:
            # --- FACE-BASED UI SCREEN (Idle / Listening / Thinking) ---
            h = 10 if blink else 54
            for cx in (95, 225):
                if emo == "happy" and not blink:
                    d.arc([cx - 30, 65, cx + 30, 125], start=190, end=350, fill=accent, width=7)
                else:
                    d.rounded_rectangle([cx - 30, 92 - h // 2, cx + 30, 92 + h // 2], radius=14, fill=accent)
                    if not blink:
                        d.ellipse([cx + 10, 92 - h // 2 + 8, cx + 18, 92 - h // 2 + 16], fill=(255, 255, 255))

            d.rounded_rectangle([(10, 160), (310, 232)], radius=8, fill=(22, 28, 44), outline=(45, 55, 72))
            if st == "listening":
                label = f"Hearing voice... ({rem}s)" if speech_act else f"Listening... ({rem}s)"
                d.text((20, 172), label, fill=(72, 239, 128) if speech_act else (56, 189, 248), font=self.font_md)
                d.rounded_rectangle([(20, 204), (300, 218)], radius=4, fill=(12, 16, 28))
                pct = max(0.0, min(1.0, robot["listen_remaining"] / tot))
                bar_w = int(280 * pct)
                if bar_w > 4:
                    bar_col = (72, 239, 128) if speech_act else ((245, 158, 11) if rem <= 2 else (0, 212, 255))
                    d.rounded_rectangle([(20, 204), (20 + bar_w, 218)], radius=4, fill=bar_col)
            else:
                lines = self._wrap_text(d, txt, self.font_md, max_w=278, max_lines=3)
                for i, line in enumerate(lines):
                    d.text((18, 168 + i * 20), line, fill=(255, 255, 255), font=self.font_md)

        self.last_image = img

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
# 6. ULTRASONIC SENSOR (WAKE-UP + INSTANT INTERRUPT WHILE THINKING/SPEAKING)
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
    prev_dist = 999.0

    while True:
        if robot["state"] == "listening":
            time.sleep(0.35)
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

                    st = robot["state"]
                    now = time.time()

                    if st == "idle" and dist <= WAKE_DISTANCE_CM and (now - last_wake_time) >= COOLDOWN_SEC:
                        trigger_voice_session(from_wake=True, is_interrupt=False, dist=dist)
                    elif st in ("thinking", "speaking") and now >= interrupt_armed_at:
                        if dist <= INTERRUPT_DISTANCE_CM or (prev_dist > WAKE_DISTANCE_CM and dist <= WAKE_DISTANCE_CM):
                            trigger_voice_session(from_wake=False, is_interrupt=True, dist=dist)

                    prev_dist = dist
            else:
                with state_lock:
                    robot["distance_cm"] = -1.0
                if not no_echo_warned and valid_count == 0:
                    no_echo_warned = True
                    log.warning("Ultrasonic: No ECHO on GPIO%d. Check 5V VCC & 1k/2k divider!", PIN_ECHO)
        except Exception:
            pass
        time.sleep(0.28)


def trigger_voice_session(from_wake: bool = False, is_interrupt: bool = False, dist: float = 0.0):
    global last_wake_time, interrupt_armed_at, active_gen_id
    now = time.time()
    last_wake_time = now
    interrupt_armed_at = now + 2.2

    if is_interrupt:
        interrupt_now(f"Ultrasonic Interrupt ({dist:.1f} cm)")
    else:
        with state_lock:
            active_gen_id += 1
        log.info("Proximity wake triggered at %.1f cm!", dist)

    my_gen = active_gen_id
    threading.Thread(target=run_voice_cycle, args=(from_wake, is_interrupt, my_gen), daemon=True).start()


# ==============================================================================
# 7. CONTINUOUS MULTI-TURN CONVERSATION PIPELINE
# ==============================================================================
def handle_reply(user_text: str, res: RobotReply, speak: bool = True, gen_id: int = 0):
    if gen_id and gen_id != active_gen_id:
        return
    u_txt = user_text or res.user_transcript or "[Voice]"
    with state_lock:
        if gen_id and gen_id != active_gen_id:
            return
        robot["last_question"] = u_txt
        robot["detected_lang"] = res.detected_language
        robot["reply_native"] = res.reply_native
        robot["reply_romanized"] = res.reply_romanized
        robot["emotion"] = res.emotion
        robot["response_hold_until"] = time.time() + RESPONSE_HOLD_SEC
        chat_history.append({"role": "User", "text": u_txt})
        chat_history.append({"role": "Easibot", "text": res.reply_english})
        if len(chat_history) > 12:
            del chat_history[:-12]

        robot["messages"].append({"sender": "YOU", "text": u_txt, "lang": res.detected_language})
        robot["messages"].append({"sender": "BOT", "text": res.reply_native, "en": res.reply_english, "lang": res.detected_language})
        robot["messages"] = robot["messages"][-30:]

    if speak and robot["speaker_on"]:
        with state_lock:
            if gen_id and gen_id != active_gen_id:
                return
            robot["state"], robot["emotion"] = "speaking", "speaking"
        speak_text(res.reply_native, res.detected_language, gen_id=gen_id)
        with state_lock:
            robot["response_hold_until"] = time.time() + RESPONSE_HOLD_SEC


def run_voice_cycle(from_wake: bool = False, is_interrupt: bool = False, gen_id: Optional[int] = None):
    global last_wake_time, interrupt_armed_at, active_gen_id
    if gen_id is None:
        with state_lock:
            active_gen_id += 1
            gen_id = active_gen_id

    try:
        turn = 0
        while gen_id == active_gen_id:
            turn += 1
            interrupt_armed_at = time.time() + 2.2

            if turn == 1 and from_wake and not is_interrupt and robot["speaker_on"]:
                with state_lock:
                    robot["state"], robot["emotion"] = "speaking", "happy"
                    robot["last_question"] = ""
                    robot["reply_native"] = "Hi! Ask me anything."
                speak_text("Hi! Ask me anything.", "en", gen_id=gen_id)
                if gen_id != active_gen_id:
                    return
            else:
                play_ready_beep()

            with state_lock:
                if gen_id != active_gen_id:
                    return
                robot["state"], robot["emotion"] = "listening", "listening"
                robot["response_hold_until"] = 0.0
                robot["reply_native"] = "Listening..." if turn == 1 else "Listening for next question..."

            wav = record_voice(wait_speech_sec=LISTEN_TIMEOUT_SEC, gen_id=gen_id)
            if gen_id != active_gen_id:
                return

            if not wav:
                with state_lock:
                    if gen_id == active_gen_id:
                        robot["state"], robot["emotion"] = "idle", "happy"
                        if turn == 1:
                            robot["reply_native"] = "No speech heard."
                break

            with state_lock:
                if gen_id != active_gen_id:
                    return
                robot["state"], robot["emotion"] = "thinking", "thinking"
                robot["reply_native"] = "Thinking..."
                interrupt_armed_at = time.time() + 1.5

            res = ask_gemini(audio_wav=wav, lang_pref=robot["language"], gen_id=gen_id)
            if not res or gen_id != active_gen_id:
                return

            if not res.user_transcript.strip() and res.end_conversation:
                with state_lock:
                    if gen_id == active_gen_id:
                        robot["state"], robot["emotion"] = "idle", "happy"
                break

            handle_reply(res.user_transcript, res, speak=True, gen_id=gen_id)
            if gen_id != active_gen_id:
                return

            if res.end_conversation or not robot["continuous_chat"]:
                with state_lock:
                    if gen_id == active_gen_id:
                        robot["state"], robot["emotion"] = "idle", "happy"
                break

        if gen_id == active_gen_id:
            last_wake_time = time.time()
    finally:
        with state_lock:
            if gen_id == active_gen_id and robot["state"] in ("listening", "thinking", "speaking"):
                robot["state"], robot["emotion"] = "idle", "happy"


# ==============================================================================
# 8. EMBEDDED SIMPLE WEB DASHBOARD (FLASK + LIVE TFT MIRROR + TEST SPEAKER)
# ==============================================================================
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Easibot Fast Dashboard</title>
<style>
  body { background:#0b1120; color:#f1f5f9; font-family:system-ui,sans-serif; max-width:760px; margin:0 auto; padding:16px; }
  .card { background:#162032; border:1px solid #26334d; border-radius:12px; padding:16px; margin-bottom:14px; }
  .row { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }
  .badge { background:#0284c7; padding:4px 10px; border-radius:20px; font-size:12px; font-weight:700; text-transform:uppercase; }
  #chat { height:280px; overflow-y:auto; background:#0b1120; border:1px solid #26334d; border-radius:8px; padding:12px; margin-bottom:12px; }
  .msg { margin-bottom:10px; padding:8px 12px; border-radius:8px; max-width:85%; }
  .YOU { background:#1e3a5f; margin-left:auto; }
  .BOT { background:#1e293b; border-left:3px solid #00d4ff; }
  .sub { font-size:12px; color:#94a3b8; margin-top:4px; }
  .chips { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
  .chip { background:#1e293b; color:#38bdf8; border:1px solid #334155; padding:4px 10px; border-radius:16px; font-size:12px; cursor:pointer; }
  input, select, button { padding:10px 14px; border-radius:8px; border:1px solid #334155; background:#0f172a; color:#fff; font-size:14px; }
  button { background:#00d4ff; color:#041226; font-weight:700; cursor:pointer; border:none; }
  button.mic { background:#f43f5e; color:#fff; flex:1; }
  button.spk { background:#10b981; color:#041226; }
  .tft-box { text-align:center; margin-top:10px; }
  .tft-img { width:100%; max-width:320px; border-radius:8px; border:2px solid #334155; }
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
      <label><input type="checkbox" id="contOn" checked onchange="toggleCont()"> 🔁 Continuous</label>
    </div>
    <div class="row" style="margin-top:10px">
      <button class="mic" onclick="fetch('/api/listen',{method:'POST'})">🎙️ Interrupt & Listen Now</button>
      <button class="spk" onclick="fetch('/api/test_speaker',{method:'POST'})">🔊 Test Speaker</button>
    </div>
    <div class="tft-box">
      <img id="tft" class="tft-img" src="/api/tft" alt="TFT Live Screen">
    </div>
  </div>

  <div class="card">
    <div id="chat"></div>
    <div class="chips">
      <button class="chip" onclick="quickAsk('hi')">hi</button>
      <button class="chip" onclick="quickAsk('what is a diode')">what is diode</button>
      <button class="chip" onclick="quickAsk('what is resistor')">what is resistor</button>
      <button class="chip" onclick="quickAsk('what is raspberry pi')">raspberry pi</button>
      <button class="chip" onclick="quickAsk('what is mitochondria')">mitochondria</button>
    </div>
    <form onsubmit="sendMsg(event)" class="row">
      <input id="txt" style="flex:1" placeholder="Ask anything (instant study commands or AI)..." autocomplete="off">
      <button type="submit">Send</button>
    </form>
  </div>

<script>
async function refresh() {
  const d = await (await fetch('/api/status')).json();
  document.getElementById('state').textContent = d.state === 'listening' ? `LISTENING (${Math.ceil(d.listen_remaining)}s)` : d.state;
  document.getElementById('dist').textContent = d.distance_cm > 0 ? d.distance_cm : '--';
  document.getElementById('mic').textContent = d.mic_info;
  document.getElementById('spk').textContent = d.speaker_info;
  const chat = document.getElementById('chat');
  chat.innerHTML = d.messages.map(m =>
    `<div class="msg ${m.sender}"><b>${m.sender} [${m.lang.toUpperCase()}]</b><div>${m.text}</div>` +
    (m.en && m.lang!=='en' ? `<div class="sub">EN: ${m.en}</div>` : '') + `</div>`
  ).join('');
  chat.scrollTop = chat.scrollHeight;
  document.getElementById('tft').src = '/api/tft?t=' + Date.now();
}
async function quickAsk(q) { document.getElementById('txt').value = q; sendMsg(new Event('submit')); }
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
setInterval(refresh, 700); refresh();
</script>
</body>
</html>"""

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
tft_instance: Optional[SimpleTFT] = None


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify(robot)


@app.route("/api/tft")
def api_tft():
    if tft_instance and tft_instance.last_image:
        buf = io.BytesIO()
        tft_instance.last_image.save(buf, format="JPEG", quality=80)
        return Response(buf.getvalue(), mimetype="image/jpeg")
    return Response(b"", status=404)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    global active_gen_id
    data = request.get_json() or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "empty"}), 400

    interrupt_now("Web Chat Input")
    my_gen = active_gen_id

    def _run_chat():
        with state_lock:
            robot["state"], robot["emotion"] = "thinking", "thinking"
            robot["last_question"] = msg
            robot["response_hold_until"] = 0.0
        res = ask_gemini(text_query=msg, lang_pref=robot["language"], gen_id=my_gen)
        if not res or my_gen != active_gen_id:
            return
        handle_reply(msg, res, data.get("speak", True), gen_id=my_gen)
        with state_lock:
            if my_gen == active_gen_id:
                robot["state"], robot["emotion"] = "idle", "happy"

    threading.Thread(target=_run_chat, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/listen", methods=["POST"])
def api_listen():
    trigger_voice_session(from_wake=False, is_interrupt=(robot["state"] != "idle"), dist=0.0)
    return jsonify({"ok": True})


@app.route("/api/test_speaker", methods=["POST"])
def api_test_speaker():
    threading.Thread(target=lambda: speak_text("Speaker test is working loudly and clearly!", "en"), daemon=True).start()
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
# 9. MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    log.info("Starting Easibot Fast Edition (Model=%s, MOCK=%s, TRIG=GPIO%d, ECHO=GPIO%d)...", GEMINI_MODEL, MOCK_HARDWARE, PIN_TRIG, PIN_ECHO)

    tft_instance = SimpleTFT()
    tft_instance.render_and_push(force=True)
    threading.Thread(target=ultrasonic_worker, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False), daemon=True).start()

    log.info("Web Dashboard available at http://localhost:%d", WEB_PORT)

    try:
        while True:
            tft_instance.render_and_push()
            time.sleep(0.25)
    except KeyboardInterrupt:
        log.info("Easibot stopped.")
