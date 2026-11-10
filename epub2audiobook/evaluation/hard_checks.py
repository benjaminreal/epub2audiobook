"""Deterministic release checks for a rendered audiobook.

Checks the file, chapters, loudness, peaks, clipping and long silences with
FFmpeg. The checks find pipeline defects; they say nothing about narration
quality.

Usage:
    python -m epub2audiobook.evaluation.hard_checks BOOK.m4b [--per-chapter]
        [--expect-chapters N] [--json REPORT.json]

Exit status is 1 when any check fails, 0 otherwise. Warnings do not fail.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Release definition V1-05: -18 +/- 1 LUFS integrated, true peak <= -3 dBTP.
TARGET_LUFS = -18.0
LUFS_TOLERANCE = 1.0
MAX_TRUE_PEAK = -3.0
# A chapter whose loudness differs from the book by more than this is flagged.
CHAPTER_LU_SPREAD = 2.0
# The engine pauses 600 ms between paragraphs; a far longer gap is suspicious.
LONG_SILENCE_S = 3.0
SILENCE_FLOOR_DB = -50
# Samples in FFmpeg's 0 dB histogram bin; a few can come from AAC decoding.
CLIPPED_SAMPLES_WARN = 10
MIN_CHAPTER_S = 1.0
# A long silence this close to a chapter boundary is a chapter break.
CHAPTER_EDGE_S = 1.0
GAP_TOLERANCE_S = 0.05


class CheckError(Exception):
    """Raised when FFmpeg cannot read the file."""


@dataclass
class Check:
    """One check result."""

    name: str
    status: str  # "pass", "warn" or "fail"
    value: object = None
    limit: object = None
    detail: str = ""


@dataclass
class Report:
    """All checks for one file."""

    path: str
    duration_s: float
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(c.status == "fail" for c in self.checks)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["failed"] = self.failed
        return data


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise CheckError(
            f"{cmd[0]} not found; install it with: brew install ffmpeg"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise CheckError(f"{cmd[0]} failed with exit status {exc.returncode}") from exc


def probe(path: Path) -> dict:
    """Return FFprobe's format, streams and chapters for a file."""
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            "-of",
            "json",
            str(path),
        ]
    ).stdout
    return json.loads(out)


def _ffmpeg_filter(
    path: Path, audio_filter: str, start: float | None = None, end: float | None = None
) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-v", "info"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(path), "-vn", "-af", audio_filter, "-f", "null", "-"]
    return _run(cmd).stderr


def _parse_loudness(err: str) -> tuple[float, float]:
    summary = err[err.rfind("Summary:") :]
    integrated = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    peak = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    if not integrated or not peak:
        raise CheckError("could not read the ebur128 summary")
    return float(integrated.group(1)), float(peak.group(1))


def _parse_clipped(err: str) -> int:
    match = re.search(r"histogram_0db:\s+(\d+)", err)
    return int(match.group(1)) if match else 0


def _parse_silences(err: str) -> list[tuple[float, float]]:
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", err)]
    if len(ends) < len(starts):  # silence runs to the end of the file
        ends.append(float("nan"))
    return list(zip(starts, ends))


def loudness(
    path: Path, start: float | None = None, end: float | None = None
) -> tuple[float, float]:
    """Return (integrated LUFS, true peak dBTP) from FFmpeg's ebur128 summary."""
    return _parse_loudness(_ffmpeg_filter(path, "ebur128=peak=true", start, end))


@dataclass
class Measurements:
    """Everything one decoding pass measures."""

    lufs: float
    true_peak: float
    clipped_samples: int
    silences: list[tuple[float, float]]


def measure(path: Path) -> Measurements:
    """Measure loudness, peaks, clipping and long silences in one decoding pass."""
    chain = (
        "ebur128=peak=true,volumedetect,"
        f"silencedetect=noise={SILENCE_FLOOR_DB}dB:d={LONG_SILENCE_S}"
    )
    err = _ffmpeg_filter(path, chain)
    lufs, peak = _parse_loudness(err)
    return Measurements(lufs, peak, _parse_clipped(err), _parse_silences(err))


def check_file(info: dict) -> list[Check]:
    """Check that there is exactly one non-empty audio stream."""
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    checks = [
        Check(
            "audio_stream",
            "pass" if len(audio) == 1 else "fail",
            len(audio),
            1,
            "number of audio streams",
        )
    ]
    checks.append(
        Check(
            "duration",
            "pass" if duration > 0 else "fail",
            round(duration, 2),
            "> 0",
            "seconds",
        )
    )
    return checks


