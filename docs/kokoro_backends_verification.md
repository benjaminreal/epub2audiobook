# Kokoro backend work: verification and limits

**Status:** Implementation and PR review completed on 2026-10-09, with voice
validation, routing, real-spawn synthetic coverage and cleanup-failure handling.
The Tasks database was not changed by PR preparation. Earlier owner-authorized
model smoke checks are recorded separately below. See the
[PR review](kokoro_backends_pr_review.md) for the final check and review scope.

## Scope

- `--backend onnx` is the default Kokoro path. It uses six spawned CPU workers,
  two ONNX intra-operation threads per worker, at most twelve queued chunks,
  and writes results to each chapter WAV in source order. A worker retains one
  model for the conversion; the CLI closes the pool before deleting temporary
  chapter files. Full voice names are validated against the local NPZ voice
  pack, read with `allow_pickle=False`, before the neural model is downloaded
  or chapter synthesis starts.
- `--backend mlx` selects an Apple Silicon-only Kokoro MLX-Audio adapter. Its
  pinned optional extra includes `mlx-audio==0.5.8`, `misaki[en]==0.9.4`, and
  the English spaCy language wheel `en-core-web-sm==3.8.0`. The latter is a
  direct public GitHub release dependency because MLX-Audio otherwise installs
  it during the first synthesis run. After model loading, full voice names are
  validated against cached `voices/*.safetensors` assets using a local-only
  Hugging Face snapshot lookup.
- Piper and the legacy `--engine` choice remain for the separate v0.2 cleanup
  task. Model relocation is also outside this backend change.

Usage and first-use download details are in [Kokoro backend usage](kokoro_backends.md).

## Current model-free checks

| Check | Result |
|---|---|
| Final PR check: `uv run --no-sync --offline python -m unittest discover -s tests -v` | 39 tests passed in 0.363 s after fixing cleanup-failure handling. No neural model inference or downloads. |
| `uv run --no-sync --offline python -m unittest discover -s tests -v` | 38 tests passed in 0.387 s after the constructor amendments; no neural model inference or downloads. |
| `uv run --no-sync --offline python -m epub2audiobook --help` | Shows `--backend {onnx,mlx}`. |
| `uv lock --check` | Resolved 126 packages; optional MLX dependencies are locked for Apple Silicon. |
| Parent final suite and scoped review | The same unittest command passed all 38 tests in the final combined tree; `git diff --check` passed. Parent reviewed production/tests/docs and checked baseline hashes; the owner prompt, release definition, review report and dependency files were unchanged in this amendment round. |
| `.venv/bin/python` read-only catalogue-helper check | Both new `_available_voices` helpers read cached assets: 54 voices each, `af_heart` present, `a_not_a_voice` absent. MLX snapshot lookup used `local_files_only=True`; no neural model load, inference or download. |
| Ruff | Unavailable in the local environment from the earlier check: `Failed to spawn: ruff` / `No such file or directory`; not installed or rerun. |

The suite covers exact voice names, missing/corrupt catalogues, patched factory
routing and default/explicit voice forwarding, bounded queueing, source order,
24 kHz mono 16-bit WAVs, worker session options, content-safe errors, cleanup,
and MLX logging restoration. The new real-spawn test injects a process-local
synthetic model into a real two-process executor, then runs the production
worker and scheduling path. It transports the second chunk's completed result
before releasing the first, verifies source-ordered PCM and paragraph pauses,
and checks both the sanitized remote traceback and partial-WAV cleanup. Its
child synchronization waits are bounded at 10 s and its full subprocess at
30 s. It does not require six real workers or measure throughput.

A read-only check used the new catalogue helpers with project Python 3.12 to read
`~/.local/share/kokoro_onnx/voices-v1.0.bin` with NumPy's `allow_pickle=False`
and the cached MLX voice filenames. The MLX lookup specified
`repo_id=MLX_MODEL_ID`, `allow_patterns=[MLX_VOICE_PATTERN]` and
`local_files_only=True`. Both helpers returned 54 voices with `af_heart`
present and `a_not_a_voice` absent. This is metadata compatibility evidence,
not a revised-constructor inference check.

## Earlier approved checks

These receipts predate the voice-validation amendments. They do not verify
the revised constructors or demonstrate a complete conversion.

| Check | Result |
|---|---|
| `uv run --no-sync --offline python -m unittest discover -s tests -q` | Earlier synthetic suite: 25 tests passed. |
| `git diff --check` | Earlier implementation check passed; final diff review is separate. |
| ONNX v1.0 model smoke | Project Python 3.12 `.venv` generated a 2.35 s, 24 kHz mono, 16-bit WAV; nonzero audio peak 16901. |
| MLX Kokoro bf16 model smoke | Same `.venv` generated a 2.80 s, 24 kHz mono, 16-bit WAV; nonzero audio peak 11000. |
| `uv sync --extra mlx --dry-run` | No removal of `en-core-web-sm` after it was added to the lockfile. |

The model checks used only the synthetic sentence
"This is a backend smoke test." and wrote WAVs outside
Dropbox in `/private/tmp`. They establish basic real-model compatibility and
non-silent output for that sentence. They do not establish conversion speed,
audio quality, or offline behavior.

## Review limits

The ONNX session construction follows the installed `kokoro-onnx` 0.6.1
`Kokoro.from_session` interface. The MLX adapter follows the documented
[Kokoro Python API](https://github.com/Blaizzy/mlx-audio/blob/main/docs/models/tts/kokoro.md)
and the pinned 0.5.8 wheel's `generate` and `sample_rate` definitions. MLX's
Kokoro pipeline can send source text or phonemes through Python's root logger;
the adapter uses `logging.disable(logging.CRITICAL)` while starting and
advancing generation, temporarily suppressing all Python loggers and restoring
the previous threshold afterward. This assumes the current synchronous,
single-conversion CLI. This does not verify behavior of native
libraries, direct stdout/stderr writes, model downloads, or network traffic.

The 10.3× ONNX and 27.3× MLX speeds in `../work_report_2026-10-06.md` are prior
benchmarks. This implementation has not repeated them. The MLX package and
model were installed for the approved smoke check; MLX-Audio also fetched the
English spaCy wheel automatically on that first run. The wheel is now an
explicit optional dependency so a later project sync retains it.

No new model inference, model downloads, dependency installation, real book
processing, speed benchmark, listening check, full EPUB-to-M4B conversion,
offline-network test, or clean-machine install was performed for these
amendments. Synthetic and metadata checks do not establish those properties.
Forced-kill cleanup, the missing root README/release packaging, Piper removal,
and model-directory migration remain outside this backend task.

Implementation workers were GPT-6-Luna at xhigh (production validation and
voice tests) and GPT-6.1-Sol at high (routing/spawn tests, synthetic fixture
integration and documentation). The parent checked the final combined tree.
