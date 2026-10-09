"""Focused tests for content-safe TTS diagnostics and Kokoro logging."""

import io
import logging
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from epub2audiobook import assembler, cli, parser, preprocessor, tts_engine
from epub2audiobook.tts_engine import (
    KokoroTTSEngine,
    TTSEngine,
    TTSError,
    create_tts_engine,
)
from epub2audiobook.utils import DependencyError

BOOK_MARKER = "BOOK_CONTENT_MARKER_7f3a"
PHONEME_MARKER = "PHONEME_DEBUG_MARKER_91bc"


@contextmanager
def _configured_kokoro_logger():
    """Install a direct stderr handler and restore the logger's prior state."""
    backend_logger = logging.getLogger("kokoro_onnx")
    original_level = backend_logger.level
    original_disabled = backend_logger.disabled
    original_propagate = backend_logger.propagate
    original_handlers = backend_logger.handlers[:]
    handler = logging.StreamHandler(sys.stderr)
    backend_logger.handlers = [handler]
    backend_logger.setLevel(logging.DEBUG)
    backend_logger.disabled = False
    backend_logger.propagate = False
    try:
        yield backend_logger
    finally:
        backend_logger.handlers = original_handlers
        backend_logger.setLevel(original_level)
        backend_logger.disabled = original_disabled
        backend_logger.propagate = original_propagate
        handler.close()


@contextmanager
def _mock_kokoro_package(backend_class, model_dir: Path):
    """Provide a fake Kokoro class and block model downloads."""
    with (
        patch.dict(sys.modules, {"kokoro_onnx": SimpleNamespace(Kokoro=backend_class)}),
        patch.object(tts_engine, "KOKORO_MODEL_DIR", model_dir),
        patch.object(tts_engine, "_download_if_missing"),
    ):
        yield


class _RaisingEngine(TTSEngine):
    sample_rate = 24_000

    def __init__(self, error: Exception) -> None:
        self.error = error

    def _synthesize_paragraph(self, _text: str):
        raise self.error

    def get_voice_name(self) -> str:
        return "synthetic voice"


