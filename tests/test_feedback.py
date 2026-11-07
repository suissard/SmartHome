"""Tests des retours sonores & vocaux (FeedbackManager) et du fade-in TTS."""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Settings
from audio.feedback import FeedbackManager
from audio.tts import TextToSpeech, TTSProvider


class FakeEngine(TTSProvider):
    @classmethod
    def describe(cls, settings):
        return "FakeEngine"

    def synthesize(self, text):
        # 1000 échantillons avec un décalage DC (simulant un modèle sans silence initial)
        return np.full(1000, 500, dtype=np.int16), 1000


class TestFeedbackManager(unittest.TestCase):
    def test_on_response_end_plays_sound_when_sound_type(self):
        settings = Settings(
            FEEDBACK_RESPONSE_END_TYPE="sound",
            FEEDBACK_RESPONSE_END_SOUND="ding",
        )
        fb = FeedbackManager(settings=settings)
        with patch.object(fb, "play_sound") as mock_play:
            fb.on_response_end()
            mock_play.assert_called_once_with("ding")

    def test_on_response_end_does_nothing_when_none_type(self):
        settings = Settings(
            FEEDBACK_RESPONSE_END_TYPE="none",
        )
        fb = FeedbackManager(settings=settings)
        with patch.object(fb, "play_sound") as mock_play:
            fb.on_response_end()
            mock_play.assert_not_called()

    def test_on_response_end_speaks_when_phrase_type(self):
        tts_mock = MagicMock()
        settings = Settings(
            FEEDBACK_RESPONSE_END_TYPE="phrase",
            FEEDBACK_RESPONSE_END_TEXT="À vous",
        )
        fb = FeedbackManager(tts=tts_mock, settings=settings)
        fb.on_response_end()
        tts_mock.speak.assert_called_once_with("À vous")

    def test_tts_fade_in_smoothes_initial_samples(self):
        settings = Settings(
            TTS_SILENCE_START_DURATION=0.1,
            TTS_SILENCE_END_DURATION=0.1,
            TTS_FADE_OUT_DURATION=0.05,
        )
        tts = TextToSpeech(settings, provider=FakeEngine(settings))
        audio, sr = tts.synthesize("Bonjour")
        # sr = 1000 -> 100 samples de silence_start
        silence_len = 100
        # Le premier échantillon après le silence démarre à 0 grâce au fade-in (au lieu de 500 direct)
        self.assertEqual(audio[silence_len], 0)
        # Et progresse vers la valeur cible
        self.assertGreater(audio[silence_len + 5], 0)


if __name__ == "__main__":
    unittest.main()
