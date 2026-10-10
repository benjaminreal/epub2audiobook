"""Synthetic voice-catalogue validation tests; no model or book is loaded."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from epub2audiobook import mlx_backend, onnx_parallel
from epub2audiobook.config import KOKORO_VOICES_FILE
from epub2audiobook.tts_engine import TTSError


def _write_onnx_voice_pack(path: Path, names: tuple[str, ...]) -> None:
    """Create an NPZ-shaped synthetic ONNX voice pack with a .bin suffix."""
    with path.open("wb") as pack:
        np.savez(pack, **{name: np.zeros(1, dtype=np.float32) for name in names})


class OnnxVoiceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="onnx-voice-validation-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def _initialize(self, voice: str, catalogue: str = "valid"):
        calls: list[Path] = []
        self.download_calls = calls

        def prepare(_url: str, destination: Path) -> None:
            calls.append(destination)
            if destination.name == KOKORO_VOICES_FILE:
                if catalogue == "valid":
                    _write_onnx_voice_pack(destination, ("af_heart", "bf_george"))
                elif catalogue == "corrupt":
                    destination.write_bytes(b"SECRET_BOOK_TEXT")

        with (
            patch.object(onnx_parallel, "KOKORO_MODEL_DIR", self.root / "models"),
            patch.object(onnx_parallel, "_download_if_missing", side_effect=prepare),
            patch.object(onnx_parallel.importlib.util, "find_spec", return_value=object()),
        ):
            engine = onnx_parallel.KokoroParallelEngine(voice)
        return engine, calls

    def test_default_voice_is_present_in_local_pack_and_model_stays_unloaded(self) -> None:
        engine, calls = self._initialize("af_heart")
        self.assertEqual(engine.get_voice_name(), "Kokoro ONNX (af_heart)")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].name, KOKORO_VOICES_FILE)
        self.assertEqual(calls[1].name, onnx_parallel.KOKORO_MODEL_FILE)
        self.assertIsNone(engine._pool)

    def test_unknown_full_voice_fails_before_model_download(self) -> None:
        with self.assertRaises(TTSError) as raised:
            self._initialize("a_not_a_voice")
        self.assertIn("Unknown Kokoro voice 'a_not_a_voice'", str(raised.exception))
        self.assertIn("af_heart", str(raised.exception))
        self.assertEqual(len(self.download_calls), 1)
        self.assertEqual(self.download_calls[0].name, KOKORO_VOICES_FILE)
        self.assertIsNone(raised.exception.__context__)

    def test_unsupported_prefix_behavior_is_preserved(self) -> None:
        with self.assertRaisesRegex(TTSError, "Unsupported Kokoro voice 'z_unknown'"):
            self._initialize("z_unknown")
        self.assertEqual(self.download_calls, [])

    def test_missing_or_corrupt_voice_pack_fails_safely(self) -> None:
        for catalogue in ("missing", "corrupt"):
            with self.subTest(catalogue=catalogue):
                with self.assertRaises(TTSError) as raised:
                    self._initialize("af_heart", catalogue=catalogue)
                self.assertIn("Failed to read Kokoro voice catalogue", str(raised.exception))
                self.assertNotIn("SECRET_BOOK_TEXT", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)


class MlxVoiceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="mlx-voice-validation-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.voices = self.root / "voices"
        self.voices.mkdir()

    def _initialize(self, voice: str, *, catalogue_error: Exception | None = None):
        model = object()
        calls: list[dict[str, object]] = []

        def snapshot_download(**kwargs: object) -> str:
            calls.append(kwargs)
            if catalogue_error is not None:
                raise catalogue_error
            return str(self.root)

        fake_hf = SimpleNamespace(snapshot_download=snapshot_download)
        fake_utils = SimpleNamespace(load_model=lambda _model_id: model)
        with (
            patch.object(mlx_backend.platform, "system", return_value="Darwin"),
            patch.object(mlx_backend.platform, "machine", return_value="arm64"),
            patch.dict(
                sys.modules,
                {
                    "huggingface_hub": fake_hf,
                    "mlx_audio": SimpleNamespace(tts=SimpleNamespace(utils=fake_utils)),
                    "mlx_audio.tts": SimpleNamespace(utils=fake_utils),
                    "mlx_audio.tts.utils": fake_utils,
                    "misaki": SimpleNamespace(),
                },
            ),
        ):
            engine = mlx_backend.MLXKokoroEngine(voice)
        return engine, model, calls

    def test_default_voice_is_present_in_cached_assets(self) -> None:
        (self.voices / "af_heart.safetensors").touch()
        engine, model, calls = self._initialize("af_heart")
        self.assertEqual(engine.get_voice_name(), "Kokoro MLX (af_heart)")
        self.assertIs(engine._model, model)
        self.assertEqual(
            calls,
            [
                {
                    "repo_id": mlx_backend.MLX_MODEL_ID,
                    "allow_patterns": ["voices/*.safetensors"],
                    "local_files_only": True,
                }
            ],
        )

    def test_unknown_full_voice_fails_before_generate(self) -> None:
        (self.voices / "af_heart.safetensors").touch()
        with self.assertRaises(TTSError) as raised:
            self._initialize("a_not_a_voice")
        self.assertIn("Unknown Kokoro voice 'a_not_a_voice'", str(raised.exception))
        self.assertIn("af_heart", str(raised.exception))
        self.assertIsNone(raised.exception.__context__)

    def test_missing_or_unreadable_catalogue_fails_safely(self) -> None:
        for error in (None, RuntimeError("SECRET_BOOK_TEXT")):
            with self.subTest(error=type(error).__name__ if error else "missing"):
                if error is None:
                    (self.voices / "af_heart.safetensors").unlink(missing_ok=True)
                    (self.voices / "not-a-voice-pack.txt").touch()
                with self.assertRaises(TTSError) as raised:
                    self._initialize("af_heart", catalogue_error=error)
                self.assertIn("Failed to read Kokoro MLX voice catalogue", str(raised.exception))
                self.assertNotIn("SECRET_BOOK_TEXT", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