def check_chapters(info: dict, expect: int | None = None) -> list[Check]:
    """Check chapter count, lengths, and that chapters tile the whole file."""
    chapters = info.get("chapters", [])
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    checks = []
    if expect is not None:
        checks.append(
            Check(
                "chapter_count",
                "pass" if len(chapters) == expect else "fail",
                len(chapters),
                expect,
            )
        )
    elif not chapters:
        checks.append(Check("chapter_count", "fail", 0, ">= 1", "no chapter markers"))
        return checks
    else:
        checks.append(Check("chapter_count", "pass", len(chapters)))
    short = [
        i + 1
        for i, c in enumerate(chapters)
        if float(c["end_time"]) - float(c["start_time"]) < MIN_CHAPTER_S
    ]
    checks.append(
        Check(
            "chapter_lengths",
            "fail" if short else "pass",
            short or None,
            f">= {MIN_CHAPTER_S} s",
            "chapters shorter than the limit",
        )
    )
    gaps = []
    previous_end = 0.0
    for i, c in enumerate(chapters):
        if abs(float(c["start_time"]) - previous_end) > GAP_TOLERANCE_S:
            gaps.append(i + 1)
        previous_end = float(c["end_time"])
    if chapters and abs(previous_end - duration) > max(
        GAP_TOLERANCE_S, 0.01 * duration
    ):
        gaps.append("end")
    checks.append(
        Check(
            "chapter_tiling",
            "fail" if gaps else "pass",
            gaps or None,
            None,
            "chapters must start where the previous one ends and cover the file",
        )
    )
    return checks


def check_loudness(m: Measurements) -> list[Check]:
    """Check integrated loudness and true peak against the release definition."""
    lufs, peak = m.lufs, m.true_peak
    ok = abs(lufs - TARGET_LUFS) <= LUFS_TOLERANCE
    return [
        Check(
            "integrated_loudness",
            "pass" if ok else "fail",
            lufs,
            f"{TARGET_LUFS} +/- {LUFS_TOLERANCE} LUFS",
        ),
        Check(
            "true_peak",
            "pass" if peak <= MAX_TRUE_PEAK else "fail",
            peak,
            f"<= {MAX_TRUE_PEAK} dBTP",
        ),
    ]


def check_chapter_loudness(path: Path, info: dict, book_lufs: float) -> list[Check]:
    """Flag chapters much louder or quieter than the whole book."""
    outliers = []
    for i, c in enumerate(info.get("chapters", [])):
        lufs, _ = loudness(path, float(c["start_time"]), float(c["end_time"]))
        if lufs != float("-inf") and abs(lufs - book_lufs) > CHAPTER_LU_SPREAD:
            outliers.append({"chapter": i + 1, "lufs": lufs})
    return [
        Check(
            "chapter_loudness",
            "warn" if outliers else "pass",
            outliers or None,
            f"within {CHAPTER_LU_SPREAD} LU of the book ({book_lufs} LUFS)",
        )
    ]


def check_clipping(m: Measurements) -> list[Check]:
    """Warn when samples reach full scale."""
    count = m.clipped_samples
    status = "warn" if count >= CLIPPED_SAMPLES_WARN else "pass"
    return [
        Check("clipping", status, count, f"< {CLIPPED_SAMPLES_WARN} samples at 0 dB")
    ]


def check_silences(m: Measurements, info: dict) -> list[Check]:
    """Warn on long silences inside chapters.

    A silence that touches a chapter boundary (or the start or end of the
    file) within CHAPTER_EDGE_S is a chapter break and is only counted.
    """
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    edges = [0.0, duration]
    for c in info.get("chapters", []):
        edges += [float(c["start_time"]), float(c["end_time"])]
    inside, at_breaks = [], 0
    for a, b in m.silences:
        end = duration if b != b else b  # NaN: the silence runs to the end
        if any(a - CHAPTER_EDGE_S <= e <= end + CHAPTER_EDGE_S for e in edges):
            at_breaks += 1
        else:
            inside.append((round(a, 2), round(end, 2)))
    return [
        Check(
            "long_silences",
            "warn" if inside else "pass",
            inside or None,
            f"< {LONG_SILENCE_S} s below {SILENCE_FLOOR_DB} dB inside a chapter",
            f"start and end in seconds; {at_breaks} at chapter breaks not counted",
        )
    ]


def run_checks(
    path: Path, per_chapter: bool = False, expect_chapters: int | None = None
) -> Report:
    """Run every check on one file."""
    info = probe(path)
    report = Report(str(path), float(info.get("format", {}).get("duration", 0) or 0))
    report.checks += check_file(info)
    if report.failed:
        return report
    report.checks += check_chapters(info, expect_chapters)
    m = measure(path)
    report.checks += check_loudness(m)
    if per_chapter and info.get("chapters"):
        report.checks += check_chapter_loudness(path, info, m.lufs)
    report.checks += check_clipping(m)
    report.checks += check_silences(m, info)
    return report


def format_report(report: Report) -> str:
    lines = [f"{report.path} ({report.duration_s / 60:.1f} min)"]
    for c in report.checks:
        limit = f" (limit {c.limit})" if c.limit is not None else ""
        lines.append(f"  {c.status.upper():4} {c.name}: {c.value}{limit}")
    lines.append("FAILED" if report.failed else "passed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", type=Path)
    parser.add_argument(
        "--per-chapter",
        action="store_true",
        help="also measure each chapter's loudness (decodes once per chapter)",
    )
    parser.add_argument("--expect-chapters", type=int)
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    args = parser.parse_args(argv)
    try:
        report = run_checks(args.audio, args.per_chapter, args.expect_chapters)
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_report(report))
    if args.json:
        args.json.write_text(json.dumps(report.to_dict(), indent=1) + "\n")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
