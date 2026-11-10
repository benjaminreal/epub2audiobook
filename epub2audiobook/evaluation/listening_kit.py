"""Blind listening kit: build a rating page from matched clips, then score the ratings.

Each passage has one clip per condition (for example a human narration, the
engine and a deliberately weak engine). ``build`` trims and loudness-matches
the clips, gives them random file names and labels, inserts hidden repeat
panels, and writes a local HTML rating page. The key that maps labels to
conditions is written to a separate file the listener should not open until
the ratings are downloaded. ``score`` joins the ratings with the key.

The kit stays on this computer: the page plays local files and saves the
ratings by downloading a JSON file. Do not upload the clips.

Usage:
    python -m epub2audiobook.evaluation.listening_kit build MANIFEST.json
        --out KIT_DIR --key KEY.json
    python -m epub2audiobook.evaluation.listening_kit score RATINGS.json
        --key KEY.json [--json RESULTS.json]

MANIFEST.json:
    {"title": "...", "reference": "human", "engine": "kokoro",
     "codec_roundtrip": ["kokoro", "piper"],
     "passages": [{"id": "P01", "clips": {"human": "...wav", "kokoro": "...wav",
                                          "piper": "...wav"}}]}
"""

from __future__ import annotations

import argparse
import json
import math
import random
import secrets
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from epub2audiobook.evaluation.hard_checks import CheckError, loudness

TARGET_LUFS = -20.0
MATCH_TOLERANCE_LU = 0.5
MAX_PEAK_DBTP = -1.0
PAD_S = 0.3
REPEAT_AFTER = (4, 8)  # a hidden repeat panel follows panels 4 and 8
# Provisional targets (owner decision, 2026-11-08): within 10 points of the
# blind professional reference, and "keep listening" on 9 of 10 passages.
TARGET_GAP = 10.0
TARGET_CONTINUE = 0.9
DIMENSIONS = (
    "pronunciation",
    "pacing and pauses",
    "prosody and emphasis",
    "dialogue clarity",
    "emotional fit",
    "consistency",
    "listening effort",
)
PAGE = Path(__file__).with_name("listening_kit.html")


