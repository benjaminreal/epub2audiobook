"""Tests for two-pass loudness normalization in the assembler."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from epub2audiobook import assembler
from epub2audiobook.config import LOUDNESS_TARGET_LUFS
from epub2audiobook.parser import BookMetadata

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

SAMPLE_STDERR = """[Parsed_loudnorm_0 @ 0x1] \n{
	"input_i" : "-22.33",
	"input_tp" : "-0.35",
	"input_lra" : "2.60",
	"input_thresh" : "-32.68",
	"output_i" : "-18.27",
	"output_tp" : "-5.50",
	"output_lra" : "2.50",
	"output_thresh" : "-28.63",
	"normalization_type" : "dynamic",
	"target_offset" : "0.27"
}
[out#0/null @ 0x2] video:0KiB audio:1KiB"""


class LoudnormParsingTests(unittest.TestCase):
    def test_parses_measurement(self):
        measured = assembler.parse_loudnorm_json(SAMPLE_STDERR)
        self.assertEqual(measured["input_i"], -22.33)
        self.assertEqual(measured["target_offset"], 0.27)

    def test_missing_measurement_raises(self):
        with self.assertRaises(assembler.AssemblyError):
            assembler.parse_loudnorm_json("no json here")

    def test_filter_applies_fixed_gain_then_limiter(self):
        f = assembler.normalization_filter(assembler.parse_loudnorm_json(SAMPLE_STDERR))
        self.assertTrue(f.startswith("volume=4.33dB,"))
        self.assertIn("alimiter=", f)
        self.assertNotIn("loudnorm", f)
        self.assertLess(f.index("volume="), f.index("alimiter="))

    def test_silence_is_not_normalized(self):
        silent = SAMPLE_STDERR.replace('"-22.33"', '"-inf"')
        with self.assertLogs("epub2audiobook.assembler", level="WARNING"):
            self.assertIsNone(
                assembler.normalization_filter(assembler.parse_loudnorm_json(silent))
            )


class EncoderChoiceTests(unittest.TestCase):
    def tearDown(self):
        assembler.aac_encoder.cache_clear()

    def _choose(self, listing: str) -> str:
        assembler.aac_encoder.cache_clear()
        done = subprocess.CompletedProcess([], 0, stdout=listing, stderr="")
        with mock.patch.object(assembler.subprocess, "run", return_value=done):
            return assembler.aac_encoder()

    def test_prefers_apple_encoder(self):
        listing = (
            " A....D aac                  AAC (Advanced Audio Coding)\n"
            " A....D aac_at               aac (AudioToolbox) (codec aac)\n"
        )
        self.assertEqual(self._choose(listing), "aac_at")

    def test_falls_back_with_warning(self):
        listing = " A....D aac                  AAC (Advanced Audio Coding)\n"
        with self.assertLogs("epub2audiobook.assembler", level="WARNING"):
            self.assertEqual(self._choose(listing), "aac")

    def test_encoder_args(self):
        self.assertEqual(
            assembler._encoder_args("aac_at"),
            ["-c:a", "aac_at", "-aac_at_mode", "cbr", "-b:a", "64k"],
        )
        self.assertEqual(assembler._encoder_args("aac"), ["-c:a", "aac", "-b:a", "64k"])


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _ebur128(path: Path) -> tuple[float, float]:
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    summary = err[err.rfind("Summary:") :]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"True peak:\s+Peak:\s+(-?[\d.]+) dBFS", summary).group(1))
    return lufs, peak


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class AssembleLoudnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.metadata = BookMetadata("Test Book", "Test Author", "en", None, None)

    def tearDown(self):
        self._tmp.cleanup()

    def _chapter(self, name: str, source: str) -> Path:
        wav = self.tmp / f"{name}.wav"
        _ffmpeg("-f", "lavfi", "-i", source, "-ac", "1", "-c:a", "pcm_s16le", str(wav))
        return wav

    def test_quiet_peaky_book_meets_release_loudness(self):
        # a quiet tone with sparse one-sample full-scale clicks: low loudness,
        # high peaks, and clicks too short to carry the loudness themselves
        tone = "sine=f={}:sample_rate=24000:duration=8,volume=-10dB"
        clicks = "aevalsrc='if(eq(mod(n,24000),0),0.99,0)':s=24000:d=8"
        chapters = [
            self._chapter(
                f"ch{i}",
                f"{tone.format(220 + 110 * i)}[n];{clicks}[c];"
                "[n][c]amix=inputs=2:normalize=0",
            )
            for i in range(2)
        ]
        before, before_peak = _ebur128(chapters[0])
        self.assertLess(before, -25)
        self.assertGreater(before_peak, -3)
        out = self.tmp / "book.m4b"
        assembler.assemble_audiobook(
            chapters, self.metadata, ["One", "Two"], out, "Narrator"
        )
        lufs, peak = _ebur128(out)
        self.assertAlmostEqual(lufs, LOUDNESS_TARGET_LUFS, delta=1.0)
        self.assertLessEqual(peak, -3.0)
        info = json.loads(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(out)],
                capture_output=True, text=True, check=True,
            ).stdout
        )  # fmt: skip
        self.assertEqual([c["tags"]["title"] for c in info["chapters"]], ["One", "Two"])

    def test_silent_book_still_assembles(self):
        chapters = [self._chapter("s", "anullsrc=r=24000:cl=mono:d=2")]
        out = self.tmp / "silent.m4b"
        with self.assertLogs("epub2audiobook.assembler", level="WARNING"):
            assembler.assemble_audiobook(
                chapters, self.metadata, ["Only"], out, "Narrator"
            )
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