class TtsSanitizationTests(unittest.TestCase):
    def test_generation_sanitizes_runtime_and_existing_tts_errors(self) -> None:
        cases = (
            (RuntimeError(f"{BOOK_MARKER} {PHONEME_MARKER}"), "RuntimeError"),
            (TTSError(f"{BOOK_MARKER} {PHONEME_MARKER}"), "TTSError"),
        )
        with tempfile.TemporaryDirectory(prefix="tts-privacy-") as scratch:
            for error, safe_type in cases:
                with self.subTest(error_type=safe_type):
                    output_path = Path(scratch) / f"{safe_type}.wav"
                    with self.assertRaises(TTSError) as raised:
                        _RaisingEngine(error).generate(
                            f"Source text includes {BOOK_MARKER}.", output_path
                        )

                    self.assertEqual(
                        str(raised.exception),
                        f"TTS generation failed ({safe_type})",
                    )
                    self.assertNotIn(BOOK_MARKER, str(raised.exception))
                    self.assertNotIn(PHONEME_MARKER, str(raised.exception))
                    self.assertTrue(raised.exception.__suppress_context__)

    def test_kokoro_constructor_and_create_logs_are_suppressed_and_restored(
        self,
    ) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        class FakeKokoro:
            def __init__(self, *_paths: str) -> None:
                logging.getLogger("kokoro_onnx").debug(
                    "constructing %s", PHONEME_MARKER
                )

            def get_voices(self) -> list[str]:
                return ["af_heart"]

            def create(self, _text: str, **_kwargs: str):
                logging.getLogger("kokoro_onnx").debug(
                    "creating %s", PHONEME_MARKER
                )
                return np.array([0.0], dtype=np.float32), 24_000

        with tempfile.TemporaryDirectory(prefix="tts-privacy-") as scratch:
            model_dir = Path(scratch) / "models"
            output_path = Path(scratch) / "chapter.wav"
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with _configured_kokoro_logger() as backend_logger:
                    with _mock_kokoro_package(FakeKokoro, model_dir):
                        engine = KokoroTTSEngine()
                        engine.generate(f"Speak {BOOK_MARKER}.", output_path)
                        self.assertTrue(output_path.is_file())

                    self.assertEqual(backend_logger.level, logging.DEBUG)
                    self.assertFalse(backend_logger.disabled)
                    self.assertFalse(backend_logger.propagate)
                    self.assertEqual(len(backend_logger.handlers), 1)

        self.assertNotIn(PHONEME_MARKER, stdout.getvalue())
        self.assertNotIn(PHONEME_MARKER, stderr.getvalue())

    def test_kokoro_constructor_failure_is_safe_and_restores_logger(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        class FailingKokoro:
            def __init__(self, *_paths: str) -> None:
                logging.getLogger("kokoro_onnx").debug(PHONEME_MARKER)
                raise RuntimeError(f"{BOOK_MARKER} {PHONEME_MARKER}")

        with tempfile.TemporaryDirectory(prefix="tts-privacy-") as scratch:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with _configured_kokoro_logger() as backend_logger:
                    with _mock_kokoro_package(
                        FailingKokoro, Path(scratch) / "models"
                    ):
                        with self.assertRaises(TTSError) as raised:
                            KokoroTTSEngine()

                    self.assertEqual(backend_logger.level, logging.DEBUG)
                    self.assertFalse(backend_logger.disabled)
                    self.assertFalse(backend_logger.propagate)
                    self.assertEqual(len(backend_logger.handlers), 1)

        self.assertEqual(
            str(raised.exception), "Failed to initialize Kokoro (RuntimeError)"
        )
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn(BOOK_MARKER, str(raised.exception))
        self.assertNotIn(PHONEME_MARKER, str(raised.exception))
        self.assertNotIn(PHONEME_MARKER, stdout.getvalue())
        self.assertNotIn(PHONEME_MARKER, stderr.getvalue())

    def test_kokoro_create_failure_is_safe_and_restores_logger(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        class FailingCreateKokoro:
            def __init__(self, *_paths: str) -> None:
                pass

            def get_voices(self) -> list[str]:
                return ["af_heart"]

            def create(self, _text: str, **_kwargs: str):
                logging.getLogger("kokoro_onnx").debug(PHONEME_MARKER)
                raise TTSError(f"{BOOK_MARKER} {PHONEME_MARKER}")

        with tempfile.TemporaryDirectory(prefix="tts-privacy-") as scratch:
            output_path = Path(scratch) / "chapter.wav"
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with _configured_kokoro_logger() as backend_logger:
                    with _mock_kokoro_package(
                        FailingCreateKokoro, Path(scratch) / "models"
                    ):
                        engine = KokoroTTSEngine()
                        with self.assertRaises(TTSError) as raised:
                            engine.generate(f"Speak {BOOK_MARKER}.", output_path)

                    self.assertEqual(backend_logger.level, logging.DEBUG)
                    self.assertFalse(backend_logger.disabled)
                    self.assertFalse(backend_logger.propagate)
                    self.assertEqual(len(backend_logger.handlers), 1)

        self.assertEqual(str(raised.exception), "TTS generation failed (TTSError)")
        self.assertNotIn(BOOK_MARKER, str(raised.exception))
        self.assertNotIn(PHONEME_MARKER, str(raised.exception))
        self.assertNotIn(PHONEME_MARKER, stdout.getvalue())
        self.assertNotIn(PHONEME_MARKER, stderr.getvalue())

    def test_piper_initialization_error_is_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tts-privacy-") as scratch:
            download_module = SimpleNamespace(
                download_voice=lambda *_args: (_ for _ in ()).throw(
                    RuntimeError(f"{BOOK_MARKER} {PHONEME_MARKER}")
                )
            )
            piper_module = SimpleNamespace(PiperVoice=object())
            with (
                patch.dict(
                    sys.modules,
                    {
                        "piper": piper_module,
                        "piper.download_voices": download_module,
                    },
                ),
                patch.object(tts_engine, "PIPER_MODEL_DIR", Path(scratch) / "models"),
            ):
                with self.assertRaises(TTSError) as raised:
                    tts_engine.PiperTTSEngine()

        self.assertEqual(
            str(raised.exception), "Failed to initialize Piper voice (RuntimeError)"
        )
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn(BOOK_MARKER, str(raised.exception))
        self.assertNotIn(PHONEME_MARKER, str(raised.exception))

    def test_dependency_and_invalid_selection_messages_remain_actionable(self) -> None:
        with patch.dict(sys.modules, {"kokoro_onnx": None}):
            with self.assertRaisesRegex(DependencyError, "kokoro-onnx is required"):
                KokoroTTSEngine()

        with self.assertRaisesRegex(TTSError, "Unknown TTS engine 'other'"):
            create_tts_engine("other")

        with patch.dict(
            sys.modules, {"kokoro_onnx": SimpleNamespace(Kokoro=object)}
        ):
            with self.assertRaisesRegex(TTSError, "Unsupported Kokoro voice 'z_bad'"):
                KokoroTTSEngine("z_bad")


class CliTtsPrivacyTests(unittest.TestCase):
    def test_chapter_warning_and_summary_do_not_print_tts_error_text(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="cli-tts-privacy-") as scratch:
            root = Path(scratch)
            epub_path = root / "synthetic.epub"
            with zipfile.ZipFile(epub_path, "w") as archive:
                archive.writestr("mimetype", "application/epub+zip")
            output_path = root / "synthetic.m4b"

            args = SimpleNamespace(
                epub_path=epub_path,
                output=output_path,
                engine="kokoro",
                voice=None,
                verbose=False,
                version=False,
            )
            metadata = parser.BookMetadata(
                "Synthetic Book", "Synthetic Author", "en", None, None
            )
            chapters = [
                parser.Chapter(0, "Chapter One", f"{BOOK_MARKER} source", "one.xhtml"),
                parser.Chapter(1, "Chapter Two", "safe synthetic source", "two.xhtml"),
            ]

            class OneFailureEngine:
                def __init__(self) -> None:
                    self.calls = 0

                def generate(self, _text: str, path: Path) -> Path:
                    self.calls += 1
                    if self.calls == 1:
                        raise TTSError(f"{BOOK_MARKER} {PHONEME_MARKER}")
                    path.write_bytes(b"synthetic wav")
                    return path

                def get_voice_name(self) -> str:
                    return "synthetic voice"

            def assemble(*_args: object) -> Path:
                output_path.write_bytes(b"synthetic m4b")
                return output_path

            with ExitStack() as stack:
                stack.enter_context(patch.object(cli, "parse_args", return_value=args))
                stack.enter_context(patch.object(cli, "setup_logging"))
                stack.enter_context(patch.object(cli, "check_ffmpeg"))
                stack.enter_context(
                    patch.object(cli, "estimate_audio_size", return_value=1)
                )
                stack.enter_context(patch.object(cli, "check_disk_space"))
                stack.enter_context(
                    patch.object(cli.platform, "machine", return_value="arm64")
                )
                stack.enter_context(
                    patch.object(
                        parser,
                        "parse_epub",
                        return_value=(metadata, chapters),
                    )
                )
                stack.enter_context(
                    patch.object(
                        preprocessor,
                        "preprocess_text",
                        side_effect=lambda text: text,
                    )
                )
                stack.enter_context(
                    patch.object(
                        tts_engine,
                        "create_tts_engine",
                        return_value=OneFailureEngine(),
                    )
                )
                stack.enter_context(
                    patch.object(assembler, "assemble_audiobook", side_effect=assemble)
                )
                stack.enter_context(
                    patch.dict(
                        sys.modules,
                        {
                            "mutagen.mp4": SimpleNamespace(
                                MP4=lambda _path: SimpleNamespace(
                                    info=SimpleNamespace(length=1.0)
                                )
                            )
                        },
                    )
                )
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertLogs("epub2audiobook", level="WARNING") as logs:
                        result = cli.main()

            self.assertEqual(result, 0)
            self.assertTrue(output_path.is_file())

        visible_output = "\n".join((stdout.getvalue(), stderr.getvalue(), *logs.output))
        self.assertNotIn(BOOK_MARKER, visible_output)
        self.assertNotIn(PHONEME_MARKER, visible_output)
        self.assertIn("TTS synthesis failed for chapter 1 (TTSError)", visible_output)
        self.assertIn("Chapter One", visible_output)
        self.assertIn("TTS synthesis failed: TTSError", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
