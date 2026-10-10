"""Synthetic backend-contract tests; no model or real book is run."""

import io
import logging
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from epub2audiobook import cli, mlx_backend, onnx_parallel, tts_engine
from epub2audiobook.tts_engine import TTSError


class _FakeFuture:
    def __init__(self, pool: "_FakePool", text: str, fail: bool) -> None:
        self.pool = pool
        self.text = text
        self.fail = fail

    def result(self) -> tuple[bytes, int]:
        self.pool.outstanding -= 1
        if self.fail:
            raise RuntimeError("SECRET_BOOK_TEXT")
        return bytes((ord(self.text[0]), 0)), 24_000


class _FakePool:
    instances: list["_FakePool"] = []
    fail = False

    def __init__(self, max_workers: int, mp_context: object) -> None:
        self.max_workers = max_workers
        self.mp_context = mp_context
        self.outstanding = 0
        self.max_outstanding = 0
        self.closed = False
        self.instances.append(self)

    def submit(self, _fn: object, text: str, *_args: object) -> _FakeFuture:
        self.outstanding += 1
        self.max_outstanding = max(self.max_outstanding, self.outstanding)
        return _FakeFuture(self, text, self.fail)

    def shutdown(self, wait: bool, cancel_futures: bool) -> None:
        self.closed = True


class ParallelOnnxTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakePool.instances.clear()
        _FakePool.fail = False
        self.scratch = tempfile.TemporaryDirectory(prefix="onnx-backend-test-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def _engine(self) -> onnx_parallel.KokoroParallelEngine:
        models = self.root / "models"
        models.mkdir(exist_ok=True)
        with (models / onnx_parallel.KOKORO_VOICES_FILE).open("wb") as voice_pack:
            np.savez(voice_pack, af_heart=np.zeros(1, dtype=np.float32))
        with (
            patch.object(onnx_parallel, "KOKORO_MODEL_DIR", models),
            patch.object(onnx_parallel, "_download_if_missing"),
            patch.object(onnx_parallel.importlib.util, "find_spec", return_value=object()),
        ):
            return onnx_parallel.KokoroParallelEngine()

    def test_default_onnx_is_ordered_bounded_and_preserves_pauses(self) -> None:
        engine = self._engine()
        output = self.root / "chapter.wav"
        text = " ".join(chr(65 + index) for index in range(20))
        with (
            patch.object(onnx_parallel, "ProcessPoolExecutor", _FakePool),
            patch.object(onnx_parallel, "MAX_TTS_CHUNK_CHARS", 1),
        ):
            engine.generate(text, output)
            engine.close()

        pool = _FakePool.instances[0]
        self.assertEqual(pool.max_workers, 6)
        self.assertLessEqual(pool.max_outstanding, 12)
        self.assertTrue(pool.closed)
        with wave.open(str(output), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 24_000)
            frames = wav_file.readframes(wav_file.getnframes())
        expected = b"".join(bytes((ord(ch), 0)) for ch in text.split())
        self.assertEqual(frames[: len(expected)], expected)
        self.assertEqual(len(frames) - len(expected), 28_800)

    def test_worker_error_is_content_safe_and_removes_partial_wav(self) -> None:
        _FakePool.fail = True
        engine = self._engine()
        output = self.root / "failed.wav"
        with patch.object(onnx_parallel, "ProcessPoolExecutor", _FakePool):
            with self.assertRaises(TTSError) as raised:
                engine.generate("Secret source text", output)
        self.assertNotIn("SECRET_BOOK_TEXT", str(raised.exception))
        self.assertFalse(output.exists())
        self.assertTrue(_FakePool.instances[0].closed)

    def test_cleanup_failure_still_closes_pool_and_sanitizes_errors(self) -> None:
        _FakePool.fail = True
        engine = self._engine()
        output = self.root / "failed.wav"
        with (
            patch.object(onnx_parallel, "ProcessPoolExecutor", _FakePool),
            patch.object(Path, "unlink", side_effect=OSError("SECRET_BOOK_TEXT")),
        ):
            with self.assertRaises(TTSError) as raised:
                engine.generate("Synthetic source text", output)
        self.assertTrue(_FakePool.instances[0].closed)
        self.assertIsNone(engine._pool)
        self.assertNotIn("SECRET_BOOK_TEXT", str(raised.exception))
        self.assertIn("partial audio cleanup failed (OSError)", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_worker_sanitizes_backend_exception_before_transport(self) -> None:
        class FakeKokoro:
            def create(self, _text: str, **_kwargs: str):
                raise RuntimeError("SECRET_BOOK_TEXT")

        with patch.object(onnx_parallel, "_worker_model", FakeKokoro()):
            with self.assertRaises(onnx_parallel._WorkerError) as raised:
                onnx_parallel._synthesize_chunk(
                    "Secret source text", "af_heart", "en-us", "model", "voices"
                )
        self.assertEqual(str(raised.exception), "RuntimeError")
        self.assertTrue(raised.exception.__suppress_context__)

    def test_worker_uses_cpu_session_with_two_threads(self) -> None:
        seen: dict[str, object] = {}

        class FakeOptions:
            intra_op_num_threads = 0
            inter_op_num_threads = 0

        class FakeKokoro:
            @staticmethod
            def from_session(session: object, voices_path: str):
                seen["session"] = session
                seen["voices_path"] = voices_path
                return FakeKokoro()

            def create(self, _text: str, **_kwargs: str):
                return np.array([0.0], dtype=np.float32), 24_000

        def make_session(model_path: str, sess_options: FakeOptions, providers: list[str]):
            seen.update(path=model_path, options=sess_options, providers=providers)
            return object()

        fake_ort = SimpleNamespace(
            SessionOptions=FakeOptions, InferenceSession=make_session
        )
        with (
            patch.object(onnx_parallel, "_worker_model", None),
            patch.dict(
                sys.modules,
                {
                    "onnxruntime": fake_ort,
                    "kokoro_onnx": SimpleNamespace(Kokoro=FakeKokoro),
                },
            ),
        ):
            frames, rate = onnx_parallel._synthesize_chunk(
                "Synthetic text", "af_heart", "en-us", "model", "voices"
            )
        self.assertEqual((frames, rate), (b"\x00\x00", 24_000))
        self.assertEqual(seen["path"], "model")
        self.assertEqual(seen["voices_path"], "voices")
        self.assertEqual(seen["providers"], ["CPUExecutionProvider"])
        self.assertEqual(seen["options"].intra_op_num_threads, 2)
        self.assertEqual(seen["options"].inter_op_num_threads, 1)


class MlxBackendTests(unittest.TestCase):
    def test_cli_flag_and_optional_mlx_generation_contract(self) -> None:
        args = cli.parse_args(["book.epub", "--backend", "mlx"])
        self.assertEqual(args.backend, "mlx")

        class FakeModel:
            def generate(self, **kwargs: object):
                self.kwargs = kwargs
                logging.warning("PHONEME_SECRET_MARKER")
                yield SimpleNamespace(
                    audio=np.array([0.0, 0.5], dtype=np.float32),
                    sample_rate=24_000,
                )

        model = FakeModel()
        fake_utils = SimpleNamespace(load_model=lambda _model_id: model)
        visible_logs = io.StringIO()
        handler = logging.StreamHandler(visible_logs)
        root_logger = logging.getLogger()
        previous_level = root_logger.level
        previous_disable = logging.root.manager.disable
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.WARNING)
        with tempfile.TemporaryDirectory(prefix="mlx-backend-test-") as scratch:
            output = Path(scratch) / "chapter.wav"
            voices = Path(scratch) / "voices"
            voices.mkdir()
            (voices / "af_heart.safetensors").touch()
            fake_hf = SimpleNamespace(snapshot_download=lambda **_kwargs: scratch)
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
                engine = mlx_backend.MLXKokoroEngine()
                engine.generate("Synthetic text", output)
            with wave.open(str(output), "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 24_000)
                self.assertEqual(wav_file.readframes(2), b"\x00\x00\xff?")
        logging.warning("AFTER_MLX_MARKER")
        root_logger.removeHandler(handler)
        root_logger.setLevel(previous_level)
        handler.close()
        self.assertEqual(logging.root.manager.disable, previous_disable)
        self.assertNotIn("PHONEME_SECRET_MARKER", visible_logs.getvalue())
        self.assertIn("AFTER_MLX_MARKER", visible_logs.getvalue())
        self.assertEqual(model.kwargs["voice"], "af_heart")
        self.assertEqual(model.kwargs["lang_code"], "a")

    def test_mlx_requires_optional_package(self) -> None:
        with (
            patch.object(mlx_backend.platform, "system", return_value="Darwin"),
            patch.object(mlx_backend.platform, "machine", return_value="arm64"),
            patch.dict(sys.modules, {"mlx_audio": None}),
        ):
            with self.assertRaisesRegex(
                tts_engine.DependencyError, "optional dependencies"
            ):
                mlx_backend.MLXKokoroEngine()

    def test_mlx_generation_failure_restores_logging_and_hides_source(self) -> None:
        class FailingModel:
            def generate(self, **_kwargs: object):
                logging.warning("PHONEME_SECRET_MARKER")
                raise RuntimeError("SECRET_BOOK_TEXT")
                yield  # Keep this a generator so failure occurs during iteration.

        fake_utils = SimpleNamespace(load_model=lambda _model_id: FailingModel())
        visible_logs = io.StringIO()
        handler = logging.StreamHandler(visible_logs)
        previous_disable = logging.root.manager.disable
        with tempfile.TemporaryDirectory(prefix="mlx-backend-error-") as scratch:
            voices = Path(scratch) / "voices"
            voices.mkdir()
            (voices / "af_heart.safetensors").touch()
            fake_hf = SimpleNamespace(snapshot_download=lambda **_kwargs: scratch)
            with (
                patch.object(mlx_backend.platform, "system", return_value="Darwin"),
                patch.object(mlx_backend.platform, "machine", return_value="arm64"),
                patch.object(logging.root, "handlers", [handler]),
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
                engine = mlx_backend.MLXKokoroEngine()
                with self.assertRaises(TTSError) as raised:
                    engine.generate("SECRET_BOOK_TEXT", Path(scratch) / "failed.wav")
        handler.close()
        self.assertEqual(logging.root.manager.disable, previous_disable)
        self.assertNotIn("SECRET_BOOK_TEXT", str(raised.exception))
        self.assertNotIn("PHONEME_SECRET_MARKER", visible_logs.getvalue())


if __name__ == "__main__":
    unittest.main()
