"""Logging, progress tracking, file helpers, and custom exceptions."""

import logging
import re
import shutil
import time
from pathlib import Path

from epub2audiobook.config import LOG_DATE_FORMAT, LOG_FORMAT, MAX_FILENAME_LENGTH


class DependencyError(Exception):
    """Raised when a required system dependency is missing."""


class DiskSpaceError(Exception):
    """Raised when insufficient disk space is available."""


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure root logger and return the application logger.

    Args:
        verbose: If True, set level to DEBUG. Otherwise, INFO.

    Returns:
        Configured Logger instance for 'epub2audiobook'.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
    return logging.getLogger("epub2audiobook")


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available on the system PATH.

    Returns:
        True if FFmpeg is found.

    Raises:
        DependencyError: If FFmpeg is not found.
    """
    if shutil.which("ffmpeg") is None:
        raise DependencyError(
            "FFmpeg is required but not installed. "
            "Install with: brew install ffmpeg"
        )
    return True


def check_disk_space(path: Path, required_bytes: int) -> bool:
    """Check if sufficient disk space is available.

    Args:
        path: Directory to check.
        required_bytes: Minimum bytes required.

    Returns:
        True if sufficient space is available.

    Raises:
        DiskSpaceError: If insufficient space.
    """
    stat = shutil.disk_usage(path)
    if stat.free < required_bytes:
        required_gb = required_bytes / (1024**3)
        available_gb = stat.free / (1024**3)
        raise DiskSpaceError(
            f"Insufficient disk space. "
            f"Need approximately {required_gb:.1f} GB, "
            f"{available_gb:.1f} GB available."
        )
    return True


def sanitize_filename(name: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Sanitize a string for use as a filename.

    Removes characters not in [a-zA-Z0-9 _-], replaces spaces with
    underscores, truncates to max_length.

    Args:
        name: Raw string (e.g., book title).
        max_length: Maximum filename length.

    Returns:
        Sanitized filename string (without extension).
    """
    sanitized = re.sub(r"[^a-zA-Z0-9 _-]", "", name)
    sanitized = sanitized.replace(" ", "_")
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    if not sanitized:
        sanitized = "audiobook"
    return sanitized[:max_length]


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to H:MM:SS or M:SS.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like '4:32:15' or '3:45'.
    """
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def estimate_audio_size(total_chars: int) -> int:
    """Estimate the total disk space needed for audio generation.

    Estimates WAV intermediate files and final M4B size based on
    character count and average speaking rate.

    Assumptions:
    - ~15 characters per second of speech
    - WAV at 44.1kHz 16-bit mono = ~88KB/s
    - Final M4B at 64kbps = ~8KB/s
    - WAV intermediates dominate the space requirement

    Args:
        total_chars: Total character count across all chapters.

    Returns:
        Estimated bytes required (WAVs + final M4B).
    """
    estimated_seconds = total_chars / 15.0
    wav_bytes = int(estimated_seconds * 88_200)  # 44100 Hz * 2 bytes * 1 channel
    m4b_bytes = int(estimated_seconds * 8_000)  # ~64kbps
    return wav_bytes + m4b_bytes


class ProgressTracker:
    """Tracks and displays conversion progress.

    Attributes:
        total_chapters: Total number of chapters to process.
    """

    def __init__(self, total_chapters: int) -> None:
        """Initialize the tracker.

        Args:
            total_chapters: Total number of chapters.
        """
        self.total_chapters = total_chapters
        self._start_time: float | None = None
        self._chapter_times: list[float] = []
        self._current_start: float | None = None
        self._logger = logging.getLogger("epub2audiobook.progress")

    def start_chapter(self, index: int, title: str) -> None:
        """Signal that a chapter has started processing.

        Args:
            index: 1-based chapter index.
            title: Chapter title.
        """
        if self._start_time is None:
            self._start_time = time.monotonic()
        self._current_start = time.monotonic()
        self._logger.info(
            "[%d/%d]  \"%s\"... processing...",
            index, self.total_chapters, title,
        )

    def finish_chapter(self, index: int) -> None:
        """Signal that a chapter has finished processing.

        Prints progress line with elapsed time and ETA.

        Args:
            index: 1-based chapter index.
        """
        if self._current_start is not None:
            chapter_duration = time.monotonic() - self._current_start
            self._chapter_times.append(chapter_duration)

        elapsed = self.get_elapsed()
        elapsed_str = format_duration(elapsed)
        eta = self.get_eta()

        if eta is not None:
            eta_str = format_duration(eta)
            self._logger.info(
                "[%d/%d]  done (%s)    %s elapsed, ~%s remaining",
                index, self.total_chapters,
                format_duration(self._chapter_times[-1]),
                elapsed_str, eta_str,
            )
        else:
            self._logger.info(
                "[%d/%d]  done (%s)",
                index, self.total_chapters,
                format_duration(self._chapter_times[-1]),
            )

    def get_elapsed(self) -> float:
        """Return elapsed time in seconds since first start_chapter call."""
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def get_eta(self) -> float | None:
        """Return estimated seconds remaining, or None if not enough data."""
        if not self._chapter_times:
            return None
        avg_time = sum(self._chapter_times) / len(self._chapter_times)
        remaining_chapters = self.total_chapters - len(self._chapter_times)
        if remaining_chapters <= 0:
            return 0.0
        return avg_time * remaining_chapters
