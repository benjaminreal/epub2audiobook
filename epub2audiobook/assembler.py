"""Audio assembly: combine chapter WAVs into M4B with chapter markers.

Two-phase process:
1. FFmpeg: concatenate WAVs, encode to AAC, embed chapter markers.
2. Mutagen: embed metadata tags and cover art.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from pydub import AudioSegment

from epub2audiobook.config import DEFAULT_BITRATE, DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE
from epub2audiobook.parser import BookMetadata
from epub2audiobook.utils import DependencyError, check_ffmpeg

logger = logging.getLogger(__name__)


class AssemblyError(Exception):
    """Raised when audio assembly fails."""


def assemble_audiobook(
    chapter_wav_paths: list[Path],
    metadata: BookMetadata,
    chapter_titles: list[str],
    output_path: Path,
) -> Path:
    """Assemble chapter WAV files into a single M4B audiobook.

    Args:
        chapter_wav_paths: Ordered list of WAV file paths.
        metadata: Book metadata (title, author, cover).
        chapter_titles: Ordered list of chapter title strings.
        output_path: Final output path for the M4B file.

    Returns:
        The output_path on success.

    Raises:
        DependencyError: If FFmpeg is not available.
        AssemblyError: If FFmpeg encoding or Mutagen tagging fails.
    """
    check_ffmpeg()

    if len(chapter_wav_paths) != len(chapter_titles):
        raise AssemblyError(
            f"Mismatch: {len(chapter_wav_paths)} WAV files "
            f"but {len(chapter_titles)} chapter titles."
        )

    logger.info("Assembling %d chapters into M4B...", len(chapter_wav_paths))

    # Create temp files for FFmpeg inputs
    with tempfile.TemporaryDirectory(prefix="epub2audiobook_asm_") as tmp_dir:
        tmp = Path(tmp_dir)

        # Generate FFMETADATA
        ffmetadata_content = create_ffmetadata(
            chapter_wav_paths, chapter_titles,
            metadata.title, metadata.author,
        )
        metadata_path = tmp / "ffmetadata.txt"
        metadata_path.write_text(ffmetadata_content, encoding="utf-8")

        # Generate concat list
        concat_list_path = tmp / "concat_list.txt"
        concat_lines = [
            f"file '{wav_path}'"
            for wav_path in chapter_wav_paths
        ]
        concat_list_path.write_text("\n".join(concat_lines), encoding="utf-8")

        # Phase 1: FFmpeg encode
        encode_m4b(concat_list_path, metadata_path, output_path)

    # Phase 2: Mutagen metadata
    narrator = "Piper TTS (lessac)"
    embed_metadata(output_path, metadata, narrator)

    logger.info("M4B assembly complete: %s", output_path)
    return output_path


def create_ffmetadata(
    chapter_wav_paths: list[Path],
    chapter_titles: list[str],
    title: str,
    author: str,
) -> str:
    """Generate FFMETADATA1 content with chapter markers.

    Reads each WAV file's duration using PyDub to calculate chapter
    timestamps.

    Args:
        chapter_wav_paths: Ordered list of WAV file paths.
        chapter_titles: Ordered list of chapter titles.
        title: Book title for file-level metadata.
        author: Author name for file-level metadata.

    Returns:
        FFMETADATA file content as a string.
    """
    lines = [
        ";FFMETADATA1",
        f"title={_escape_ffmetadata(title)}",
        f"artist={_escape_ffmetadata(author)}",
        "",
    ]

    cumulative_ms = 0
    for wav_path, chapter_title in zip(chapter_wav_paths, chapter_titles):
        audio = AudioSegment.from_wav(str(wav_path))
        duration_ms = len(audio)
        # Release audio from memory
        del audio

        start_ms = cumulative_ms
        end_ms = cumulative_ms + duration_ms

        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start_ms}",
            f"END={end_ms}",
            f"title={_escape_ffmetadata(chapter_title)}",
            "",
        ])

        cumulative_ms = end_ms

    return "\n".join(lines)


def encode_m4b(
    concat_list_path: Path,
    metadata_path: Path,
    output_path: Path,
) -> Path:
    """Run FFmpeg to concatenate WAVs and encode to M4B.

    Args:
        concat_list_path: Path to the FFmpeg concat list file.
        metadata_path: Path to the FFMETADATA file.
        output_path: Path for the output M4B file.

    Returns:
        The output_path.

    Raises:
        AssemblyError: If FFmpeg returns a non-zero exit code.
    """
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_path),
        "-i", str(metadata_path),
        "-map_metadata", "1",
        "-c:a", "aac",
        "-b:a", DEFAULT_BITRATE,
        "-ac", str(DEFAULT_CHANNELS),
        "-ar", str(DEFAULT_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.debug("Running FFmpeg: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise AssemblyError(
            f"FFmpeg encoding failed (exit code {result.returncode}):\n"
            f"{result.stderr}"
        )

    return output_path


def embed_metadata(
    m4b_path: Path,
    metadata: BookMetadata,
    narrator: str,
) -> None:
    """Embed metadata and cover art into an M4B file using Mutagen.

    Sets iTunes-compatible tags: title, artist, album, album artist,
    media kind (Audiobook), and cover art.

    Args:
        m4b_path: Path to the M4B file.
        metadata: Book metadata.
        narrator: Narrator name for the album artist tag.

    Raises:
        AssemblyError: If Mutagen cannot open or save the file.
    """
    try:
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError as e:
        raise AssemblyError(
            "mutagen is required but not installed. "
            "Install with: pip install mutagen"
        ) from e

    try:
        audio = MP4(str(m4b_path))
    except Exception as e:
        raise AssemblyError(f"Failed to open M4B for metadata: {e}") from e

    # Set tags
    audio["\xa9nam"] = [metadata.title]      # Title
    audio["\xa9ART"] = [metadata.author]     # Artist
    audio["\xa9alb"] = [metadata.title]      # Album = book title
    audio["aART"] = [narrator]               # Album artist = narrator
    audio["stik"] = [2]                      # Media kind: Audiobook

    # Embed cover art
    if metadata.cover_image is not None:
        if metadata.cover_format == "png":
            img_format = MP4Cover.FORMAT_PNG
        else:
            img_format = MP4Cover.FORMAT_JPEG

        audio["covr"] = [MP4Cover(metadata.cover_image, imageformat=img_format)]
        logger.info("Cover art embedded (%s)", metadata.cover_format)

    try:
        audio.save()
    except Exception as e:
        raise AssemblyError(f"Failed to save M4B metadata: {e}") from e

    logger.info("Metadata embedded: title='%s', author='%s'", metadata.title, metadata.author)


def _escape_ffmetadata(value: str) -> str:
    """Escape special characters for FFMETADATA format.

    FFMETADATA requires escaping =, ;, #, \\ and newline.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("=", "\\=")
    value = value.replace(";", "\\;")
    value = value.replace("#", "\\#")
    value = value.replace("\n", "\\\n")
    return value
