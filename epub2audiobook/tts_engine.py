"""TTS engine abstraction and Piper TTS implementation.

Provides an abstract TTSEngine base class and a concrete PiperTTSEngine
that uses the piper-tts Python library for speech synthesis.
"""

import io
import logging
import re
import struct
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from epub2audiobook.config import DEFAULT_SAMPLE_RATE, DEFAULT_VOICE, MAX_TTS_CHUNK_CHARS
from epub2audiobook.utils import DependencyError

logger = logging.getLogger(__name__)


class TTSError(Exception):
    """Raised when TTS generation fails."""


class TTSEngine(ABC):
    """Abstract base class for text-to-speech engines."""

    @abstractmethod
    def generate(self, text: str, output_path: Path) -> Path:
        """Generate audio from text and save to a WAV file.

        Args:
            text: The text to synthesize.
            output_path: Path where the WAV file should be written.

        Returns:
            The output_path on success.

        Raises:
            TTSError: If audio generation fails.
        """

    @abstractmethod
    def get_voice_name(self) -> str:
        """Return the human-readable name of the current voice."""


class PiperTTSEngine(TTSEngine):
    """Piper TTS engine implementation.

    Uses the piper-tts Python library. Auto-downloads the voice model
    on first use.
    """

    def __init__(self, voice: str = DEFAULT_VOICE) -> None:
        """Initialize the Piper TTS engine.

        Args:
            voice: Piper voice model name.

        Raises:
            DependencyError: If piper-tts is not installed.
            TTSError: If the voice model cannot be loaded or downloaded.
        """
        self._voice_name = voice

        try:
            from piper import PiperVoice  # noqa: F401
            from piper.download import ensure_voice_exists, find_voice, get_voices
        except ImportError as e:
            raise DependencyError(
                "piper-tts is required but not installed. "
                "Install with: pip install piper-tts"
            ) from e

        # Determine model directory
        self._model_dir = Path.home() / ".local" / "share" / "piper_tts"
        self._model_dir.mkdir(parents=True, exist_ok=True)

        # Download model if needed
        try:
            voices_info = get_voices(self._model_dir, update_voices=True)
            ensure_voice_exists(voice, self._model_dir, self._model_dir, voices_info)
            self._model_path, self._config_path = find_voice(voice, [self._model_dir])
        except Exception as e:
            raise TTSError(
                f"Failed to load or download voice model '{voice}': {e}"
            ) from e

        # Load the voice
        try:
            self._voice = PiperVoice.load(
                str(self._model_path),
                config_path=str(self._config_path),
            )
        except Exception as e:
            raise TTSError(f"Failed to initialize Piper voice: {e}") from e

        logger.info("Piper TTS initialized with voice: %s", voice)

    def generate(self, text: str, output_path: Path) -> Path:
        """Generate audio from text using Piper TTS.

        For texts exceeding MAX_TTS_CHUNK_CHARS, splits at sentence
        boundaries and concatenates the results.

        Args:
            text: The text to synthesize.
            output_path: Path for the output WAV file.

        Returns:
            The output_path.

        Raises:
            TTSError: If Piper fails to generate audio.
        """
        text = text.strip()
        if not text:
            return self.generate_silence(output_path)

        try:
            if len(text) <= MAX_TTS_CHUNK_CHARS:
                self._synthesize_to_wav(text, output_path)
            else:
                chunks = self._split_into_chunks(text)
                logger.debug("Split text into %d chunks for TTS", len(chunks))
                self._synthesize_chunks_to_wav(chunks, output_path)
        except TTSError:
            raise
        except Exception as e:
            raise TTSError(
                f"TTS generation failed: {e} "
                f"(text starts with: '{text[:100]}...')"
            ) from e

        return output_path

    def get_voice_name(self) -> str:
        """Return 'Piper TTS (lessac)'."""
        return f"Piper TTS ({self._voice_name.split('-')[-2]})"

    def generate_silence(self, output_path: Path, duration_ms: int = 1000) -> Path:
        """Generate a silent WAV file.

        Args:
            output_path: Path for the output WAV file.
            duration_ms: Duration of silence in milliseconds.

        Returns:
            The output_path.
        """
        sample_rate = DEFAULT_SAMPLE_RATE
        num_samples = int(sample_rate * duration_ms / 1000)
        silent_data = struct.pack(f"<{num_samples}h", *([0] * num_samples))

        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(silent_data)

        return output_path

    def _synthesize_to_wav(self, text: str, output_path: Path) -> None:
        """Synthesize text to a single WAV file."""
        with wave.open(str(output_path), "wb") as wav_file:
            self._voice.synthesize(text, wav_file)

    def _synthesize_chunks_to_wav(self, chunks: list[str], output_path: Path) -> None:
        """Synthesize multiple text chunks and concatenate to one WAV."""
        # Synthesize each chunk to a buffer, then concatenate
        all_audio_data = bytearray()
        sample_rate = None
        sample_width = None

        for i, chunk in enumerate(chunks):
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav_file:
                self._voice.synthesize(chunk, wav_file)

            buf.seek(0)
            with wave.open(buf, "rb") as wav_file:
                if sample_rate is None:
                    sample_rate = wav_file.getframerate()
                    sample_width = wav_file.getsampwidth()
                all_audio_data.extend(wav_file.readframes(wav_file.getnframes()))

        # Write concatenated audio
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(sample_width or 2)
            wav_file.setframerate(sample_rate or DEFAULT_SAMPLE_RATE)
            wav_file.writeframes(bytes(all_audio_data))

    @staticmethod
    def _split_into_chunks(text: str) -> list[str]:
        """Split text at sentence boundaries into chunks under the limit.

        Splits on sentence-ending punctuation (. ! ?) followed by
        whitespace, keeping chunks under MAX_TTS_CHUNK_CHARS.
        """
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence)
            if current_length + sentence_len > MAX_TTS_CHUNK_CHARS and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_length = 0
            current_chunk.append(sentence)
            current_length += sentence_len + 1  # +1 for space

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks
