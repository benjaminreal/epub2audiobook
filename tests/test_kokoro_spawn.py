"""One bounded real-spawn check using synthetic PCM, with no neural models."""

import multiprocessing
import subprocess
import sys
import tempfile
import traceback
import unittest
import wave
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from epub2audiobook import onnx_parallel
from epub2audiobook.config import PARAGRAPH_PAUSE_MS
from epub2audiobook.tts_engine import TTSError


class _SyntheticModel:
    def __init__(self, release_first: object) -> None:
        self.release_first = release_first

    def create(self, text: str, **_kwargs: str) -> tuple[np.ndarray, int]:
        if text == "First":
            if not self.release_first.wait(timeout=10):
                raise TimeoutError("Synthetic synchronization timed out")
            value = 0.25
        elif text == "Second":
            value = 0.5
        else:
            raise RuntimeError("SECRET_SYNTHETIC_TEXT")
        return np.array([value], dtype=np.float32), onnx_parallel.SAMPLE_RATE


def _initialize_synthetic_model(release_first: object) -> None:
    """Set the process-local cache so the real worker needs no model imports."""
    onnx_parallel._worker_model = _SyntheticModel(release_first)


def _run_spawn_scenario() -> None:
    context = multiprocessing.get_context("spawn")
    release_first = context.Event()
    with (
        tempfile.TemporaryDirectory(prefix="kokoro-spawn-test-") as scratch,
        ProcessPoolExecutor(
            max_workers=2,
            mp_context=context,
            initializer=_initialize_synthetic_model,
            initargs=(release_first,),
        ) as pool,
    ):
        engine = onnx_parallel.KokoroParallelEngine.__new__(
            onnx_parallel.KokoroParallelEngine
        )
        engine._voice = "af_heart"
        engine._language = "en-us"
        engine._model_path = "unused-synthetic-model"
        engine._voices_path = "unused-synthetic-voices"

        def submit(worker: object, text: str, *args: str):
            future = pool.submit(worker, text, *args)
            if text == "Second":
                # First is still blocked in another child: transport Second's
                # completed result before allowing First to finish.
                assert future.result(timeout=10) == (b"\xff?", 24_000)
                release_first.set()
            return future

        engine._pool = SimpleNamespace(submit=submit, shutdown=pool.shutdown)
        output = Path(scratch) / "ordered.wav"
        assert engine.generate("First\n\nSecond", output) == output
        with wave.open(str(output), "rb") as wav_file:
            assert (wav_file.getnchannels(), wav_file.getsampwidth()) == (1, 2)
            assert wav_file.getframerate() == 24_000
            frames = wav_file.readframes(wav_file.getnframes())
        pause = bytes(2 * int(24_000 * PARAGRAPH_PAUSE_MS / 1000))
        assert frames == b"\xff\x1f" + pause + b"\xff?" + pause

        failure = pool.submit(
            onnx_parallel._synthesize_chunk,
            "Failure",
            "af_heart",
            "en-us",
            "unused-synthetic-model",
            "unused-synthetic-voices",
        )
        try:
            failure.result(timeout=10)
        except onnx_parallel._WorkerError as error:
            assert str(error) == "RuntimeError"
            assert "SECRET_SYNTHETIC_TEXT" not in "".join(
                traceback.format_exception(error)
            )
        else:
            raise AssertionError("The spawned exception was not transported")

        engine._pool = pool
        failed_output = Path(scratch) / "failed.wav"
        try:
            engine.generate("Failure", failed_output)
        except TTSError as error:
            assert str(error) == "TTS generation failed (_WorkerError)"
            assert not failed_output.exists()
            assert engine._pool is None
        else:
            raise AssertionError("The engine did not report the spawned failure")


class SpawnBackendTests(unittest.TestCase):
    def test_spawn_transports_ordered_pcm_and_sanitized_errors(self) -> None:
        # Bound the entire scenario, including executor shutdown, so a worker
        # regression cannot hang the suite. This script is also spawn-importable.
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--spawn-scenario"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if sys.argv[1:] == ["--spawn-scenario"]:
        _run_spawn_scenario()
    else:
        unittest.main()
