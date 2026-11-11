"""Audio assembly: combine chapter WAVs into M4B with chapter markers.

Process:
1. FFmpeg: measure the loudness of the concatenated chapters.
2. FFmpeg: concatenate WAVs, normalize loudness, encode to AAC, embed chapters.
3. Mutagen: embed metadata tags and cover art.
"""

import json
import logging
import re
import subprocess
import tempfile
from functools import cache
from pathlib import Path

from pydub import AudioSegment

from epub2audiobook.config import (
    DEFAULT_BITRATE,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    FALLBACK_AAC_ENCODER,
    LOUDNESS_MIN_INPUT_LUFS,
    LOUDNESS_OVERSAMPLE,
    LOUDNESS_PEAK_CEILING_DBFS,
    LOUDNESS_TARGET_LUFS,
    PREFERRED_AAC_ENCODER,
)
from epub2audiobook.parser import BookMetadata
from epub2audiobook.utils import DependencyError as DependencyError
from epub2audiobook.utils import check_ffmpeg

logger = logging.getLogger(__name__)


class AssemblyError(Exception):
    """Raised when audio assembly fails."""


def assemble_audiobook(
    chapter_wav_paths: list[Path],
    metadata: BookMetadata,
    chapter_titles: list[str],
    output_path: Path,
    narrator: str,
) -> Path:
    """Assemble chapter WAV files into a single M4B audiobook.

    Args:
        chapter_wav_paths: Ordered list of WAV file paths.
        metadata: Book metadata (title, author, cover).
        chapter_titles: Ordered list of chapter title strings.
        output_path: Final output path for the M4B file.
        narrator: Narrator name for the album artist tag (the TTS voice).

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

        # Phase 1: loudness measurement; phase 2: FFmpeg encode
        audio_filter = normalization_filter(measure_loudness(concat_list_path))
        encode_m4b(concat_list_path, metadata_path, output_path, audio_filter)

    # Phase 3: Mutagen metadata
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


def measure_loudness(concat_list_path: Path) -> dict[str, float]:
    """Measure the concatenated chapters with FFmpeg loudnorm (first pass).

    Args:
        concat_list_path: Path to the FFmpeg concat list file.

    Returns:
        loudnorm's input_i, input_tp, input_lra, input_thresh and
        target_offset as floats (-inf for silence).

    Raises:
        AssemblyError: If FFmpeg fails or prints no measurement.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssemblyError(
            f"FFmpeg loudness measurement failed (exit code {result.returncode})"
        )
    return parse_loudnorm_json(result.stderr)


def parse_loudnorm_json(stderr: str) -> dict[str, float]:
    """Extract loudnorm's JSON summary from FFmpeg's stderr.

    Raises:
        AssemblyError: If no summary is found.
    """
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr)
    if not match:
        raise AssemblyError("FFmpeg printed no loudness measurement")
    data = json.loads(match.group(0))
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    return {k: float(data[k]) for k in keys}


def normalization_filter(measured: dict[str, float]) -> str | None:
    """Build the filter that brings the book to the target loudness.

    One fixed gain for the whole book, so quiet and loud passages keep their
    balance, then a lookahead limiter at LOUDNESS_OVERSAMPLE times the output
    rate that only acts on the rare peaks above the ceiling. Returns None for
    silence, which has no loudness to normalize.

    FFmpeg's loudnorm is not used for this step: when the gain would push peaks
    over its limit it switches to dynamic mode, which put sub-millisecond
    bursts near full scale into a full-book render.
    """
    if not measured["input_i"] > LOUDNESS_MIN_INPUT_LUFS:  # also catches -inf/NaN
        logger.warning("Audio is silent or nearly silent; loudness not normalized")
        return None
    gain = LOUDNESS_TARGET_LUFS - measured["input_i"]
    logger.info(
        "Measured %.1f LUFS, true peak %.1f dBTP; applying %+.1f dB gain to %.1f "
        "LUFS with peaks limited to %.1f dBFS",
        measured["input_i"], measured["input_tp"], gain, LOUDNESS_TARGET_LUFS,
        LOUDNESS_PEAK_CEILING_DBFS,
    )  # fmt: skip
    ceiling = 10 ** (LOUDNESS_PEAK_CEILING_DBFS / 20)
    return (
        f"volume={gain:.2f}dB,"
        f"aresample={LOUDNESS_OVERSAMPLE * DEFAULT_SAMPLE_RATE},"
        f"alimiter=limit={ceiling:.4f}:attack=5:release=50:level=false:latency=true,"
        f"aresample={DEFAULT_SAMPLE_RATE}"
    )


@cache
def aac_encoder() -> str:
    """Return the AAC encoder to use: Apple's when FFmpeg has it, else FFmpeg's.

    Logs a warning on fallback, because FFmpeg's own encoder can push peaks
    over the release limit on long books.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    )
    if re.search(rf"^\s*A\S*\s+{PREFERRED_AAC_ENCODER}\s", result.stdout, re.M):
        return PREFERRED_AAC_ENCODER
    logger.warning(
        "FFmpeg has no %s encoder; using %s, which may exceed the peak limit",
        PREFERRED_AAC_ENCODER, FALLBACK_AAC_ENCODER,
    )  # fmt: skip
    return FALLBACK_AAC_ENCODER


def _encoder_args(encoder: str) -> list[str]:
    args = ["-c:a", encoder]
    if encoder == PREFERRED_AAC_ENCODER:
        args += ["-aac_at_mode", "cbr"]
    return [*args, "-b:a", DEFAULT_BITRATE]


def encode_m4b(
    concat_list_path: Path,
    metadata_path: Path,
    output_path: Path,
    audio_filter: str | None = None,
) -> Path:
    """Run FFmpeg to concatenate WAVs and encode to M4B (AAC, see aac_encoder).

    Args:
        concat_list_path: Path to the FFmpeg concat list file.
        metadata_path: Path to the FFMETADATA file.
        output_path: Path for the output M4B file.
        audio_filter: Optional FFmpeg audio filter, such as normalization.

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
        *(["-af", audio_filter] if audio_filter else []),
        *_encoder_args(aac_encoder()),
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

    logger.info(
        "Metadata embedded: title='%s', author='%s'", metadata.title, metadata.author
    )


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
