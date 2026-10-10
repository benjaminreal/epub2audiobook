"""Optional Kokoro synthesis on the Apple GPU through MLX-Audio."""

import logging
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from epub2audiobook.config import DEFAULT_KOKORO_VOICE
from epub2audiobook.tts_engine import KOKORO_LANGUAGES, TTSEngine, TTSError
from epub2audiobook.utils import DependencyError

MLX_MODEL_ID = "mlx-community/Kokoro-82M-bf16"
MLX_VOICE_PATTERN = "voices/*.safetensors"


def _available_voices(voices_directory: Path) -> tuple[str, ...]:
    """Return names from locally cached MLX voice-pack assets."""
    try:
        available = tuple(
            sorted(
                path.stem
                for path in voices_directory.iterdir()
                if path.name.endswith(".safetensors") and path.is_file()
            )
        )
    except Exception as error:
        raise TTSError(
            f"Failed to read Kokoro MLX voice catalogue ({type(error).__name__})"
        ) from None
    if not available:
        raise TTSError(
            "Failed to read Kokoro MLX voice catalogue (no voice assets)"
        ) from None
    return available


@contextmanager
def _suppress_mlx_content_logs() -> Iterator[None]:
    """Hide root logger records emitted by MLX-Audio during book synthesis."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


class MLXKokoroEngine(TTSEngine):
    """Generate Kokoro audio with the optional MLX-Audio package."""

    sample_rate = 24_000

    def __init__(self, voice: str = DEFAULT_KOKORO_VOICE) -> None:
        """Load the MLX Kokoro model for an Apple Silicon run."""
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise DependencyError("The MLX backend requires an Apple Silicon Mac")
        if voice[:1] not in KOKORO_LANGUAGES:
            raise TTSError(f"Unsupported Kokoro voice '{voice}'")
        try:
            from huggingface_hub import snapshot_download
            from mlx_audio.tts.utils import load_model
            import misaki  # noqa: F401 — needed by the Kokoro phonemizer
        except ImportError:
            raise DependencyError(
                "The MLX backend requires the optional dependencies. "
                "Install epub2audiobook[mlx]."
            ) from None

        try:
            self._model = load_model(MLX_MODEL_ID)
        except Exception as error:
            raise TTSError(
                f"Failed to initialize Kokoro MLX ({type(error).__name__})"
            ) from None

        try:
            model_snapshot = snapshot_download(
                repo_id=MLX_MODEL_ID,
                allow_patterns=[MLX_VOICE_PATTERN],
                local_files_only=True,
            )
            available_voices = _available_voices(Path(model_snapshot) / "voices")
        except TTSError:
            raise
        except Exception as error:
            raise TTSError(
                f"Failed to read Kokoro MLX voice catalogue ({type(error).__name__})"
            ) from None

        if voice not in available_voices:
            raise TTSError(
                f"Unknown Kokoro voice '{voice}'. Available: "
                f"{', '.join(available_voices)}"
            )

        self._voice = voice
        self._language = voice[:1]

    def get_voice_name(self) -> str:
        """Return the narrator label stored in the audiobook."""
        return f"Kokoro MLX ({self._voice})"

    def _synthesize_paragraph(self, text: str) -> Iterator[bytes]:
        """Yield 16-bit mono PCM frames from MLX generation results."""
        yielded = False
        with _suppress_mlx_content_logs():
            results = iter(
                self._model.generate(
                    text=text,
                    voice=self._voice,
                    speed=1.0,
                    lang_code=self._language,
                )
            )
        while True:
            with _suppress_mlx_content_logs():
                try:
                    result = next(results)
                except StopIteration:
                    break
                if result.sample_rate != self.sample_rate:
                    raise TTSError("Unexpected Kokoro MLX sample rate")
                audio = np.asarray(result.audio)
                if audio.ndim != 1:
                    raise TTSError("Unexpected Kokoro MLX audio shape")
                yielded = True
                frames = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            yield frames
        if not yielded:
            raise TTSError("Kokoro MLX produced no audio")
