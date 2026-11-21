"""
Unit tests for GeminiService and RobotResponse schema.
"""

import unittest
from core.gemini_service import GeminiService, RobotResponse


class TestGeminiService(unittest.TestCase):

    def setUp(self):
        # Initialized without API key to test fallback and parsing robustness
        self.svc = GeminiService(api_key=None)

    def test_robot_response_model(self):
        """Verifies Pydantic structured output model."""
        resp = RobotResponse(
            detected_language="te",
            reply_native="నమస్కారం! నేను బాగున్నాను.",
            reply_english="Hello! I am doing well.",
            reply_romanized="Namaskaram! Nenu bagunnanu.",
            emotion="happy"
        )
        self.assertEqual(resp.detected_language, "te")
        self.assertEqual(resp.emotion, "happy")
        self.assertIn("నమస్కారం", resp.reply_native)

    def test_fallback_english(self):
        resp = self.svc.process_text_query("Who are you?", language_preference="en")
        self.assertEqual(resp.detected_language, "en")
        self.assertIn("Easibot", resp.reply_native)
        self.assertIn(resp.emotion, ["happy", "neutral", "thinking", "speaking"])

    def test_fallback_telugu(self):
        resp = self.svc.process_text_query("Ela unnavu?", language_preference="te")
        self.assertEqual(resp.detected_language, "te")
        self.assertIn("నమస్కారం", resp.reply_native)
        self.assertTrue(len(resp.reply_romanized) > 0)

    def test_fallback_hindi(self):
        resp = self.svc.process_text_query("Aap kaise ho?", language_preference="hi")
        self.assertEqual(resp.detected_language, "hi")
        self.assertIn("नमस्ते", resp.reply_native)
        self.assertTrue(len(resp.reply_romanized) > 0)


if __name__ == "__main__":
    unittest.main()