def _ffmpeg(*args: str) -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True
        )
    except FileNotFoundError as exc:
        raise CheckError(
            "ffmpeg not found; install it with: brew install ffmpeg"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise CheckError(
            f"ffmpeg failed: {exc.stderr.decode(errors='replace')}"
        ) from exc


def prepare_clip(source: Path, stem: str, roundtrip: bool, work: Path) -> dict:
    """Trim edge silence, pad, and optionally pass through AAC 64k.

    The AAC round trip gives engine clips the same codec as the engine's M4B
    output. Returns the intermediate file with its loudness and true peak.
    """
    trimmed = work / f"{stem}_trim.wav"
    edge = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05"
    pad = f"adelay={int(PAD_S * 1000)},apad=pad_dur={PAD_S}"
    _ffmpeg(
        "-i", str(source), "-ac", "1", "-ar", "44100",
        "-af", f"{edge},areverse,{edge},areverse,{pad}",
        str(trimmed),
    )  # fmt: skip
    if roundtrip:
        aac = work / f"{stem}.m4a"
        _ffmpeg("-i", str(trimmed), "-c:a", "aac", "-b:a", "64k", str(aac))
        decoded = work / f"{stem}_aac.wav"
        _ffmpeg("-i", str(aac), "-ac", "1", "-ar", "44100", str(decoded))
        trimmed = decoded
    lufs, peak = loudness(trimmed)
    return {"path": trimmed, "lufs": lufs, "true_peak": peak}


def common_target(clips: list[dict]) -> float:
    """The loudest level, at most TARGET_LUFS, that keeps every peak in limit.

    Every clip is matched to the same level, so the clip with the highest
    peak-to-loudness ratio sets it.
    """
    headroom = min(MAX_PEAK_DBTP - (c["true_peak"] - c["lufs"]) for c in clips)
    return min(TARGET_LUFS, math.floor(headroom * 2) / 2)


def match_loudness(prepared: dict, out: Path, target: float) -> dict:
    """Apply one gain change; no limiter, EQ or time stretch."""
    trimmed, gain = prepared["path"], target - prepared["lufs"]
    _ffmpeg(
        "-i", str(trimmed), "-af", f"volume={gain:.2f}dB",
        "-c:a", "pcm_s16le", str(out),
    )  # fmt: skip
    after, peak = loudness(out)
    if abs(after - target) > MATCH_TOLERANCE_LU:
        raise CheckError(f"{out.name}: loudness {after} LUFS after matching")
    if peak > MAX_PEAK_DBTP + 0.2:  # re-measurement after rounding the gain
        raise CheckError(f"{out.name}: true peak {peak} dBTP after matching")
    return {"lufs": after, "true_peak": peak, "gain_db": round(gain, 2)}


def plan_panels(passage_ids: list[str], rng: random.Random) -> list[dict]:
    """Shuffle passages and insert hidden repeats of earlier panels."""
    order = passage_ids[:]
    rng.shuffle(order)
    panels: list[dict] = []
    for i, pid in enumerate(order, 1):
        panels.append({"passage": pid, "repeat_of": None})
        if i in REPEAT_AFTER and i < len(order):
            shown = [p for p in panels if p["repeat_of"] is None]
            source = rng.choice(shown)
            panels.append({"passage": source["passage"], "repeat_of": source})
    for n, p in enumerate(panels, 1):
        p["panel"] = n
    for p in panels:
        if p["repeat_of"] is not None:
            p["repeat_of"] = p["repeat_of"]["panel"]
    return panels


def build(manifest_path: Path, out_dir: Path, key_path: Path) -> dict:
    """Build the kit folder and the separate key file."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if out_dir.exists() or key_path.exists():
        raise CheckError("the kit folder or key file already exists; choose new paths")
    rng = random.Random(secrets.randbits(64))
    passages = {p["id"]: p for p in manifest["passages"]}
    conditions = sorted({c for p in passages.values() for c in p["clips"]})
    roundtrip = set(manifest.get("codec_roundtrip", []))
    (out_dir / "audio").mkdir(parents=True)
    kit_id = secrets.token_hex(4)
    files: dict[tuple[str, str], dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        prepared = {
            (pid, condition): prepare_clip(
                Path(src), f"{pid}_{condition}", condition in roundtrip, Path(tmp)
            )
            for pid, p in passages.items()
            for condition, src in p["clips"].items()
        }
        target = common_target(list(prepared.values()))
        for (pid, condition), prep in prepared.items():
            name = secrets.token_hex(6) + ".wav"
            stats = match_loudness(prep, out_dir / "audio" / name, target)
            files[(pid, condition)] = {"file": f"audio/{name}", **stats}
    panels = plan_panels(list(passages), rng)
    page_panels, key_panels = [], []
    for p in panels:
        labels = "ABCDEFGH"[: len(passages[p["passage"]]["clips"])]
        conds = list(passages[p["passage"]]["clips"])
        rng.shuffle(conds)
        clips = []
        for label, condition in zip(labels, conds):
            src = files[(p["passage"], condition)]
            if p["repeat_of"] is not None:  # a repeat gets its own file name
                name = secrets.token_hex(6) + ".wav"
                (out_dir / "audio" / name).write_bytes(
                    (out_dir / src["file"]).read_bytes()
                )
                src = {**src, "file": f"audio/{name}"}
            clips.append({"label": label, "file": src["file"]})
            files[(f"panel{p['panel']}", label)] = {"condition": condition, **src}
        page_panels.append({"panel": p["panel"], "clips": clips})
        key_panels.append(
            {
                "panel": p["panel"],
                "passage": p["passage"],
                "repeat_of": p["repeat_of"],
                "clips": {c["label"]: cond for c, cond in zip(clips, conds)},
            }
        )
    meta = {
        "kit_id": kit_id,
        "title": manifest.get("title", "Blind listening round"),
        "dimensions": list(DIMENSIONS),
    }
    page = PAGE.read_text(encoding="utf-8").replace(
        "__KIT__", json.dumps({**meta, "panels": page_panels})
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    key = {
        **meta,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference": manifest.get("reference"),
        "engine": manifest.get("engine"),
        "conditions": conditions,
        "codec_roundtrip": sorted(roundtrip),
        "target_lufs": target,
        "panels": key_panels,
        "clips": {
            f"{pid}/{cond}": v
            for (pid, cond), v in files.items()
            if not pid.startswith("panel")
        },
    }
    key_path.write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
    return key


def score(ratings: dict, key: dict) -> dict:
    """Join ratings with the key and summarize gaps, continuation and drift."""
    if ratings.get("kit_id") != key["kit_id"]:
        raise ValueError("these ratings belong to a different kit")
    reference, engine = key.get("reference"), key.get("engine")
    by_panel = {p["panel"]: p for p in key["panels"]}
    rated = {r["panel"]: r for r in ratings["panels"]}
    per_passage: dict[str, dict] = {}
    drift = []
    dims: dict[str, dict[str, list[int]]] = {}
    for n, kp in by_panel.items():
        r = rated.get(n)
        if r is None:
            continue
        by_condition = {
            cond: r["clips"].get(label, {}) for label, cond in kp["clips"].items()
        }
        if kp["repeat_of"] is not None:
            first = rated.get(kp["repeat_of"])
            if first:
                first_by = {
                    cond: first["clips"].get(label, {})
                    for label, cond in by_panel[kp["repeat_of"]]["clips"].items()
                }
                for cond, c in by_condition.items():
                    a, b = first_by.get(cond, {}).get("score"), c.get("score")
                    if a is not None and b is not None:
                        drift.append({"condition": cond, "first": a, "repeat": b})
            continue
        entry = {cond: c.get("score") for cond, c in by_condition.items()}
        entry["continue"] = {
            cond: c.get("continue") for cond, c in by_condition.items()
        }
        entry["reasons"] = {
            cond: c.get("reason") for cond, c in by_condition.items() if c.get("reason")
        }
        if entry.get(reference) is not None and entry.get(engine) is not None:
            entry["gap"] = entry[engine] - entry[reference]
        per_passage[kp["passage"]] = entry
        for cond, c in by_condition.items():
            for d, v in (c.get("dims") or {}).items():
                dims.setdefault(cond, {}).setdefault(d, []).append(v)

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.fmean(xs), 1) if xs else None

    gaps = [e["gap"] for e in per_passage.values() if "gap" in e]
    cont = [e["continue"].get(engine) for e in per_passage.values()]
    cont = [c for c in cont if c is not None]
    summary = {
        "passages_rated": len(per_passage),
        "mean_score": {
            c: mean(e.get(c) for e in per_passage.values()) for c in key["conditions"]
        },
        "mean_gap": mean(gaps),
        "worst_gap": min(gaps) if gaps else None,
        "engine_continue": f"{sum(cont)}/{len(cont)}" if cont else None,
        "repeat_drift": [abs(d["repeat"] - d["first"]) for d in drift],
        "provisional_targets": {
            "gap_within_points": TARGET_GAP,
            "gap_met": (mean(gaps) is not None and mean(gaps) >= -TARGET_GAP),
            "continue_rate": TARGET_CONTINUE,
            "continue_met": bool(cont) and sum(cont) / len(cont) >= TARGET_CONTINUE,
        },
        "note": (
            "One listener, one round: this describes this listener's ratings of "
            "these passages, not a general quality level."
        ),
    }
    return {
        "summary": summary,
        "passages": per_passage,
        "repeats": drift,
        "dimensions": {
            c: {d: mean(v) for d, v in ds.items()} for c, ds in dims.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("manifest", type=Path)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--key", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("ratings", type=Path)
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            key = build(args.manifest, args.out, args.key)
            print(f"kit {key['kit_id']}: {len(key['panels'])} panels")
            print(f"open {args.out / 'index.html'}; do not open {args.key}")
            return 0
        result = score(
            json.loads(args.ratings.read_text(encoding="utf-8")),
            json.loads(args.key.read_text(encoding="utf-8")),
        )
    except (CheckError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["summary"], indent=1))
    if args.json:
        args.json.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
