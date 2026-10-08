"""TTS engine abstraction with Kokoro and Piper implementations.

Provides an abstract TTSEngine base class that synthesizes text paragraph
by paragraph with a pause between paragraphs, and two concrete engines:
KokoroTTSEngine (default, more natural) and PiperTTSEngine (faster).
"""

import logging
import re
import urllib.request
import wave
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from epub2audiobook.config import (
    DEFAULT_ENGINE,
    DEFAULT_KOKORO_VOICE,
    DEFAULT_PIPER_VOICE,
    KOKORO_MODEL_DIR,
    KOKORO_MODEL_FILE,
    KOKORO_MODEL_URL,
    KOKORO_VOICES_FILE,
    PARAGRAPH_PAUSE_MS,
    PIPER_MODEL_DIR,
    SENTENCE_PAUSE_MS,
)
from epub2audiobook.utils import DependencyError

logger = logging.getLogger(__name__)

# Kokoro voice-name prefix -> espeak language code
KOKORO_LANGUAGES: dict[str, str] = {
    "a": "en-us",
    "b": "en-gb",
    "e": "es",
    "f": "fr-fr",
    "h": "hi",
    "i": "it",
    "p": "pt-br",
}


class TTSError(Exception):
    """Raised when TTS generation fails."""


class TTSEngine(ABC):
    """Abstract base class for text-to-speech engines.

    Subclasses set `sample_rate` and implement `_synthesize_paragraph`.
    Every WAV an engine writes uses that one sample rate, which FFmpeg's
    concat demuxer requires.
    """

    sample_rate: int

    @abstractmethod
    def _synthesize_paragraph(self, text: str) -> Iterator[bytes]:
        """Yield 16-bit mono PCM frames for one paragraph."""

    @abstractmethod
    def get_voice_name(self) -> str:
        """Return the human-readable name of the current voice."""

    def generate(self, text: str, output_path: Path) -> Path:
        """Generate audio from text and save to a WAV file.

        Synthesizes paragraph by paragraph, streaming to disk, with a
        pause after each paragraph.

        Args:
            text: The text to synthesize.
            output_path: Path where the WAV file should be written.

        Returns:
            The output_path on success.

        Raises:
            TTSError: If audio generation fails.
        """
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            return self.generate_silence(output_path)

        pause = self._silence(PARAGRAPH_PAUSE_MS)
        try:
            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                for paragraph in paragraphs:
                    for frames in self._synthesize_paragraph(paragraph):
                        wav_file.writeframes(frames)
                    wav_file.writeframes(pause)
        except TTSError:
            raise
        except Exception as e:
            raise TTSError(
                f"TTS generation failed: {e} "
                f"(text starts with: '{text[:100]}...')"
            ) from e

        return output_path

    def generate_silence(self, output_path: Path, duration_ms: int = 1000) -> Path:
        """Generate a silent WAV file at the engine's sample rate.

        Args:
            output_path: Path for the output WAV file.
            duration_ms: Duration of silence in milliseconds.

        Returns:
            The output_path.
        """
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(self._silence(duration_ms))

        return output_path

    def _silence(self, duration_ms: int) -> bytes:
        """Return 16-bit mono silence of the given duration."""
        return bytes(2 * int(self.sample_rate * duration_ms / 1000))


