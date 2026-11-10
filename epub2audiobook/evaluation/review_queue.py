"""Speech-to-text review queue: where the narration may not match the text.

Compares the text the engine was asked to read with a whisper.cpp transcript
of the audio, and lists likely skipped, added, repeated or misread words with
timestamps, for a person to listen to. It is not a score: speech-to-text makes
its own mistakes, so every flag needs listening.

When a transcript of a human narration of the same text is given, a flag
whose text span the human transcript also gets wrong is marked
``also_in_reference``: the speech-to-text model, not the narration, is the
likely cause.

Produce transcripts with whisper.cpp's JSON output, for example:
    whisper-cli -m ggml-large-v3-turbo.bin -l en -oj -of out clip.wav

Usage:
    python -m epub2audiobook.evaluation.review_queue --text passage.txt
        --asr kokoro.json [--reference-asr human.json] [--offset SECONDS]
        [--json queue.json]
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from epub2audiobook.evaluation.spoken_form import NUMBER_WORDS, Token, tokenize

HIGH_SEVERITY_WORDS = 3
CONTEXT_WORDS = 4


@dataclass
class HeardWord:
    """A transcribed word with an interpolated time in seconds."""

    word: str
    start: float
    end: float


@dataclass
class Flag:
    """One place for a person to listen to."""

    kind: str  # skipped, added, repeated, misread, name, number
    severity: str  # high or low
    time: float
    expected: str
    heard: str
    context: str
    expected_span: tuple[int, int]
    also_in_reference: bool = False


def load_whisper_json(path: Path) -> list[tuple[float, float, str]]:
    """Return (start, end, text) segments from whisper.cpp JSON output."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        (s["offsets"]["from"] / 1000, s["offsets"]["to"] / 1000, s["text"])
        for s in data.get("transcription", [])
    ]


def heard_words(
    segments: list[tuple[float, float, str]], offset: float = 0.0
) -> list[HeardWord]:
    """Split segments into words, interpolating each word's time within its segment.

    whisper.cpp segment times are reliable to a fraction of a second; word
    times inside a segment are estimates.
    """
    out = []
    for start, end, text in segments:
        tokens = tokenize(text)
        for k, t in enumerate(tokens):
            a = start + (end - start) * k / len(tokens)
            b = start + (end - start) * (k + 1) / len(tokens)
            out.append(HeardWord(t.word, round(a + offset, 2), round(b + offset, 2)))
    return out


def _opcodes(
    expected: list[str], heard: list[str]
) -> list[tuple[str, int, int, int, int]]:
    matcher = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
    return [op for op in matcher.get_opcodes() if op[0] != "equal"]


def _classify(
    tag: str, exp: list[Token], heard: list[str], prev_heard: list[str]
) -> str:
    if tag == "delete":
        return "skipped"
    if tag == "insert":
        n = len(heard)
        return "repeated" if n and prev_heard[-n:] == heard else "added"
    if any(t.is_name for t in exp):
        return "name"
    if any(t.word in NUMBER_WORDS for t in exp) or any(
        w in NUMBER_WORDS for w in heard
    ):
        return "number"
    return "misread"


def _spans_with_errors(expected: list[str], heard: list[str]) -> list[tuple[int, int]]:
    """Expected-text spans where a transcript differs (insertions are zero-width)."""
    return [(i1, i2) for _, i1, i2, _, _ in _opcodes(expected, heard)]


def _overlaps(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    a, b = span
    for c, d in others:
        if a == b or c == d:  # insertion: compare positions with one word of slack
            if c - 1 <= a <= d + 1 or a - 1 <= c <= b + 1:
                return True
        elif a < d and c < b:
            return True
    return False


def build_queue(
    text: str,
    segments: list[tuple[float, float, str]],
    reference_segments: list[tuple[float, float, str]] | None = None,
    offset: float = 0.0,
) -> dict:
    """Align expected text to a transcript and return flags plus a summary."""
    expected = tokenize(text)
    exp_words = [t.word for t in expected]
    heard = heard_words(segments, offset)
    heard_list = [h.word for h in heard]
    reference_spans = None
    if reference_segments is not None:
        reference_spans = _spans_with_errors(
            exp_words, [h.word for h in heard_words(reference_segments)]
        )

    flags = []
    for tag, i1, i2, j1, j2 in _opcodes(exp_words, heard_list):
        exp_tokens = expected[i1:i2]
        heard_part = heard_list[j1:j2]
        kind = _classify(tag, exp_tokens, heard_part, heard_list[:j1])
        size = max(i2 - i1, j2 - j1)
        if j1 < len(heard):
            time = heard[j1].start
        elif heard:
            time = heard[-1].end
        else:
            time = offset
        before = " ".join(exp_words[max(0, i1 - CONTEXT_WORDS) : i1])
        after = " ".join(exp_words[i2 : i2 + CONTEXT_WORDS])
        flag = Flag(
            kind=kind,
            severity="high"
            if size >= HIGH_SEVERITY_WORDS or kind == "repeated" and size >= 2
            else "low",
            time=time,
            expected=" ".join(t.original for t in exp_tokens),
            heard=" ".join(heard_part),
            context=f"{before} [{' '.join(exp_words[i1:i2])}] {after}".strip(),
            expected_span=(i1, i2),
        )
        if reference_spans is not None:
            flag.also_in_reference = _overlaps((i1, i2), reference_spans)
        flags.append(flag)

    matched = sum(
        b.size
        for b in difflib.SequenceMatcher(
            None, exp_words, heard_list, autojunk=False
        ).get_matching_blocks()
    )
    return {
        "summary": {
            "expected_words": len(exp_words),
            "heard_words": len(heard_list),
            "matched_words": matched,
            "flags": len(flags),
            "high": sum(f.severity == "high" for f in flags),
            "likely_asr": sum(f.also_in_reference for f in flags),
            "note": (
                "Flags are places to listen to, not errors. "
                "Word match is a diagnostic, not a score."
            ),
        },
        "flags": [asdict(f) for f in flags],
    }


def format_queue(queue: dict) -> str:
    s = queue["summary"]
    lines = [
        f"{s['flags']} flags ({s['high']} high, {s['likely_asr']} also in reference); "
        f"{s['matched_words']}/{s['expected_words']} expected words heard"
    ]
    for f in queue["flags"]:
        mark = " (also in reference)" if f["also_in_reference"] else ""
        lines.append(
            f"  {f['time']:8.2f}s {f['severity']:4} {f['kind']:8} "
            f"expected '{f['expected']}' heard '{f['heard']}'{mark}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--text", type=Path, required=True, help="text the narration should read"
    )
    parser.add_argument(
        "--asr", type=Path, required=True, help="whisper.cpp JSON of the narration"
    )
    parser.add_argument(
        "--reference-asr",
        type=Path,
        help="whisper.cpp JSON of a human narration of the same text",
    )
    parser.add_argument(
        "--offset",
        type=float,
        default=0.0,
        help="seconds to add to every time, e.g. a clip's start in the book",
    )
    parser.add_argument("--json", type=Path, help="write the queue as JSON")
    args = parser.parse_args(argv)
    reference = load_whisper_json(args.reference_asr) if args.reference_asr else None
    queue = build_queue(
        args.text.read_text(encoding="utf-8"),
        load_whisper_json(args.asr),
        reference,
        args.offset,
    )
    print(format_queue(queue))
    if args.json:
        args.json.write_text(
            json.dumps(queue, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
