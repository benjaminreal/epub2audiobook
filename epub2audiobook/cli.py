"""Entry point: argument parsing, validation, and pipeline orchestration."""

import argparse
import logging
import os
import platform
import stat
import subprocess
import sys
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path

from epub2audiobook.config import DEFAULT_ENGINE, DEFAULT_OUTPUT_DIR, VERSION
from epub2audiobook.utils import (
    DependencyError,
    DiskSpaceError,
    check_disk_space,
    check_ffmpeg,
    estimate_audio_size,
    format_duration,
    sanitize_filename,
    setup_logging,
    ProgressTracker,
)

logger = logging.getLogger(__name__)


class InputError(Exception):
    """Raised for input validation failures."""


def main() -> int:
    """Application entry point.

    Parses arguments, runs the conversion pipeline, handles top-level
    errors, and returns an exit code.

    Returns:
        Exit code: 0 (success), 1 (input error), 2 (dependency error),
        3 (processing error).
    """
    args = parse_args()
    setup_logging(verbose=args.verbose)

    if args.version:
        print(f"epub2audiobook v{VERSION}")
        return 0

    # Warn if not ARM64
    if platform.machine() != "arm64":
        logger.warning(
            "This tool is optimized for Apple Silicon (ARM64). "
            "Performance may be degraded on %s.", platform.machine()
        )

    # Resolve ePub path
    epub_path = args.epub_path
    if epub_path is None:
        epub_path = open_file_dialog()
        if epub_path is None:
            print(
                f"Usage: python -m epub2audiobook <epub_path> [OPTIONS]\n"
                f"\n"
                f"Options:\n"
                f"  --output, -o  Output path for the M4B file\n"
                "  --engine      TTS engine: kokoro (default) or piper\n"
                "  --backend     Kokoro backend: onnx (default) or mlx\n"
                "  --voice       Voice name (default depends on engine)\n"
                f"  --verbose, -v Enable debug logging\n"
                f"  --version     Print version and exit",
                file=sys.stderr,
            )
            return 1

    try:
        epub_path = validate_input(epub_path)
    except InputError as e:
        logger.error("%s", e)
        return 1

    # Check dependencies
    try:
        check_ffmpeg()
    except DependencyError as e:
        logger.error("%s", e)
        return 2

    # Import pipeline modules (deferred to avoid import errors if deps missing)
    try:
        from epub2audiobook.assembler import AssemblyError, assemble_audiobook
        from epub2audiobook.parser import BookMetadata, ParsingError, parse_epub
        from epub2audiobook.preprocessor import preprocess_text
        from epub2audiobook.tts_engine import TTSError, create_tts_engine
    except ImportError as e:
        logger.error("Missing dependency: %s", e)
        return 2

    # Stage 1-3: Parse ePub
    try:
        logger.info("Loading: %s", epub_path.name)
        metadata, chapters = parse_epub(epub_path)
        logger.info("Author:  %s", metadata.author)
        logger.info("Chapters: %d detected", len(chapters))
    except ParsingError as e:
        logger.error("%s", e)
        return 3

    try:
        output_path = _resolve_output_path(args.output, metadata.title)
    except InputError as e:
        logger.error("%s", e)
        return 1

    # Stage 4: Preprocess text
    for chapter in chapters:
        chapter.text = preprocess_text(chapter.text)

    total_chars = sum(len(ch.text) for ch in chapters)
    logger.info("Total text: %d characters", total_chars)

    # Check disk space
    try:
        estimated_size = estimate_audio_size(total_chars)
        check_disk_space(Path(tempfile.gettempdir()), estimated_size)
    except DiskSpaceError as e:
        logger.error("%s", e)
        return 3

    # Stage 5: TTS generation
    try:
        tts = create_tts_engine(
            args.engine, args.voice, getattr(args, "backend", "onnx")
        )
    except DependencyError as e:
        logger.error("%s", e)
        return 2
    except TTSError as e:
        logger.error("%s", e)
        return 2

    chapter_wav_paths: list[Path] = []
    chapter_titles: list[str] = []
    skipped_chapters: list[tuple[int, str]] = []
    progress = ProgressTracker(len(chapters))

    try:
        temp_context = tempfile.TemporaryDirectory(prefix="epub2audiobook_")
    except OSError as e:
        logger.error(
            "Cannot create conversion temporary directory: %s",
            _safe_os_error(e),
        )
        return 3

    with ExitStack() as stack:
        temp_dir_name = stack.enter_context(temp_context)
        close_tts = getattr(tts, "close", None)
        if callable(close_tts):
            stack.callback(close_tts)
        temp_dir = Path(temp_dir_name)
        logger.debug("Temp directory: %s", temp_dir)

        for chapter in chapters:
            idx = chapter.index + 1
            progress.start_chapter(idx, chapter.title)

            wav_path = temp_dir / f"chapter_{idx:03d}.wav"

            try:
                tts.generate(chapter.text, wav_path)
                chapter_wav_paths.append(wav_path)
                chapter_titles.append(chapter.title)
            except TTSError:
                logger.warning(
                    "TTS synthesis failed for chapter %d (TTSError)", idx
                )
                skipped_chapters.append((idx, chapter.title))
                continue

            progress.finish_chapter(idx)

        if not chapter_wav_paths:
            logger.error("All chapters failed TTS generation. No output produced.")
            return 3

        # Stage 6: Assembly and output stat are one filesystem boundary.
        try:
            try:
                output_path.stat()
            except FileNotFoundError:
                pass
            else:
                logger.warning("Overwriting existing file: %s", output_path)

            assemble_audiobook(
                chapter_wav_paths, metadata, chapter_titles, output_path,
                tts.get_voice_name(),
            )
            output_stat = output_path.stat()
            if not stat.S_ISREG(output_stat.st_mode):
                raise OSError("assembled output is not a regular file")
            file_size_mb = output_stat.st_size / (1024 * 1024)
        except (AssemblyError, DependencyError) as e:
            logger.error("Assembly failed: %s", e)
            return 3
        except OSError as e:
            logger.error("Output filesystem error: %s", _safe_os_error(e))
            return 3

    # Print summary
    elapsed = progress.get_elapsed()

    # Calculate total duration from the M4B
    try:
        from mutagen.mp4 import MP4
        duration_str = format_duration(MP4(str(output_path)).info.length)
    except Exception:
        duration_str = "unknown"

    print(f"\nAudiobook created successfully!")
    print(f"  Output:    {output_path}")
    print(f"  Size:      {file_size_mb:.1f} MB")
    print(f"  Duration:  {duration_str}")
    print(f"  Chapters:  {len(chapter_wav_paths)}")
    print(f"  Time:      {format_duration(elapsed)}")

    if skipped_chapters:
        print(f"\nWarning: {len(skipped_chapters)} chapter(s) skipped due to TTS errors:")
        for idx, title in skipped_chapters:
            print(f"  - Chapter {idx}: \"{title}\" (TTS synthesis failed: TTSError)")

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list. If None, uses sys.argv[1:].

    Returns:
        Namespace with epub_path, output, engine, voice, verbose, version.
    """
    parser = argparse.ArgumentParser(
        prog="epub2audiobook",
        description="Convert ePub files to M4B audiobooks with chapter markers.",
    )
    parser.add_argument(
        "epub_path",
        nargs="?",
        type=Path,
        default=None,
        help="Path to the .epub file. Opens file dialog if omitted.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help=f"Output path for the M4B file (default: {DEFAULT_OUTPUT_DIR}/{{title}}.m4b)",
    )
    parser.add_argument(
        "--engine",
        choices=["kokoro", "piper"],
        default=DEFAULT_ENGINE,
        help=f"TTS engine (default: {DEFAULT_ENGINE}). "
             "Kokoro sounds more natural; Piper is about 8x faster.",
    )
    parser.add_argument(
        "--backend",
        choices=["onnx", "mlx"],
        default="onnx",
        help="Kokoro runtime (default: onnx). MLX requires the optional extra.",
    )
    parser.add_argument(
        "--voice",
        default=None,
        help="Voice name, e.g. af_heart or bm_george for Kokoro, "
             "en_US-lessac-medium for Piper (default: the engine's default).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version number and exit.",
    )
    return parser.parse_args(argv)


def validate_input(path: Path) -> Path:
    """Validate that the given path is a processable ePub file.

    Args:
        path: Path to validate.

    Returns:
        The validated absolute Path.

    Raises:
        InputError: If any validation check fails.
    """
    path = path.expanduser().resolve()

    if not path.exists():
        raise InputError(f"File not found: {path}")

    if path.suffix.lower() != ".epub":
        raise InputError(
            f"Not an ePub file: {path.name}. Expected a file with .epub extension."
        )

    if not zipfile.is_zipfile(path):
        raise InputError(f"Invalid or corrupt ePub file: {path.name}")

    # Check for DRM
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "META-INF/encryption.xml" in zf.namelist():
                encryption_content = zf.read("META-INF/encryption.xml").decode(
                    "utf-8", errors="replace"
                )
                if "EncryptedData" in encryption_content:
                    raise InputError(
                        "This ePub is DRM-protected and cannot be converted. "
                        "Please use a DRM-free ePub."
                    )
    except zipfile.BadZipFile:
        raise InputError(f"Invalid or corrupt ePub file: {path.name}")

    return path


def open_file_dialog() -> Path | None:
    """Open a native macOS file dialog to select an ePub file.

    Uses osascript to invoke a Cocoa file dialog filtered to .epub files.

    Returns:
        Path to the selected file, or None if the user cancelled.
    """
    if sys.platform != "darwin":
        return None

    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'POSIX path of (choose file of type '
                '{"org.idpf.epub-container"} '
                'with prompt "Select an ePub file")',
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    path_str = result.stdout.strip()
    if not path_str:
        return None

    return Path(path_str)


def _resolve_output_path(output_arg: Path | None, title: str) -> Path:
    """Determine and validate the output path for the M4B file.

    Runs before TTS, so a bad path fails in seconds rather than after
    hours of synthesis. A directory, or a path without an extension, gets
    the default '{title}.m4b' filename and is created if missing.

    Raises:
        InputError: If the path has an extension other than .m4b, or the
            directory cannot be created.
    """
    filename = sanitize_filename(title) + ".m4b"
    try:
        if output_arg is None:
            output_dir = DEFAULT_OUTPUT_DIR.expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename
        else:
            requested_path = output_arg.expanduser().resolve()
            try:
                requested_stat = requested_path.stat()
            except FileNotFoundError:
                requested_stat = None

            # Keep existing-directory-first semantics, including directories
            # whose names end in .m4b.
            is_directory = (
                requested_stat is not None
                and stat.S_ISDIR(requested_stat.st_mode)
            )
            if is_directory or not requested_path.suffix:
                requested_path.mkdir(parents=True, exist_ok=True)
                output_path = requested_path / filename
            else:
                if requested_path.suffix.lower() != ".m4b":
                    raise InputError(
                        "Output must be a .m4b file or a directory, "
                        f"got: {requested_path.name}"
                    )
                output_path = requested_path

        output_path.parent.mkdir(parents=True, exist_ok=True)
        parent_stat = output_path.parent.stat()
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise InputError(
                f"Output parent is not a directory: {output_path.parent}"
            )

        _validate_output_file(output_path)
        _probe_directory_writable(output_path.parent)
        _check_existing_output_writable(output_path)
        return output_path
    except InputError:
        raise
    except OSError as e:
        error_path = locals().get(
            "output_path",
            output_arg if output_arg is not None else DEFAULT_OUTPUT_DIR,
        )
        raise InputError(
            f"Cannot prepare output path {error_path}: {_safe_os_error(e)}"
        ) from e


def _validate_output_file(output_path: Path) -> None:
    """Reject an existing destination that is not a regular file."""
    try:
        output_stat = output_path.stat()
    except FileNotFoundError:
        return

    if not stat.S_ISREG(output_stat.st_mode):
        raise InputError(
            f"Output destination is not a regular file: {output_path}"
        )


def _probe_directory_writable(directory: Path) -> None:
    """Verify directory write access with a temporary sibling probe."""
    descriptor = -1
    probe_path: Path | None = None
    try:
        descriptor, probe_name = tempfile.mkstemp(
            prefix=".epub2audiobook-write-test-",
            suffix=".tmp",
            dir=directory,
        )
        probe_path = Path(probe_name)
        probe_descriptor = descriptor
        descriptor = -1
        os.close(probe_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if probe_path is not None:
            probe_path.unlink()


def _check_existing_output_writable(output_path: Path) -> None:
    """Open an existing output for writing without truncating its contents."""
    try:
        output_stat = output_path.stat()
    except FileNotFoundError:
        return

    if not stat.S_ISREG(output_stat.st_mode):
        raise InputError(
            f"Output destination is not a regular file: {output_path}"
        )

    descriptor = os.open(
        output_path,
        os.O_WRONLY | getattr(os, "O_NONBLOCK", 0),
    )
    os.close(descriptor)


def _safe_os_error(error: OSError) -> str:
    """Return filesystem error details without arbitrary exception text."""
    return error.strerror or type(error).__name__
