"""Factory routing coverage without loading either Kokoro model."""

import unittest
from unittest.mock import patch

from epub2audiobook import mlx_backend, onnx_parallel, tts_engine
from epub2audiobook.config import DEFAULT_KOKORO_VOICE, DEFAULT_PIPER_VOICE
from epub2audiobook.tts_engine import TTSError


class BackendRoutingTests(unittest.TestCase):
    def test_default_factory_selects_onnx_and_forwards_voice(self) -> None:
        with patch.object(onnx_parallel, "KokoroParallelEngine") as constructor:
            self.assertIs(tts_engine.create_tts_engine(), constructor.return_value)
            constructor.assert_called_once_with(DEFAULT_KOKORO_VOICE)
            constructor.reset_mock()
            self.assertIs(
                tts_engine.create_tts_engine(voice="bm_george"),
                constructor.return_value,
            )
            constructor.assert_called_once_with("bm_george")

    def test_explicit_mlx_selects_mlx_and_forwards_voice(self) -> None:
        with patch.object(mlx_backend, "MLXKokoroEngine") as constructor:
            self.assertIs(
                tts_engine.create_tts_engine(backend="mlx"), constructor.return_value
            )
            constructor.assert_called_once_with(DEFAULT_KOKORO_VOICE)
            constructor.reset_mock()
            self.assertIs(
                tts_engine.create_tts_engine(voice="bm_george", backend="mlx"),
                constructor.return_value,
            )
            constructor.assert_called_once_with("bm_george")

    def test_retained_piper_default_backend_and_voice_forwarding(self) -> None:
        with patch.object(tts_engine, "PiperTTSEngine") as constructor:
            self.assertIs(
                tts_engine.create_tts_engine("piper"), constructor.return_value
            )
            constructor.assert_called_once_with(DEFAULT_PIPER_VOICE)
            constructor.reset_mock()
            self.assertIs(
                tts_engine.create_tts_engine("piper", "en_GB-alan-medium"),
                constructor.return_value,
            )
            constructor.assert_called_once_with("en_GB-alan-medium")

    def test_piper_with_mlx_is_rejected_before_construction(self) -> None:
        with patch.object(tts_engine, "PiperTTSEngine") as constructor:
            with self.assertRaisesRegex(TTSError, "only available with Kokoro"):
                tts_engine.create_tts_engine("piper", backend="mlx")
            constructor.assert_not_called()

    def test_unknown_kokoro_backend_is_rejected(self) -> None:
        with self.assertRaisesRegex(TTSError, "Unknown Kokoro backend 'other'"):
            tts_engine.create_tts_engine(backend="other")


if __name__ == "__main__":
    unittest.main()
