"""
Unit tests for headless single-file Easibot (main.py).
"""

import unittest
import main as bot


class TestEasibot(unittest.TestCase):

    def setUp(self):
        bot.MOCK_HARDWARE = True
        bot.robot["state"] = "idle"
        bot.robot["emotion"] = "happy"

    def test_predefined_commands(self):
        for q in ("hi", "hallo", "whattup", "what is diode", "what is resister", "raspberry pi", "mitrocandra"):
            res = bot.match_predefined(q)
            self.assertIsNotNone(res, f"Expected predefined match for {q}")
            self.assertTrue(len(res.reply_native) > 10)

    def test_ultrasonic_limits_and_no_speaking_interrupt(self):
        self.assertEqual(bot.WAKE_DISTANCE_CM, 15.0)
        old_gen = bot.active_gen_id
        bot.interrupt_thinking("Test Thinking Interrupt")
        self.assertEqual(bot.active_gen_id, old_gen + 1)

    def test_tft_face_and_response_screens(self):
        tft = bot.SimpleTFT()

        # 1. Face UI (Listening with countdown)
        bot.robot["state"] = "listening"
        bot.robot["emotion"] = "listening"
        bot.robot["listen_total"] = 5.0
        bot.robot["listen_remaining"] = 3.0
        tft.render_and_push(force=True)
        self.assertEqual(tft.last_image.size, (320, 240))

        # 2. Response UI (Speaking / Answer hold)
        res = bot.match_predefined("what is diode")
        bot.handle_reply("what is diode", res, speak=False)
        bot.robot["state"] = "speaking"
        tft.render_and_push(force=True)
        self.assertEqual(tft.last_image.size, (320, 240))


if __name__ == "__main__":
    unittest.main()
