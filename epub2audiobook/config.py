"""Application constants and default configuration values."""

from pathlib import Path

# Version
VERSION: str = "0.1.0"

# TTS
DEFAULT_ENGINE: str = "kokoro"
DEFAULT_KOKORO_VOICE: str = "af_heart"
DEFAULT_PIPER_VOICE: str = "en_US-lessac-medium"
KOKORO_MODEL_DIR: Path = Path.home() / ".local" / "share" / "kokoro_onnx"
KOKORO_MODEL_URL: str = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
)
KOKORO_MODEL_FILE: str = "kokoro-v1.0.onnx"
KOKORO_VOICES_FILE: str = "voices-v1.0.bin"
PIPER_MODEL_DIR: Path = Path.home() / ".local" / "share" / "piper_tts"
# Kokoro holds a whole call's audio in RAM; 2,000 chars is about 2 minutes
MAX_TTS_CHUNK_CHARS: int = 2_000

# Pauses (Piper butts sentences together; Kokoro adds its own sentence pauses)
SENTENCE_PAUSE_MS: int = 300
PARAGRAPH_PAUSE_MS: int = 600

# Audio encoding
DEFAULT_BITRATE: str = "64k"
DEFAULT_SAMPLE_RATE: int = 44_100
DEFAULT_CHANNELS: int = 1  # mono
# Apple's AAC encoder (FFmpeg's AudioToolbox wrapper, macOS only). FFmpeg's own
# "aac" encoder added near-full-scale bursts to a full-length book encode that
# the same audio did not have before encoding; it is only a fallback.
PREFERRED_AAC_ENCODER: str = "aac_at"
FALLBACK_AAC_ENCODER: str = "aac"

# Loudness normalization (release definition V1-05: -18 +/- 1 LUFS, true peak
# at or below -3 dBTP, measured on the M4B with ffmpeg ebur128). One fixed gain
# brings the book to the target; a lookahead limiter, run at 4x the output
# sample rate so it also catches peaks between samples, holds the rare peaks
# under the ceiling. AAC encoding raises peaks by about 2 dB, so the ceiling
# sits below the release limit.
LOUDNESS_TARGET_LUFS: float = -18.0
LOUDNESS_PEAK_CEILING_DBFS: float = -6.0
LOUDNESS_OVERSAMPLE: int = 4
# Below this measured loudness (silence or near-silence) normalization is skipped.
LOUDNESS_MIN_INPUT_LUFS: float = -70.0

# Output
DEFAULT_OUTPUT_DIR: Path = Path.home() / "Downloads"
MAX_FILENAME_LENGTH: int = 200

# Chapter detection
MIN_CHAPTER_CHARS: int = 50
FLAT_EPUB_MAX_SPINE_ITEMS: int = 3
FLAT_EPUB_MIN_TEXT_LENGTH: int = 20_000

# Logging
LOG_FORMAT: str = "%(levelname)s [%(name)s] %(asctime)s - %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
