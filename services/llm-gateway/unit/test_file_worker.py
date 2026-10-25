import io
import sys
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.file_worker import speech


class SpeechDecodingTests(unittest.TestCase):
    def test_whisper_receives_normalized_mono_16khz_pcm(self):
        for rate, channels in ((16000, 1), (48000, 2)):
            with self.subTest(rate=rate, channels=channels):
                samples = (8192 * np.sin(2 * np.pi * 440 * np.arange(rate // 10) / rate)).astype("<i2")
                data = io.BytesIO()
                with wave.open(data, "wb") as wav:
                    wav.setnchannels(channels)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(np.repeat(samples, channels).tobytes())

                def transcribe(audio, **kwargs):
                    self.assertIsInstance(audio, np.ndarray)
                    self.assertEqual(audio.dtype, np.float32)
                    self.assertEqual(audio.shape, (1600,))
                    self.assertGreater(float(np.max(np.abs(audio))), 0.1)
                    self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)
                    self.assertEqual(kwargs, {"language": "ru", "vad_filter": True})
                    return iter([SimpleNamespace(start=0, end=0.1, text=" Заявка ")]), None

                model = SimpleNamespace(transcribe=transcribe)
                with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=lambda *a, **kw: model)}):
                    result = speech(data.getvalue(), dict(media_type="audio/wav", model="small", device="cpu", compute_type="int8", max_chars=100))
                self.assertEqual(result, "[[0.00-0.10 с]] Заявка")
