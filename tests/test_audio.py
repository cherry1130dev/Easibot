"""
Unit tests for AudioService: voice recording and TTS synthesis.
"""

import unittest
import wave
import io
from pathlib import Path
from core.audio_service import AudioService
import config


class TestAudioService(unittest.TestCase):

    def setUp(self):
        self.audio_svc = AudioService()

    def test_dummy_wav_generation(self):
        """Verifies valid WAV format generated for mock recording."""
        wav_bytes = self.audio_svc._generate_dummy_wav(duration_sec=1.0, sample_rate=16000)
        self.assertIsNotNone(wav_bytes)
        self.assertGreater(len(wav_bytes), 1000)

        # Inspect WAV header
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 16000)
            self.assertEqual(wf.getnframes(), 16000)

    def test_voice_mappings(self):
        """Verifies configured voice IDs for English, Telugu, and Hindi."""
        self.assertEqual(config.EDGE_TTS_VOICES["en"], "en-IN-NeerjaNeural")
        self.assertEqual(config.EDGE_TTS_VOICES["te"], "te-IN-ShrutiNeural")
        self.assertEqual(config.EDGE_TTS_VOICES["hi"], "hi-IN-SwaraNeural")


if __name__ == "__main__":
    unittest.main()
