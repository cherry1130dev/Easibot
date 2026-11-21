"""
Easibot: AI-Powered Multilingual Interactive Assistant Robot
Main Application Orchestrator for Raspberry Pi Zero 2 W / Laptop Mock.
"""

import os
import sys
import time
import signal
import logging
import argparse
import threading
from typing import Optional

# Setup root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("easibot.main")

import config
from core.state_manager import StateManager, RobotState, Emotion
from core.gemini_service import GeminiService
from core.audio_service import AudioService
from hardware.tft_display import TFTDisplay
from hardware.ultrasonic import UltrasonicSensor
from web.app import create_app


class EasibotApp:
    """Master application coordinator."""

    def __init__(self, mock_hardware: bool = config.MOCK_HARDWARE):
        logger.info("Initializing Easibot Multilingual Robot Assistant...")
        logger.info("Operating Mode: %s", "MOCK HARDWARE (Laptop Mode)" if mock_hardware else "PHYSICAL HARDWARE (Raspberry Pi)")

        # 1. Thread-safe State Manager
        self.state_mgr = StateManager(
            default_language=config.DEFAULT_LANGUAGE,
            speaker_enabled=config.ENABLE_SPEAKER_BY_DEFAULT
        )
        self.state_mgr.set_mock_mode(mock_hardware)

        # 2. Multilingual AI Service (Google Gemini)
        self.gemini_svc = GeminiService()

        # 3. Audio & Voice Pipeline
        self.audio_svc = AudioService()

        # 4. 2.8" SPI TFT LCD Display
        self.tft = TFTDisplay(mock_override=mock_hardware)

        # 5. HC-SR04 Ultrasonic Distance Sensor
        self.ultrasonic = UltrasonicSensor(
            on_wake_callback=self.on_ultrasonic_wake,
            mock_override=mock_hardware
        )

        # 6. Web Dashboard & REST API
        self.flask_app = create_app(
            state_manager=self.state_mgr,
            gemini_service=self.gemini_svc,
            audio_service=self.audio_svc,
            tft_display=self.tft,
            ultrasonic_sensor=self.ultrasonic,
            trigger_listen_callback=self.trigger_voice_cycle
        )

        self._running = False
        self._voice_lock = threading.Lock()

    def start(self):
        """Starts all background hardware loops and web server."""
        self._running = True

        # Start TFT display animation loop
        self.tft.start_animation_loop(self.state_mgr)

        # Start Ultrasonic distance sensor loop
        self.ultrasonic.start()

        # Start Flask web server in daemon thread
        web_thread = threading.Thread(
            target=lambda: self.flask_app.run(
                host=config.WEB_HOST,
                port=config.WEB_PORT,
                debug=False,
                use_reloader=False,
                threaded=True
            ),
            daemon=True,
            name="FlaskServerThread"
        )
        web_thread.start()
        logger.info("Web Dashboard live at: http://%s:%d (or http://localhost:%d)", self.state_mgr._ip_address, config.WEB_PORT, config.WEB_PORT)

        # Greet user on boot
        self._boot_greeting()

    def _boot_greeting(self):
        """Initial welcome greeting on TFT and speaker."""
        active_lang = self.state_mgr.active_language
        welcome_info = config.WELCOME_GREETINGS.get(active_lang, config.WELCOME_GREETINGS["en"])

        self.state_mgr.record_turn(
            user_query="",
            reply_native=welcome_info["text"],
            reply_english=config.WELCOME_GREETINGS["en"]["text"],
            reply_romanized=welcome_info["romanized"],
            emotion="happy",
            detected_language=welcome_info["lang"]
        )
        self.state_mgr.set_state(RobotState.IDLE, Emotion.HAPPY)

    # =========================================================================
    # Autonomous Wake & Voice Interaction Cycle
    # =========================================================================
    def on_ultrasonic_wake(self):
        """Called when ultrasonic sensor detects person within 60 cm."""
        if not self.state_mgr.can_trigger_wake(config.ULTRASONIC_COOLDOWN_SEC):
            return

        logger.info("Human detected near robot! Initiating autonomous greeting & voice cycle...")
        
        # 1. State: WAKING with greeting
        self.state_mgr.set_state(RobotState.WAKING, Emotion.HAPPY)
        
        # Play short chime or greeting if speaker enabled
        active_lang = self.state_mgr.active_language
        welcome_info = config.WELCOME_GREETINGS.get(active_lang, config.WELCOME_GREETINGS["en"])
        
        if self.state_mgr.speaker_enabled:
            tts_file = self.audio_svc.synthesize_speech(
                text="Hello! I am listening.",
                language="en"
            )
            if tts_file:
                self.audio_svc.play_audio(tts_file, blocking=True)

        # 2. Trigger voice listening cycle
        self.trigger_voice_cycle()

    def trigger_voice_cycle(self):
        """Executes full Listen -> Gemini 2.5 Flash Multimodal -> Speak pipeline."""
        if not self._voice_lock.acquire(blocking=False):
            logger.warning("Voice cycle already in progress, ignoring duplicate trigger.")
            return

        try:
            # Step 1: LISTENING
            logger.info("--- Voice Cycle Started ---")
            self.state_mgr.set_state(RobotState.LISTENING, Emotion.LISTENING)
            self.state_mgr.record_turn(
                user_query="",
                reply_native="Listening...",
                reply_english="Listening...",
                reply_romanized="Listening...",
                emotion="listening",
                detected_language=self.state_mgr.active_language
            )

            # Record voice from microphone (5 seconds)
            audio_data = self.audio_svc.record_audio(duration_sec=config.RECORD_DURATION_SEC)
            if not audio_data:
                logger.warning("No audio data captured.")
                self.state_mgr.set_state(RobotState.IDLE, Emotion.NEUTRAL)
                return

            # Step 2: THINKING & GEMINI PROCESSING
            logger.info("Audio captured (%d bytes). Querying Gemini 2.5 Flash...", len(audio_data))
            self.state_mgr.set_state(RobotState.THINKING, Emotion.THINKING)
            self.state_mgr.record_turn(
                user_query="[Voice Input]",
                reply_native="Thinking...",
                reply_english="Thinking...",
                reply_romanized="Thinking...",
                emotion="thinking",
                detected_language=self.state_mgr.active_language
            )

            # Send native audio directly to Gemini 2.5 Flash
            result = self.gemini_svc.process_audio_query(
                audio_bytes=audio_data,
                mime_type="audio/wav",
                language_preference=self.state_mgr.active_language
            )

            logger.info("Gemini reply received: lang=%s, emotion=%s", result.detected_language, result.emotion)

            # Step 3: SPEAKING & TFT DISPLAY
            self.state_mgr.set_state(RobotState.SPEAKING)
            self.state_mgr.record_turn(
                user_query="[Voice Input]",
                reply_native=result.reply_native,
                reply_english=result.reply_english,
                reply_romanized=result.reply_romanized,
                emotion=result.emotion,
                detected_language=result.detected_language
            )

            # Synthesize & play speech on Bluetooth speaker
            if self.state_mgr.speaker_enabled:
                tts_path = self.audio_svc.synthesize_speech(
                    text=result.reply_native,
                    language=result.detected_language
                )
                if tts_path:
                    self.audio_svc.play_audio(tts_path, blocking=True)
            else:
                time.sleep(2.5)

            # Step 4: Return to IDLE
            self.state_mgr.set_state(RobotState.IDLE, Emotion.HAPPY)
            logger.info("--- Voice Cycle Completed Successfully ---")

        except Exception as e:
            logger.error("Error in voice interaction cycle: %s", e)
            self.state_mgr.set_state(RobotState.ERROR, Emotion.ERROR)
            time.sleep(2.0)
            self.state_mgr.set_state(RobotState.IDLE, Emotion.NEUTRAL)
        finally:
            self._voice_lock.release()

    def stop(self):
        """Gracefully tears down all services."""
        logger.info("Shutting down Easibot services...")
        self._running = False
        self.ultrasonic.stop()
        self.tft.stop_animation_loop()
        self.audio_svc.stop_playback()
        logger.info("Easibot shutdown complete.")


def parse_args():
    parser = argparse.ArgumentParser(description="Easibot Multilingual Robot Assistant")
    parser.add_argument("--mock", action="store_true", help="Force mock hardware mode (laptop development)")
    parser.add_argument("--hardware", action="store_true", help="Force physical Raspberry Pi hardware mode")
    parser.add_argument("--port", type=int, default=config.WEB_PORT, help="Flask web port (default: 5000)")
    parser.add_argument("--lang", type=str, default=config.DEFAULT_LANGUAGE, choices=["auto", "en", "te", "hi"], help="Default language")
    return parser.parse_args()


def main():
    args = parse_args()

    mock_mode = config.MOCK_HARDWARE
    if args.mock:
        mock_mode = True
    elif args.hardware:
        mock_mode = False

    if args.port:
        config.WEB_PORT = args.port
    if args.lang:
        config.DEFAULT_LANGUAGE = args.lang

    bot = EasibotApp(mock_hardware=mock_mode)

    # Signal handlers for clean exit
    def sig_handler(sig, frame):
        logger.info("Received termination signal. Exiting cleanly...")
        bot.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    bot.start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        bot.stop()


if __name__ == "__main__":
    main()
