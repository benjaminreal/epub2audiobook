"""Application constants and default configuration values."""

from pathlib import Path

# Version
VERSION: str = "0.1.0"

# TTS
DEFAULT_VOICE: str = "en_US-lessac-medium"
MAX_TTS_CHUNK_CHARS: int = 10_000

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
