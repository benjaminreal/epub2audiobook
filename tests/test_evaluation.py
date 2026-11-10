"""Tests for the narration evaluation tools, on synthetic audio and transcripts."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from epub2audiobook.evaluation import hard_checks, review_queue
from epub2audiobook.evaluation.spoken_form import number_to_words, tokenize, words

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _segments(*texts: str, seconds: float = 2.0) -> list[tuple[float, float, str]]:
    return [(i * seconds, (i + 1) * seconds, t) for i, t in enumerate(texts)]


class SpokenFormTests(unittest.TestCase):
    def test_numbers_and_money_match_spelled_words(self):
        self.assertEqual(
            words("Shawn had paid $500 for him."),
            words("Shawn had paid five hundred dollars for him."),
        )

    def test_number_to_words(self):
        self.assertEqual(
            number_to_words(1_234), "one thousand two hundred thirty four".split()
        )
        self.assertEqual(number_to_words(40), ["forty"])

    def test_years_read_as_years(self):
        self.assertEqual(
            words("In 1995 and 1907"),
            "in nineteen ninety five and nineteen oh seven".split(),
        )

    def test_hyphens_apostrophes_and_case(self):
        self.assertEqual(
            words("“We’ll pay a-eleven-tion,” he said."),
            ["we'll", "pay", "a", "eleven", "tion", "he", "said"],
        )

    def test_names_are_capitalized_words_inside_a_sentence(self):
        names = [
            t.original
            for t in tokenize("Then I saw Tyler. Audrey called.")
            if t.is_name
        ]
        self.assertEqual(names, ["Tyler"])


class ReviewQueueTests(unittest.TestCase):
    TEXT = "I wanted to believe her but didn't. Diego had been killing Luke's chickens."

    def test_exact_read_has_no_flags(self):
        queue = review_queue.build_queue(
            self.TEXT,
            _segments(
                "I wanted to believe her, but didn't.",
                "Diego had been killing Luke's chickens.",
            ),
        )
        self.assertEqual(queue["flags"], [])
        self.assertEqual(
            queue["summary"]["matched_words"], queue["summary"]["expected_words"]
        )

    def test_skipped_words_are_high_severity_with_time(self):
        queue = review_queue.build_queue(
            self.TEXT,
            _segments(
                "I wanted to believe her.", "Diego had been killing Luke's chickens."
            ),
        )
        (flag,) = queue["flags"]
        self.assertEqual(flag["kind"], "skipped")
        self.assertEqual(flag["severity"], "low")  # two words: but didn't
        self.assertEqual(flag["expected"], "but didn't")
        self.assertAlmostEqual(flag["time"], 2.0)

    def test_repeat_and_offset(self):
        queue = review_queue.build_queue(
            self.TEXT,
            _segments(
                "I wanted to believe her but didn't.",
                "Diego had been killing Luke's chickens. Luke's chickens.",
            ),
            offset=100.0,
        )
        (flag,) = queue["flags"]
        self.assertEqual(flag["kind"], "repeated")
        self.assertEqual(flag["severity"], "high")
        self.assertGreater(flag["time"], 100.0)

    def test_name_substitution_marked_likely_asr_when_reference_agrees(self):
        text = "Shawn had paid for him."
        kokoro = _segments("Sean had paid for him.")
        human = _segments("Sean had paid for him.")
        queue = review_queue.build_queue(
            "Then " + text,
            _segments("Then " + kokoro[0][2]),
            _segments("Then " + human[0][2]),
        )
        (flag,) = queue["flags"]
        self.assertEqual(flag["kind"], "name")
        self.assertTrue(flag["also_in_reference"])
        self.assertEqual(queue["summary"]["likely_asr"], 1)

    def test_flag_not_in_reference_stays_unmarked(self):
        queue = review_queue.build_queue(
            self.TEXT,
            _segments(
                "I wanted to believe her but didn't.",
                "Diego had been killing chickens.",
            ),
            _segments(self.TEXT),
        )
        (flag,) = queue["flags"]
        self.assertFalse(flag["also_in_reference"])

    def test_cli_reads_whisper_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "text.txt").write_text(self.TEXT, encoding="utf-8")
            (tmp / "asr.json").write_text(
                json.dumps(
                    {
                        "transcription": [
                            {
                                "offsets": {"from": 0, "to": 3000},
                                "text": " I wanted to believe her but didn't.",
                            },
                            {
                                "offsets": {"from": 3000, "to": 6000},
                                "text": " Diego had been killing Luke's chickens.",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = tmp / "queue.json"
            code = review_queue.main(
                [
                    "--text",
                    str(tmp / "text.txt"),
                    "--asr",
                    str(tmp / "asr.json"),
                    "--json",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text())["summary"]["flags"], 0)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class HardCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _tone(
        self,
        name: str,
        seconds: float,
        volume_db: float,
        chapters: list[float] | None = None,
        gap: float = 0.0,
    ) -> Path:
        """Pink noise at a fixed gain, with an optional silent gap and chapters."""
        wav = self.tmp / f"{name}.wav"
        source = (
            f"anoisesrc=color=pink:sample_rate=44100:duration={seconds}:seed=1,"
            f"volume={volume_db}dB"
        )
        if gap:
            _ffmpeg(
                "-f",
                "lavfi",
                "-i",
                source,
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=44100:cl=mono:d={gap}",
                "-f",
                "lavfi",
                "-i",
                source,
                "-filter_complex",
                "[0][1][2]concat=n=3:v=0:a=1",
                "-ac",
                "1",
                str(wav),
            )
        else:
            _ffmpeg("-f", "lavfi", "-i", source, "-ac", "1", str(wav))
        out = self.tmp / f"{name}.m4a"
        if chapters:
            meta = self.tmp / f"{name}.txt"
            lines = [";FFMETADATA1"]
            bounds = [0.0, *chapters]
            for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
                lines += [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={int(a * 1000)}",
                    f"END={int(b * 1000)}",
                    f"title=Chapter {i + 1}",
                ]
            meta.write_text("\n".join(lines) + "\n")
            _ffmpeg(
                "-i",
                str(wav),
                "-i",
                str(meta),
                "-map_metadata",
                "1",
                "-map_chapters",
                "1",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                str(out),
            )
        else:
            _ffmpeg("-i", str(wav), "-c:a", "aac", "-b:a", "64k", str(out))
        return out

    def _calibrated(self, name: str, **kwargs) -> Path:
        """A file whose loudness lands near -18 LUFS."""
        first = self._tone(name + "_probe", 6, 0.0)
        lufs, _ = hard_checks.loudness(first)
        return self._tone(name, volume_db=-18.0 - lufs, **kwargs)

    def _status(self, report, name):
        return next(c.status for c in report.checks if c.name == name)

    def test_compliant_file_passes(self):
        path = self._calibrated("ok", seconds=6, chapters=[3.0, 6.0])
        report = hard_checks.run_checks(path, per_chapter=True, expect_chapters=2)
        self.assertFalse(report.failed, hard_checks.format_report(report))
        self.assertEqual(self._status(report, "chapter_loudness"), "pass")

    def test_loud_file_fails_loudness(self):
        path = self._tone("loud", 6, 0.0, chapters=[6.0])
        report = hard_checks.run_checks(path)
        self.assertEqual(self._status(report, "integrated_loudness"), "fail")
        self.assertTrue(report.failed)

    def test_missing_chapters_and_wrong_count_fail(self):
        path = self._calibrated("nochap", seconds=6)
        self.assertEqual(
            self._status(hard_checks.run_checks(path), "chapter_count"), "fail"
        )
        path = self._calibrated("twochap", seconds=6, chapters=[3.0, 6.0])
        report = hard_checks.run_checks(path, expect_chapters=3)
        self.assertEqual(self._status(report, "chapter_count"), "fail")

    def test_long_silence_warns(self):
        path = self._calibrated("gap", seconds=3, gap=4.0, chapters=[10.0])
        report = hard_checks.run_checks(path)
        self.assertEqual(self._status(report, "long_silences"), "warn")
        (gap,) = next(c.value for c in report.checks if c.name == "long_silences")
        self.assertAlmostEqual(gap[0], 3.0, delta=0.2)

    def test_silence_at_chapter_break_is_not_flagged(self):
        info = {
            "format": {"duration": "20"},
            "chapters": [
                {"start_time": "0", "end_time": "10"},
                {"start_time": "10", "end_time": "20"},
            ],
        }
        m = hard_checks.Measurements(-18.0, -4.0, 0, [(7.0, 10.5), (13.0, 17.0)])
        (check,) = hard_checks.check_silences(m, info)
        self.assertEqual(check.value, [(13.0, 17.0)])
        self.assertIn("1 at chapter breaks", check.detail)

    def test_chapter_tiling_detects_gap(self):
        info = {
            "format": {"duration": "10"},
            "chapters": [
                {"start_time": "0", "end_time": "4"},
                {"start_time": "5", "end_time": "10"},
            ],
        }
        checks = {c.name: c for c in hard_checks.check_chapters(info)}
        self.assertEqual(checks["chapter_tiling"].status, "fail")
        self.assertEqual(checks["chapter_tiling"].value, [2])

    def test_unreadable_file_raises(self):
        bad = self.tmp / "bad.m4b"
        bad.write_bytes(b"not audio")
        with self.assertRaises(hard_checks.CheckError):
            hard_checks.run_checks(bad)


if __name__ == "__main__":
    unittest.main()
