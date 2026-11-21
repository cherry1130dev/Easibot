"""
Unit and integration tests for StateManager, MockTFTDisplay, MockUltrasonic, and Flask Web API.
"""

import unittest
from PIL import Image

from core.state_manager import StateManager, RobotState, Emotion
from hardware.tft_display import RobotFacePainter
from hardware.mock_hardware import MockTFTDisplay, MockUltrasonic
from web.app import create_app
from core.gemini_service import GeminiService
from core.audio_service import AudioService


class TestHardwareAndState(unittest.TestCase):

    def test_state_manager_transitions(self):
        sm = StateManager(default_language="te", speaker_enabled=True)
        self.assertEqual(sm.state, RobotState.IDLE)
        self.assertEqual(sm.active_language, "te")

        # Transition to LISTENING
        sm.set_state(RobotState.LISTENING)
        self.assertEqual(sm.state, RobotState.LISTENING)
        self.assertEqual(sm.emotion, Emotion.LISTENING)

        # Record conversation turn
        sm.record_turn(
            user_query="నమస్కారం",
            reply_native="నమస్కారం! ఎలా ఉన్నారు?",
            reply_english="Hello! How are you?",
            reply_romanized="Namaskaram! Ela unnaru?",
            emotion="happy",
            detected_language="te"
        )
        self.assertEqual(sm.last_reply_native, "నమస్కారం! ఎలా ఉన్నారు?")
        self.assertEqual(sm.emotion, Emotion.HAPPY)
        self.assertEqual(len(sm.to_dict()["messages"]), 2)

    def test_robot_face_painter(self):
        """Verifies PIL frame rendering generates exact 320x240 RGB image."""
        painter = RobotFacePainter()
        frame = painter.draw_frame(
            state=RobotState.LISTENING,
            emotion=Emotion.HAPPY,
            distance_cm=45.0,
            active_lang="te",
            detected_lang="te",
            reply_native="నమస్కారం! నేను వింటున్నాను.",
            reply_romanized="Namaskaram! Nenu vintunnanu.",
            ip_address="192.168.1.50"
        )
        self.assertIsInstance(frame, Image.Image)
        self.assertEqual(frame.size, (320, 240))
        self.assertEqual(frame.mode, "RGB")

    def test_mock_tft_display(self):
        mock_tft = MockTFTDisplay()
        dummy_img = Image.new("RGB", (320, 240), (10, 10, 20))
        mock_tft.display_image(dummy_img)
        jpeg_bytes = mock_tft.get_preview_bytes(format="JPEG")
        self.assertGreater(len(jpeg_bytes), 100)

    def test_mock_ultrasonic_wake_threshold(self):
        wake_called = []
        def on_wake():
            wake_called.append(True)

        sensor = MockUltrasonic(on_wake_callback=on_wake)
        sensor.last_wake_time = 0.0  # reset cooldown
        sensor.trigger_proximity_approach(distance_cm=45.0)
        self.assertEqual(sensor.get_distance(), 45.0)

    def test_web_api_endpoints(self):
        sm = StateManager()
        gemini = GeminiService(api_key=None)
        audio = AudioService()
        app = create_app(sm, gemini, audio)
        client = app.test_client()

        # 1. GET /
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"EASIBOT", res.data)

        # 2. GET /api/status
        res = client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["state"], "idle")

        # 3. POST /api/chat
        res = client.post("/api/chat", json={
            "message": "Hello robot",
            "language": "en",
            "speak_on_robot": False
        })
        self.assertEqual(res.status_code, 200)
        chat_data = res.get_json()
        self.assertEqual(chat_data["status"], "success")
        self.assertIn("detected_language", chat_data)

        # 4. POST /api/set_language
        res = client.post("/api/set_language", json={"language": "hi"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sm.active_language, "hi")


if __name__ == "__main__":
    unittest.main()
