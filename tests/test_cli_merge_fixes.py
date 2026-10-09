"""Focused CLI tests for output preflight and conversion temp cleanup."""

import argparse
import os
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from epub2audiobook import assembler as assembler_module
from epub2audiobook import cli
from epub2audiobook.assembler import AssemblyError
from epub2audiobook.parser import BookMetadata, Chapter
from epub2audiobook.tts_engine import TTSError


class CliOutputPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="epub-cli-tests-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def test_default_and_existing_m4b_directory_resolve_and_probe(self) -> None:
        default_dir = self.root / "default-output"
        with patch.object(cli, "DEFAULT_OUTPUT_DIR", default_dir):
            self.assertEqual(
                cli._resolve_output_path(None, "A Book"),
                (default_dir / "A_Book.m4b").resolve(),
            )
        self.assertTrue(default_dir.is_dir())
        self.assertEqual(list(default_dir.iterdir()), [])

        directory_named_m4b = self.root / "collection.m4b"
        directory_named_m4b.mkdir()
        self.assertEqual(
            cli._resolve_output_path(directory_named_m4b, "A Book"),
            (directory_named_m4b / "A_Book.m4b").resolve(),
        )
        self.assertEqual(list(directory_named_m4b.iterdir()), [])

    def test_rejects_nonregular_destination_and_file_parent(self) -> None:
        pipe_path = self.root / "audio.m4b"
        os.mkfifo(pipe_path)
        with self.assertRaisesRegex(cli.InputError, "not a regular file"):
            cli._resolve_output_path(pipe_path, "A Book")

        parent_file = self.root / "parent-file"
        parent_file.write_bytes(b"parent")
        with self.assertRaises(cli.InputError):
            cli._resolve_output_path(parent_file / "audio.m4b", "A Book")

    def test_invalid_extension_is_rejected(self) -> None:
        with self.assertRaisesRegex(cli.InputError, "must be a .m4b"):
            cli._resolve_output_path(self.root / "audio.mp3", "A Book")

    def test_parent_probe_permission_failure_is_input_error(self) -> None:
        output = self.root / "out" / "audio.m4b"
        output.parent.mkdir()
        with patch.object(
            cli.tempfile,
            "mkstemp",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            with self.assertRaisesRegex(cli.InputError, "Permission denied"):
                cli._resolve_output_path(output, "A Book")

    def test_existing_output_preflight_checks_writeability_without_truncating(
        self,
    ) -> None:
        output = self.root / "audio.m4b"
        original_bytes = b"existing output must stay intact"
        output.write_bytes(original_bytes)
        real_open = os.open

        def deny_output_open(
            path: os.PathLike[str] | str,
            flags: int,
            *args: object,
            **kwargs: object,
        ) -> int:
            if Path(path).resolve() == output.resolve():
                raise PermissionError(13, "Permission denied", str(output))
            return real_open(path, flags, *args, **kwargs)

        with patch.object(cli.os, "open", side_effect=deny_output_open):
            with self.assertRaisesRegex(cli.InputError, "Permission denied"):
                cli._resolve_output_path(output, "A Book")
        self.assertEqual(output.read_bytes(), original_bytes)

    def test_invalid_default_target_fails_before_engine_initialization(self) -> None:
        epub_path = self._make_epub()
        default_target = self.root / "default-output-is-a-file"
        default_target.write_bytes(b"not a directory")
        args = self._args(epub_path, None)
        engine_factory = unittest.mock.Mock()

        with (
            patch.object(cli, "DEFAULT_OUTPUT_DIR", default_target),
            self._patched_main(args, engine_factory, unittest.mock.Mock()),
        ):
            with self.assertLogs("epub2audiobook", level="ERROR") as logs:
                self.assertEqual(cli.main(), 1)

        engine_factory.assert_not_called()
        diagnostic = "\n".join(logs.output)
        self.assertIn(str(default_target), diagnostic)
        self.assertNotIn("output path None", diagnostic)

    def test_explicit_output_creates_parent_and_preserves_existing_bytes(self) -> None:
        output = self.root / "new-parent" / "audio.m4b"
        resolved_output = output.resolve()

        self.assertEqual(cli._resolve_output_path(output, "A Book"), resolved_output)
        self.assertTrue(output.parent.is_dir())
        self.assertFalse(output.exists())

        original_bytes = b"keep this existing audiobook"
        output.write_bytes(original_bytes)
        self.assertEqual(cli._resolve_output_path(output, "A Book"), resolved_output)
        self.assertEqual(output.read_bytes(), original_bytes)

    def test_invalid_target_fails_before_engine_initialization(self) -> None:
        epub_path = self._make_epub()
        parent_file = self.root / "not-a-directory"
        parent_file.write_bytes(b"parent")
        args = self._args(epub_path, parent_file / "audio.m4b")
        engine_factory = unittest.mock.Mock()

        with self._patched_main(args, engine_factory, unittest.mock.Mock()):
            self.assertEqual(cli.main(), 1)

        engine_factory.assert_not_called()

    def test_all_cleanup_paths_remove_only_the_conversion_directory(self) -> None:
        scenarios = ("success", "all_failed", "assembly_failed", "interrupted")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                output = self.root / f"{scenario}.m4b"
                sentinel = self.root / f"{scenario}-sentinel.txt"
                sentinel.write_bytes(b"leave this alone")
                generated_dirs: list[Path] = []

                class FakeEngine:
                    def generate(inner_self, _text: str, path: Path) -> Path:
                        generated_dirs.append(path.parent)
                        if scenario == "all_failed":
                            raise TTSError("synthetic TTS failure")
                        if scenario == "interrupted":
                            raise KeyboardInterrupt
                        path.write_bytes(b"synthetic wav")
                        return path

                    def get_voice_name(inner_self) -> str:
                        return "synthetic voice"

                def assemble(*_args: object) -> Path:
                    if scenario == "assembly_failed":
                        raise AssemblyError("synthetic assembly failure")
                    output.write_bytes(b"synthetic m4b")
                    return output

                args = self._args(self._make_epub(), output)
                assembler = unittest.mock.Mock(side_effect=assemble)
                run = self._patched_main(args, lambda *_: FakeEngine(), assembler)
                if scenario == "interrupted":
                    with run:
                        with self.assertRaises(KeyboardInterrupt):
                            cli.main()
                else:
                    with run:
                        expected_code = 0 if scenario == "success" else 3
                        self.assertEqual(cli.main(), expected_code)

                self.assertTrue(generated_dirs)
                self.assertFalse(generated_dirs[0].exists())
                self.assertEqual(sentinel.read_bytes(), b"leave this alone")
                self.assertEqual(
                    assembler.called,
                    scenario in {"success", "assembly_failed"},
                )

    def test_late_assembly_oserror_returns_processing_error(self) -> None:
        output = self.root / "late-failure.m4b"
        args = self._args(self._make_epub(), output)
        assembly = unittest.mock.Mock(
            side_effect=PermissionError(13, "Permission denied")
        )

        with self._patched_main(args, lambda *_: _SuccessfulEngine(), assembly):
            with self.assertLogs("epub2audiobook", level="ERROR") as logs:
                self.assertEqual(cli.main(), 3)
        self.assertIn("Output filesystem error", "\n".join(logs.output))
        self.assertNotIn("Traceback", "\n".join(logs.output))

    def test_late_output_stat_oserror_returns_processing_error(self) -> None:
        output = self.root / "stat-failure.m4b"
        resolved_output = output.resolve()
        args = self._args(self._make_epub(), output)
        assembled = False
        real_stat = Path.stat

        def assemble(*_args: object) -> Path:
            nonlocal assembled
            output.write_bytes(b"synthetic m4b")
            assembled = True
            return output

        def fail_after_assembly(path: Path, *args: object, **kwargs: object):
            lexical_path = Path(os.path.abspath(os.fspath(path)))
            if assembled and lexical_path == resolved_output:
                raise PermissionError(13, "Permission denied", str(output))
            return real_stat(path, *args, **kwargs)

        with self._patched_main(args, lambda *_: _SuccessfulEngine(), assemble):
            with patch.object(Path, "stat", fail_after_assembly):
                with self.assertLogs("epub2audiobook", level="ERROR") as logs:
                    self.assertEqual(cli.main(), 3)
        self.assertIn("Output filesystem error", "\n".join(logs.output))
        self.assertNotIn("Traceback", "\n".join(logs.output))

    def _make_epub(self) -> Path:
        epub_path = self.root / "synthetic.epub"
        with zipfile.ZipFile(epub_path, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
        return epub_path

    @staticmethod
    def _args(epub_path: Path, output: Path | None) -> argparse.Namespace:
        return argparse.Namespace(
            epub_path=epub_path,
            output=output,
            engine="kokoro",
            voice=None,
            verbose=False,
            version=False,
        )

    def _patched_main(
        self,
        args: argparse.Namespace,
        engine_factory: object,
        assembler: object,
    ) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.object(cli, "parse_args", return_value=args))
        stack.enter_context(patch.object(cli, "setup_logging"))
        stack.enter_context(patch.object(cli, "check_ffmpeg"))
        stack.enter_context(patch.object(cli, "estimate_audio_size", return_value=1))
        stack.enter_context(patch.object(cli, "check_disk_space"))
        stack.enter_context(
            patch.object(cli.platform, "machine", return_value="arm64")
        )

        from epub2audiobook import parser, preprocessor, tts_engine

        metadata = BookMetadata("Synthetic Book", "Synthetic Author", "en", None, None)
        chapters = [Chapter(0, "Chapter 1", "synthetic text", "chapter.xhtml")]
        stack.enter_context(
            patch.object(parser, "parse_epub", return_value=(metadata, chapters))
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
                side_effect=engine_factory,
            )
        )
        stack.enter_context(
            patch.object(
                assembler_module,
                "assemble_audiobook",
                side_effect=assembler,
            )
        )
        return stack


class _SuccessfulEngine:
    def generate(self, _text: str, path: Path) -> Path:
        path.write_bytes(b"synthetic wav")
        return path

    def get_voice_name(self) -> str:
        return "synthetic voice"


if __name__ == "__main__":
    unittest.main()
