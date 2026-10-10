"""Bounded, ordered Kokoro synthesis across CPU worker processes."""

import importlib.util
import multiprocessing
import re
import wave
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
from itertools import chain
from pathlib import Path
from typing import Iterator

import numpy as np

from epub2audiobook.config import (
    DEFAULT_KOKORO_VOICE,
    KOKORO_MODEL_DIR,
    KOKORO_MODEL_FILE,
    KOKORO_MODEL_URL,
    KOKORO_VOICES_FILE,
    MAX_TTS_CHUNK_CHARS,
    PARAGRAPH_PAUSE_MS,
)
from epub2audiobook.tts_engine import (
    KOKORO_LANGUAGES,
    TTSError,
    _download_if_missing,
    _has_speakable_text,
    _split_long_text,
    _suppress_kokoro_logging,
)
from epub2audiobook.utils import DependencyError

WORKERS = 6
THREADS_PER_WORKER = 2
SAMPLE_RATE = 24_000

# Each spawned process owns one model. This cache is never shared between jobs.
_worker_model = None


class _WorkerError(Exception):
    """Content-free error transported from a worker process."""


def _available_voices(voices_path: Path) -> tuple[str, ...]:
    """Read voice names from the ONNX voice pack without loading its model."""
    try:
        with np.load(voices_path, allow_pickle=False) as voices:
            if not isinstance(voices, np.lib.npyio.NpzFile):
                raise ValueError("Unexpected voice-pack format")
            available = tuple(sorted(voices.files))
        if not available:
            raise ValueError("Voice pack is empty")
        return available
    except Exception as error:
        raise TTSError(
            f"Failed to read Kokoro voice catalogue ({type(error).__name__})"
        ) from None


def _synthesize_chunk(
    text: str, voice: str, language: str, model_path: str, voices_path: str
) -> tuple[bytes, int]:
    """Load one model per worker and synthesize a bounded text chunk."""
    global _worker_model
    try:
        with _suppress_kokoro_logging():
            if _worker_model is None:
                import onnxruntime as ort
                from kokoro_onnx import Kokoro

                options = ort.SessionOptions()
                options.intra_op_num_threads = THREADS_PER_WORKER
                options.inter_op_num_threads = 1
                session = ort.InferenceSession(
                    model_path,
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
                _worker_model = Kokoro.from_session(session, voices_path)
            audio, sample_rate = _worker_model.create(
                text, voice=voice, lang=language
            )
        if sample_rate != SAMPLE_RATE:
            raise ValueError("Unexpected Kokoro sample rate")
        frames = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        return frames, sample_rate
    except Exception as error:
        # Remote tracebacks are serialized by ProcessPoolExecutor. Never let
        # backend exception text or a chained exception cross that boundary.
        raise _WorkerError(type(error).__name__) from None


def _units(text: str) -> Iterator[str | None]:
    """Yield speakable chunks and a pause marker after each paragraph."""
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not paragraph:
            continue
        for chunk in _split_long_text(paragraph, MAX_TTS_CHUNK_CHARS):
            if _has_speakable_text(chunk):
                yield chunk
        yield None


class KokoroParallelEngine:
    """Kokoro ONNX with six persistent CPU workers and ordered WAV output."""

    sample_rate = SAMPLE_RATE

    def __init__(self, voice: str = DEFAULT_KOKORO_VOICE) -> None:
        """Prepare model assets without loading a model in the parent process."""
        if importlib.util.find_spec("kokoro_onnx") is None:
            raise DependencyError("kokoro-onnx is required for the ONNX backend")
        if importlib.util.find_spec("onnxruntime") is None:
            raise DependencyError("onnxruntime is required for the ONNX backend")
        language = KOKORO_LANGUAGES.get(voice[:1])
        if language is None:
            raise TTSError(f"Unsupported Kokoro voice '{voice}'")

        try:
            KOKORO_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            voices_path = KOKORO_MODEL_DIR / KOKORO_VOICES_FILE
            _download_if_missing(KOKORO_MODEL_URL + KOKORO_VOICES_FILE, voices_path)
            available_voices = _available_voices(voices_path)
        except TTSError:
            raise
        except Exception as error:
            raise TTSError(
                f"Failed to prepare Kokoro voice catalogue ({type(error).__name__})"
            ) from None

        if voice not in available_voices:
            raise TTSError(
                f"Unknown Kokoro voice '{voice}'. Available: "
                f"{', '.join(available_voices)}"
            )

        try:
            model_path = KOKORO_MODEL_DIR / KOKORO_MODEL_FILE
            _download_if_missing(KOKORO_MODEL_URL + KOKORO_MODEL_FILE, model_path)
        except Exception as error:
            raise TTSError(
                f"Failed to prepare Kokoro model ({type(error).__name__})"
            ) from None

        self._voice = voice
        self._language = language
        self._model_path = str(model_path)
        self._voices_path = str(voices_path)
        self._pool: ProcessPoolExecutor | None = None

    def get_voice_name(self) -> str:
        """Return the narrator label stored in the audiobook."""
        return f"Kokoro ONNX ({self._voice})"

    def close(self) -> None:
        """Stop workers before the conversion temporary directory is removed."""
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None

    def generate(self, text: str, output_path: Path) -> Path:
        """Generate ordered chapter audio with bounded queued work."""
        units = iter(_units(text))
        first = next(units, Ellipsis)
        if first is Ellipsis:
            self._write_silence(output_path, 1000)
            return output_path

        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=WORKERS,
                mp_context=multiprocessing.get_context("spawn"),
            )

        pending: deque[Future[tuple[bytes, int]] | None] = deque()
        remaining = chain((first,), units)

        def fill_queue() -> None:
            while len(pending) < 2 * WORKERS:
                unit = next(remaining, Ellipsis)
                if unit is Ellipsis:
                    break
                pending.append(
                    None
                    if unit is None
                    else self._pool.submit(
                        _synthesize_chunk,
                        unit,
                        self._voice,
                        self._language,
                        self._model_path,
                        self._voices_path,
                    )
                )

        pause = bytes(2 * int(SAMPLE_RATE * PARAGRAPH_PAUSE_MS / 1000))
        try:
            fill_queue()
            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(SAMPLE_RATE)
                while pending:
                    future = pending.popleft()
                    if future is None:
                        wav_file.writeframes(pause)
                    else:
                        frames, sample_rate = future.result()
                        if sample_rate != SAMPLE_RATE:
                            raise ValueError("Unexpected Kokoro sample rate")
                        wav_file.writeframes(frames)
                    fill_queue()
        except Exception as error:
            message = f"TTS generation failed ({type(error).__name__})"
            try:
                output_path.unlink(missing_ok=True)
            except Exception as cleanup_error:
                message += (
                    "; partial audio cleanup failed "
                    f"({type(cleanup_error).__name__})"
                )
            try:
                self.close()
            except Exception as shutdown_error:
                message += (
                    "; worker shutdown failed "
                    f"({type(shutdown_error).__name__})"
                )
            raise TTSError(message) from None
        return output_path

    def _write_silence(self, output_path: Path, duration_ms: int) -> None:
        """Create an empty chapter at the backend's sample rate."""
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(bytes(2 * int(SAMPLE_RATE * duration_ms / 1000)))