class KokoroTTSEngine(TTSEngine):
    """Kokoro TTS engine implementation (via kokoro-onnx).

    Downloads the model and voice pack on first use.
    """

    def __init__(self, voice: str = DEFAULT_KOKORO_VOICE) -> None:
        """Initialize the Kokoro TTS engine.

        Args:
            voice: Kokoro voice name (e.g., 'af_heart', 'bm_george').

        Raises:
            DependencyError: If kokoro-onnx is not installed.
            TTSError: If the model cannot be loaded or the voice is unknown.
        """
        self._voice_name = voice

        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise DependencyError(
                "kokoro-onnx is required but not installed. "
                "Install with: pip install kokoro-onnx"
            ) from e

        self._lang = KOKORO_LANGUAGES.get(voice[:1])
        if self._lang is None:
            raise TTSError(
                f"Unsupported Kokoro voice '{voice}'. Supported prefixes: "
                f"{', '.join(sorted(KOKORO_LANGUAGES))}"
            )

        try:
            KOKORO_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            for filename in (KOKORO_MODEL_FILE, KOKORO_VOICES_FILE):
                _download_if_missing(KOKORO_MODEL_URL + filename,
                                     KOKORO_MODEL_DIR / filename)
            self._kokoro = Kokoro(
                str(KOKORO_MODEL_DIR / KOKORO_MODEL_FILE),
                str(KOKORO_MODEL_DIR / KOKORO_VOICES_FILE),
            )
        except Exception as e:
            raise TTSError(f"Failed to load Kokoro model: {e}") from e

        if voice not in self._kokoro.get_voices():
            raise TTSError(
                f"Unknown Kokoro voice '{voice}'. Available: "
                f"{', '.join(sorted(self._kokoro.get_voices()))}"
            )

        self.sample_rate = 24_000
        logger.info("Kokoro TTS initialized with voice: %s", voice)

    def get_voice_name(self) -> str:
        """Return e.g. 'Kokoro (af_heart)'."""
        return f"Kokoro ({self._voice_name})"

    def _synthesize_paragraph(self, text: str) -> Iterator[bytes]:
        audio, sample_rate = self._kokoro.create(
            text, voice=self._voice_name, lang=self._lang
        )
        if sample_rate != self.sample_rate:
            raise TTSError(
                f"Kokoro returned {sample_rate} Hz, expected {self.sample_rate} Hz"
            )
        yield (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class PiperTTSEngine(TTSEngine):
    """Piper TTS engine implementation.

    Faster than Kokoro but less natural. Auto-downloads the voice model
    on first use. Piper emits sentences back to back, so a short pause is
    inserted after each sentence.
    """

    def __init__(self, voice: str = DEFAULT_PIPER_VOICE) -> None:
        """Initialize the Piper TTS engine.

        Args:
            voice: Piper voice model name.

        Raises:
            DependencyError: If piper-tts is not installed.
            TTSError: If the voice model cannot be loaded or downloaded.
        """
        self._voice_name = voice

        try:
            from piper import PiperVoice
            from piper.download_voices import download_voice
        except ImportError as e:
            raise DependencyError(
                "piper-tts is required but not installed. "
                "Install with: pip install piper-tts"
            ) from e

        PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)

        try:
            download_voice(voice, PIPER_MODEL_DIR)
            self._voice = PiperVoice.load(
                str(PIPER_MODEL_DIR / f"{voice}.onnx"),
                config_path=str(PIPER_MODEL_DIR / f"{voice}.onnx.json"),
            )
        except Exception as e:
            raise TTSError(f"Failed to load Piper voice '{voice}': {e}") from e

        self.sample_rate = self._voice.config.sample_rate
        logger.info("Piper TTS initialized with voice: %s", voice)

    def get_voice_name(self) -> str:
        """Return 'Piper TTS (lessac)'."""
        return f"Piper TTS ({self._voice_name.split('-')[-2]})"

    def _synthesize_paragraph(self, text: str) -> Iterator[bytes]:
        pause = self._silence(SENTENCE_PAUSE_MS)
        for chunk in self._voice.synthesize(text):
            yield chunk.audio_int16_bytes
            yield pause


def create_tts_engine(
    engine: str = DEFAULT_ENGINE,
    voice: str | None = None,
) -> TTSEngine:
    """Build a TTS engine by name.

    Args:
        engine: 'kokoro' or 'piper'.
        voice: Voice name; None selects the engine's default voice.

    Returns:
        An initialized TTSEngine.

    Raises:
        DependencyError: If the engine's package is not installed.
        TTSError: If the engine name, model, or voice is invalid.
    """
    if engine == "kokoro":
        return KokoroTTSEngine(voice or DEFAULT_KOKORO_VOICE)
    if engine == "piper":
        return PiperTTSEngine(voice or DEFAULT_PIPER_VOICE)
    raise TTSError(f"Unknown TTS engine '{engine}'. Choose 'kokoro' or 'piper'.")


def _download_if_missing(url: str, path: Path) -> None:
    """Download url to path unless it already exists (atomic rename)."""
    if path.exists() and path.stat().st_size > 0:
        return
    logger.info("Downloading %s (first run only)...", path.name)
    partial = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url) as response, open(partial, "wb") as f:
        while block := response.read(1 << 20):
            f.write(block)
    partial.rename(path)
