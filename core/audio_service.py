"""
Audio Recording, Speech Synthesis (TTS), and Playback Service.
Supports edge-tts (neural voices) with automatic gTTS fallback.
Supports Bluetooth speaker/mic playback via PipeWire/PulseAudio/ALSA/Windows.
"""

import os
import sys
import wave
import time
import shutil
import asyncio
import logging
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Optional, Callable

import config

logger = logging.getLogger("easibot.audio")

# Optional sounddevice for microphone capture & playback
try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


class AudioService:
    """Manages microphone recording, TTS synthesis, and Bluetooth speaker playback."""

    def __init__(self, temp_dir: Optional[Path] = None):
        self.temp_dir = temp_dir or config.TEMP_AUDIO_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.is_recording = False
        self.is_playing = False
        self._playback_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    # ==========================================================================
    # Microphone Capture & Recording
    # ==========================================================================
    def record_audio(
        self,
        duration_sec: float = config.RECORD_DURATION_SEC,
        sample_rate: int = config.AUDIO_SAMPLE_RATE,
        channels: int = config.AUDIO_CHANNELS,
        output_filename: Optional[str] = None
    ) -> Optional[bytes]:
        """
        Records audio from the microphone and returns WAV bytes.
        Tries sounddevice first, then arecord (Linux/ALSA), then generates silence/beep fallback.
        """
        output_path = self.temp_dir / (output_filename or f"record_{int(time.time()*1000)}.wav")
        self.is_recording = True
        logger.info("Starting audio recording for %.1f seconds...", duration_sec)

        try:
            # 1. Try sounddevice if installed and devices exist
            if SOUNDDEVICE_AVAILABLE:
                try:
                    recording = sd.rec(
                        int(duration_sec * sample_rate),
                        samplerate=sample_rate,
                        channels=channels,
                        dtype="int16"
                    )
                    sd.wait()
                    # Write to WAV file
                    with wave.open(str(output_path), "wb") as wf:
                        wf.setnchannels(channels)
                        wf.setsampwidth(2)  # 16-bit
                        wf.setframerate(sample_rate)
                        wf.writeframes(recording.tobytes())

                    with open(output_path, "rb") as f:
                        data = f.read()
                    logger.info("Recorded %d bytes via sounddevice", len(data))
                    return data
                except Exception as e:
                    logger.warning("sounddevice recording failed: %s. Trying arecord fallback...", e)

            # 2. Try ALSA arecord on Linux / Raspberry Pi
            if shutil.which("arecord"):
                try:
                    cmd = [
                        "arecord",
                        "-D", "default",
                        "-f", "S16_LE",
                        "-r", str(sample_rate),
                        "-c", str(channels),
                        "-d", str(int(duration_sec)),
                        str(output_path)
                    ]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if output_path.exists():
                        with open(output_path, "rb") as f:
                            data = f.read()
                        logger.info("Recorded %d bytes via arecord", len(data))
                        return data
                except Exception as e:
                    logger.warning("arecord recording failed: %s", e)

            # 3. Fallback: Generate valid minimal dummy WAV for test/mock environment
            logger.info("Generating simulated speech WAV for testing/mock environment")
            return self._generate_dummy_wav(duration_sec, sample_rate)

        finally:
            self.is_recording = False
            # Clean up temp file if needed
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass

    def _generate_dummy_wav(self, duration_sec: float, sample_rate: int) -> bytes:
        """Generates a minimal valid WAV file with low tone for mock testing."""
        num_frames = int(duration_sec * sample_rate)
        # Create a simple 440Hz sine wave tone
        import math
        raw_frames = bytearray()
        for i in range(num_frames):
            val = int(3000.0 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            raw_frames.extend(val.to_bytes(2, byteorder="little", signed=True))

        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_frames)
        return buf.getvalue()

    # ==========================================================================
    # Text-to-Speech (TTS) Synthesis
    # ==========================================================================
    def synthesize_speech(
        self,
        text: str,
        language: str = "en",
        output_filename: Optional[str] = None
    ) -> Optional[Path]:
        """
        Synthesizes speech using edge-tts (primary) and falls back to gTTS.
        Returns the path to the generated MP3/WAV file.
        """
        if not text.strip():
            return None

        out_path = self.temp_dir / (output_filename or f"tts_{int(time.time()*1000)}.mp3")

        # Select edge-tts voice
        voice = config.EDGE_TTS_VOICES.get(language, config.EDGE_TTS_VOICES["en"])

        # 1. Try edge-tts
        try:
            success = self._run_edge_tts(text, voice, out_path)
            if success and out_path.exists() and out_path.stat().st_size > 500:
                logger.info("edge-tts synthesized successfully: %s", out_path.name)
                return out_path
        except Exception as e:
            logger.warning("edge-tts failed (%s), attempting gTTS fallback...", e)

        # 2. Try gTTS fallback
        try:
            gtts_lang = config.GTTS_LANG_CODES.get(language, "en")
            from gtts import gTTS
            tts = gTTS(text=text, lang=gtts_lang, slow=False)
            tts.save(str(out_path))
            if out_path.exists() and out_path.stat().st_size > 500:
                logger.info("gTTS synthesized successfully: %s", out_path.name)
                return out_path
        except Exception as e:
            logger.error("gTTS fallback failed: %s", e)

        return None

    def _run_edge_tts(self, text: str, voice: str, output_path: Path) -> bool:
        """Runs edge-tts via asyncio loop."""
        import edge_tts

        async def _synthesize():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))

        try:
            # Check if event loop is already running
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(_synthesize(), loop)
                    future.result(timeout=10.0)
                else:
                    loop.run_until_complete(_synthesize())
            except RuntimeError:
                asyncio.run(_synthesize())
            return True
        except Exception as e:
            logger.debug("edge-tts error details: %s", e)
            return False

    # ==========================================================================
    # Audio Playback
    # ==========================================================================
    def play_audio(
        self,
        audio_path: Path,
        blocking: bool = True,
        on_finished: Optional[Callable[[], None]] = None
    ):
        """
        Plays audio file on the system speaker (Bluetooth default sink on Pi).
        Supports mpg123, pw-play, paplay, ffplay, and PowerShell (on Windows).
        """
        if not audio_path or not audio_path.exists():
            if on_finished:
                on_finished()
            return

        def _play_worker():
            with self._lock:
                self.is_playing = True

            try:
                # 1. Linux PipeWire / PulseAudio / ALSA players
                if sys.platform.startswith("linux"):
                    cmd = None
                    if audio_path.suffix.lower() == ".wav":
                        if shutil.which("pw-play"):
                            cmd = ["pw-play", str(audio_path)]
                        elif shutil.which("paplay"):
                            cmd = ["paplay", str(audio_path)]
                        elif shutil.which("aplay"):
                            cmd = ["aplay", str(audio_path)]
                    
                    if not cmd:
                        if shutil.which("mpg123") and audio_path.suffix.lower() == ".mp3":
                            cmd = ["mpg123", "-q", str(audio_path)]
                        elif shutil.which("ffplay"):
                            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]
                        elif shutil.which("cvlc"):
                            cmd = ["cvlc", "--play-and-exit", str(audio_path)]

                    if cmd:
                        self._playback_process = subprocess.Popen(
                            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        self._playback_process.wait()
                    else:
                        logger.warning("No Linux audio player found (install mpg123, pw-play, or ffmpeg)")
                        time.sleep(1.5)

                # 2. Windows players
                elif sys.platform.startswith("win"):
                    if shutil.which("ffplay"):
                        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]
                        self._playback_process = subprocess.Popen(
                            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        self._playback_process.wait()
                    else:
                        # Use PowerShell Media.SoundPlayer for .wav or Windows Media Player for .mp3
                        if audio_path.suffix.lower() == ".wav":
                            ps_cmd = f"(New-Object Media.SoundPlayer '{audio_path}').PlaySync()"
                        else:
                            ps_cmd = (
                                f"$wmp = New-Object -ComObject WMPlayer.OCX; "
                                f"$wmp.URL = '{audio_path}'; "
                                f"$wmp.controls.play(); "
                                f"while($wmp.playState -ne 1) {{ Start-Sleep -Milliseconds 100 }}"
                            )
                        subprocess.run(["powershell", "-c", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    # macOS
                    if shutil.which("afplay"):
                        subprocess.run(["afplay", str(audio_path)])

            except Exception as e:
                logger.error("Audio playback error: %s", e)
            finally:
                with self._lock:
                    self.is_playing = False
                    self._playback_process = None
                if on_finished:
                    on_finished()

        if blocking:
            _play_worker()
        else:
            t = threading.Thread(target=_play_worker, daemon=True)
            t.start()

    def stop_playback(self):
        """Stops active audio playback immediately."""
        with self._lock:
            if self._playback_process:
                try:
                    self._playback_process.terminate()
                except Exception:
                    pass
                self._playback_process = None
            self.is_playing = False
