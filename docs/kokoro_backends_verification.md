# Kokoro backend work: verification and limits

**Status:** Implementation and PR review completed on 2026-10-09, with voice
validation, routing, real-spawn synthetic coverage and cleanup-failure handling.
Owner-approved full-book technical checks passed for both backends on
2026-10-10; the results and limits are recorded below.
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
| Ruff at PR preparation | The executable was unavailable then; the follow-up check below supersedes that lint gap. |

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

## Follow-up Ruff check after PR merge

Ruff 0.15.16, already declared in the development extra and locked in `uv.lock`,
was installed into the project environment for the owner's requested check.
Dependency declarations and the lockfile were unchanged.

`uv run --no-sync --offline ruff check epub2audiobook tests --output-format json`
initially reported 25 findings. Running the same Ruff version and configuration
against pre-backend commit `8e25e87351b21dc47c4cb2a7fcf2c4d618d69fae` reported
15. Comparison by relative path, rule and message identified 10 introduced
findings: one import-order issue and nine long lines. Those were corrected
locally without changing the protected owner prompt. The repository-wide
command now reports exactly the same 15 baseline findings and exits with code
1; it is not a repository-wide lint pass.

The narrower check passed with code 0:

```sh
uv run --no-sync --offline ruff check \
  epub2audiobook/mlx_backend.py epub2audiobook/onnx_parallel.py \
  tests/test_kokoro_backend_routing.py tests/test_kokoro_backends.py \
  tests/test_kokoro_spawn.py tests/test_kokoro_voice_validation.py
```

After these edits, `uv run --no-sync --offline python -m unittest discover
-s tests -q` passed all 39 tests, and `git diff --check` passed. This is a
lasting source cleanup. No book or model
inference was involved in the Ruff check.

## Full-book technical verification — 2026-10-10

The owner approved two complete conversions of the exact supplied Eric Ries
EPUB, *Incorruptible*, and confirmed Dropbox sync was paused. The staged input,
outputs, temporary files and logs stayed outside Dropbox in
`/private/tmp/kokoro-verification-67p8f2tb`. The input contained 100,763 processed
whitespace words and 54 parser entries. Its original and staged SHA-256 stayed
`b280e19d06abc6a4d31694aab6863db3b909742fdca33c71fa676aa7634cfc7e`.

Each backend ran once through the production Python 3.12.13 CLI:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run --no-sync --offline python -m epub2audiobook \
  /private/tmp/kokoro-verification-67p8f2tb/incorruptible.epub \
  --backend <onnx-or-mlx> --voice af_heart --output <backend-output.m4b>
```

Cached Kokoro ONNX v1.0 assets were used with `kokoro-onnx==0.6.1` and
`onnxruntime==1.26.0`. MLX used `mlx-community/Kokoro-82M-bf16`, cached revision
`a71e4d38b236d968966a2002c4c895dbd12b1c3c`, through `mlx-audio==0.5.8`.
No model downloads or paid model API calls were needed; model/API cost was $0.
Offline flags were enabled; network traffic was not independently monitored.

| Result | ONNX | MLX |
|---|---:|---:|
| CLI exit code | 0 | 0 |
| CLI elapsed time, including M4B assembly | 1:27:46.77 | 0:27:49.94 |
| Audio duration | 12:10:35.472 | 12:23:10.625 |
| Output size | 344.4 MiB | 337.6 MiB |
| Peak sampled summed process resident memory | 10.82 GiB | 2.90 GiB |
| Ordered markers matching parser manifest | 54 | 54 |
| Full FFmpeg audio decode exit code | 0 | 0 |
| Text entries with nonzero decoded samples | 37 / 37 | 37 / 37 |

`ffprobe` confirmed AAC mono audio at 44,100 Hz, the book title/author metadata,
and contiguous increasing markers ending at the audio duration. The full audio
was decoded using `ffmpeg -v error -i <output.m4b> -map 0:a:0 -f null -`.
Both sets of eleven assertions in the local verification helper passed.
Temporary chapter WAVs and conversion directories were removed. Each test
temporary root retained only an empty UV runtime lock. All six observed ONNX
worker processes ended. Source files and the protected owner prompt were
unchanged during the runs.

Memory figures are process-tree samples taken once per second, summed across
processes. Shared pages may be counted more than once and brief peaks may be
missed; these are approximate measurements, not total physical/GPU memory.
The timing comparison describes this one book and environment.

Seventeen image-only entries contain no extracted words and become silence;
no optical character recognition was performed. Marker labels match the
current parser, including its generic and nested labels; authored table-of-
contents fidelity was not established. Nonzero samples and complete decoding
do not establish word-perfect narration or listened audio quality. Three
ten-second listening clips per backend were extracted locally for owner
review and have not been listened to by the agent.

Detailed receipts, hashes and links to the outputs and clips are in
`/private/tmp/kokoro-verification-67p8f2tb/verification-report.md`. These scratch
artifacts are temporary and have not been copied into the repository. The
earlier Quick Start Guide selection was superseded before inference.

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
benchmarks. The full-book checks above are a separate timing observation.
The MLX package and
model were installed for the approved smoke check; MLX-Audio also fetched the
English spaCy wheel automatically on that first run. The wheel is now an
explicit optional dependency so a later project sync retains it.

At the earlier PR amendment stage, no new model inference, model downloads,
dependency installation, real book
processing, speed benchmark, listening check, full EPUB-to-M4B conversion,
offline-network test, or clean-machine install was performed for these
amendments. The later Ruff and full-book checks above supersede the corresponding
gaps. Listening quality, independent offline-network verification and
clean-machine installation remain unverified.
Forced-kill cleanup, the missing root README/release packaging, Piper removal,
and model-directory migration remain outside this backend task.

Implementation workers were GPT-6-Luna at xhigh (production validation and
voice tests) and GPT-6.1-Sol at high (routing/spawn tests, synthetic fixture
integration and documentation). The parent checked the final combined tree.
