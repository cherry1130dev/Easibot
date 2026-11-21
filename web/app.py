"""
Flask Web Chat Dashboard & REST API for Easibot.
Runs in a background thread concurrently with hardware loops.
Provides real-time state monitoring, interactive multilingual chat, and audio controls.
"""

import time
import json
import logging
from typing import Optional, Callable
from flask import Flask, render_template, request, jsonify, Response, send_file

import config
from core.state_manager import StateManager, RobotState, Emotion
from core.gemini_service import GeminiService
from core.audio_service import AudioService
from hardware.tft_display import TFTDisplay
from hardware.ultrasonic import UltrasonicSensor

logger = logging.getLogger("easibot.web")


def create_app(
    state_manager: StateManager,
    gemini_service: GeminiService,
    audio_service: AudioService,
    tft_display: Optional[TFTDisplay] = None,
    ultrasonic_sensor: Optional[UltrasonicSensor] = None,
    trigger_listen_callback: Optional[Callable[[], None]] = None
) -> Flask:
    """Factory function for Easibot Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    # Disable noisy Flask request logs in console
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            supported_languages=config.SUPPORTED_LANGUAGES,
            default_lang=state_manager.active_language,
            speaker_enabled=state_manager.speaker_enabled,
            mock_mode=state_manager.mock_mode
        )

    @app.route("/api/status", methods=["GET"])
    def get_status():
        """Returns JSON snapshot of robot state, emotion, proximity, and chat."""
        # Refresh distance before returning
        if ultrasonic_sensor:
            state_manager.update_distance(ultrasonic_sensor.get_distance())
        return jsonify(state_manager.to_dict())

    @app.route("/api/stream")
    def sse_stream():
        """Server-Sent Events endpoint for real-time live dashboard sync."""
        def event_generator():
            while True:
                if ultrasonic_sensor:
                    state_manager.update_distance(ultrasonic_sensor.get_distance())
                data = json.dumps(state_manager.to_dict())
                yield f"data: {data}\n\n"
                time.sleep(0.5)

        return Response(event_generator(), mimetype="text/event-stream")

    @app.route("/api/chat", methods=["POST"])
    def post_chat():
        """Handles user text input from the web chat dashboard."""
        payload = request.get_json() or {}
        user_message = payload.get("message", "").strip()
        lang_override = payload.get("language", state_manager.active_language)
        speak_on_robot = payload.get("speak_on_robot", True)

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        # Update state to THINKING
        state_manager.set_state(RobotState.THINKING, Emotion.THINKING)

        try:
            # Query Gemini
            result = gemini_service.process_text_query(user_message, language_preference=lang_override)

            # Record turn in state manager
            state_manager.record_turn(
                user_query=user_message,
                reply_native=result.reply_native,
                reply_english=result.reply_english,
                reply_romanized=result.reply_romanized,
                emotion=result.emotion,
                detected_language=result.detected_language
            )

            # Audio TTS Playback on Robot Speaker
            if speak_on_robot and state_manager.speaker_enabled:
                state_manager.set_state(RobotState.SPEAKING, Emotion.SPEAKING)
                
                def _play_tts_async():
                    tts_file = audio_service.synthesize_speech(
                        text=result.reply_native,
                        language=result.detected_language
                    )
                    if tts_file:
                        audio_service.play_audio(tts_file, blocking=True)
                    # Return to IDLE
                    state_manager.set_state(RobotState.IDLE, Emotion.NEUTRAL)

                import threading
                threading.Thread(target=_play_tts_async, daemon=True).start()
            else:
                state_manager.set_state(RobotState.IDLE, Emotion.NEUTRAL)

            return jsonify({
                "status": "success",
                "detected_language": result.detected_language,
                "reply_native": result.reply_native,
                "reply_english": result.reply_english,
                "reply_romanized": result.reply_romanized,
                "emotion": result.emotion
            })

        except Exception as e:
            logger.error("Chat processing failed: %s", e)
            state_manager.set_state(RobotState.ERROR, Emotion.ERROR)
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/trigger_listen", methods=["POST"])
    def trigger_listen():
        """Remotely activates the robot's voice listening pipeline."""
        if trigger_listen_callback:
            import threading
            threading.Thread(target=trigger_listen_callback, daemon=True).start()
            return jsonify({"status": "triggered", "message": "Listening cycle activated"})
        return jsonify({"status": "error", "message": "Voice trigger callback not configured"}), 501

    @app.route("/api/set_language", methods=["POST"])
    def set_language():
        payload = request.get_json() or {}
        lang = payload.get("language", "auto")
        state_manager.set_active_language(lang)
        return jsonify({"status": "success", "active_language": state_manager.active_language})

    @app.route("/api/toggle_speaker", methods=["POST"])
    def toggle_speaker():
        payload = request.get_json() or {}
        enabled = payload.get("enabled", True)
        state_manager.set_speaker_enabled(bool(enabled))
        return jsonify({"status": "success", "speaker_enabled": state_manager.speaker_enabled})

    @app.route("/api/mock/distance", methods=["POST"])
    def set_mock_distance():
        """Simulates changing ultrasonic distance for testing proximity wake-up."""
        payload = request.get_json() or {}
        dist = float(payload.get("distance_cm", 50.0))
        
        if ultrasonic_sensor and hasattr(ultrasonic_sensor.sensor_device, "set_distance"):
            ultrasonic_sensor.sensor_device.set_distance(dist)
            state_manager.update_distance(dist)
            return jsonify({"status": "success", "distance_cm": dist})
        
        state_manager.update_distance(dist)
        return jsonify({"status": "success", "distance_cm": dist})

    @app.route("/api/tft_preview")
    def get_tft_preview():
        """Returns binary JPEG mirror of the active TFT display canvas."""
        if tft_display and hasattr(tft_display.display_device, "get_preview_bytes"):
            data = tft_display.display_device.get_preview_bytes(format="JPEG")
            return Response(data, mimetype="image/jpeg")

        # Fallback to preview file if exists
        preview_file = config.BASE_DIR / "web" / "static" / "img" / "tft_preview.png"
        if preview_file.exists():
            return send_file(preview_file, mimetype="image/png")

        return Response(b"", status=404)

    return app
