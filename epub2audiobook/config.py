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
