[drafted by gpt-6.1-sol]

# Kokoro backends: scoped completion plan

**Date:** 2026-10-09. **Status:** Reviewed amendments implemented locally by
GPT-6-Luna at xhigh and GPT-6.1-Sol at high; parent final checks passed.
Implementation closeout was local and unpublished. The subsequent PR review
and its final verification are recorded in [the PR review](kokoro_backends_pr_review.md).
**Task:** `8c68c073-b866-40aa-804b-35f77f77c3b9`, Implement Kokoro backends:
ONNX parallel default + MLX GPU opt-in. Live Tasks database read today: P1,
open, last updated 2026-10-07 23:55:04.110607+00.

## Objective and authority

Complete the CLI's two Kokoro backends with the owner's agreed defaults:
ONNX on CPU with six processes and two threads per process; optional MLX on
Apple Silicon selected with `--backend mlx`. Preserve chapter order, paragraph
pauses, bounded memory, content-safe diagnostics, and temporary-file cleanup.

Authority is the task row and `docs/v1_release_definition.md`. This task is one
part of v0.2, not the entire v0.2 release. The prior 10.3x ONNX and 27.3x MLX
benchmarks motivate the architecture; they are not measurements of this code.

## Evidence at plan review, before implementation amendments

- Local base: merged `master` at `8e25e87351b21dc47c4cb2a7fcf2c4d618d69fae`.
  Backend changes exist in the working tree and are uncommitted.
- ONNX implementation has a persistent spawned process pool, two intra-op
  threads and one inter-op thread per worker, CPU provider, a twelve-unit
  queue bound, ordered WAV writes, and process-local model reuse.
- MLX adapter uses `mlx-community/Kokoro-82M-bf16`; its optional extra pins
  MLX-Audio 0.5.8, misaki[en] 0.9.4, and the public en-core-web-sm 3.8.0 wheel.
  Imports/model initialization are deferred until MLX is selected.
- The CLI adds `--backend {onnx,mlx}` and closes the ONNX pool before the
  conversion temporary directory is removed.
- 25 synthetic unittest tests passed. `uv lock --check` and `git diff --check`
  passed. Ruff is not installed; lint is an explicit verification gap.
- Approved local model checks processed only "This is a backend smoke test."
  with project Python 3.12: ONNX produced a non-silent 2.35-second WAV; MLX a
  non-silent 2.80-second WAV. Both were 24 kHz, mono, 16-bit.
- These short checks do not exercise all six real workers, establish speed,
  listening quality, a full EPUB-to-M4B conversion, or offline operation.
  Further model runs require a specific new approval; this review invokes none.

## Minimum scope

Keep changes limited to `onnx_parallel.py`, `mlx_backend.py`, the backend
factory in `tts_engine.py`, CLI selection/lifetime in `cli.py`, optional
dependencies and `uv.lock`, focused tests, and concise usage/review documents.
Use the current `generate(text, output_path)` and narrator-name contract. Keep
chapters sequential and parallelize only bounded chunks within a chapter.

Do not add worker-count controls, a plugin framework, backend auto-fallback,
new engines, generalized concurrency infrastructure, or a benchmark system.
Piper removal, model-directory migration, Spanish product support, loudness,
speed/pacing controls, parser repairs, resume/cancellation protocol, release
packaging, and model-download integrity are separate roadmap work.

The owner's unrelated `product_definition_prompt.md` edit is protected; its
SHA-256 is `3c2fc0bb44422604b7ba307326e24a1a5784aee588fd13f20a4fe582a9f7a6c1`.
The final change set must exclude that file. Do not change the approved release
definition, task data, session records, or project index during this review.

## Reviewed execution sequence

1. Completed: one independent plan review against the task, source, and tests.
   The parent assessed every recommendation; decisions are recorded below.
   No additional plan-review round is needed for these reversible amendments.
2. Validate complete voice names for each backend using its voice metadata or
   assets, before chapter synthesis begins. Return an actionable, content-safe
   invalid-voice error. Do not run synthesis to validate a name or load the ONNX
   neural model in the parent merely to obtain its voice list. Add synthetic
   valid/invalid-name tests, factory routing tests for default ONNX, explicit
   MLX, legacy Piper, and Piper plus MLX rejection. Add one small, bounded,
   model-free test with the real spawn executor and a module-level synthetic
   worker to verify process result/exception transport and ordered output.
   Avoid assertions that all six workers receive tasks or scheduler timing
   thresholds. Reuse existing tests for queue bounds and thread configuration.
   Keep one implementation owner; no additional architecture is needed.
3. Write `docs/kokoro_backends.md` with concise installation/use guidance for
   default ONNX and opt-in MLX, Apple Silicon requirements, optional dependency
   footprint, first-use downloads, and differing MLX pacing. Separate dependency
   footprint from model assets and label historical estimates. State that MLX
   generation temporarily suppresses Python logging process-wide, restores the
   previous threshold, and assumes the current synchronous, single-conversion
   CLI. Correct matching verification wording. Leave the pre-existing missing
   root README and release-packaging repairs to the later packaging task.
4. Run the focused synthetic suite, lock consistency, whitespace validation,
   protected-file hash check, and final diff review after accepted changes.
   Report Ruff as unverified unless its runner is available or installation is
   specifically authorized. Do not perform unrelated baseline lint cleanup.
5. Present the exact changed-file scope and validation for the normal approved
   commit/PR workflow. Publication, merge, and task completion are later actions;
   this plan review does not perform them.

## Acceptance for this backend task

| Criterion | Evidence needed |
|---|---|
| Selection | Synthetic factory tests prove default ONNX, explicit MLX and retained Piper behavior; incompatible Piper/MLX selection fails clearly. Missing optional dependencies and unsupported platform give actionable errors. Both Kokoro adapters reject an invalid complete voice name before chapter synthesis. |
| ONNX behavior | Six-worker/two-thread configuration, bounded outstanding work, ordered chunks and pauses, persistent model reuse within each process, stable 24 kHz mono PCM WAV contract. One bounded model-free real-spawn test verifies process transport and output order without requiring all workers to receive tasks or making speed claims. |
| MLX behavior | Pinned optional dependency set, model/voice/language passed correctly, streamed audio converted to the same WAV contract, no implicit fallback. |
| Failure and lifetime | Backend failures are content-safe; worker shutdown and temporary directory unwinding preserve existing CLI behavior on ordinary failure and interruption. Do not claim cleanup after a forced kill. |
| Privacy | Supported Python diagnostics omit source text/phonemes; logging suppression restores prior state. MLX's temporary process-wide logging threshold and synchronous-use boundary are stated accurately; narrower logging machinery is not required here. Review scope covers application behavior, not blanket native/dependency/network clearance. |
| Usability | Documented commands match the parser and optional dependency declaration. Base dependency set does not acquire MLX requirements. |
| Verification | Focused suite, both existing model smoke receipts, lock/whitespace checks, final scoped diff, protected owner edit, and disclosed remaining gaps. |

Do not treat this task's acceptance as v1 release acceptance. Full-book timing,
listening, clean-machine installation, and network-disabled conversion remain
unverified and are tracked as later release validation unless the review shows
a smaller check is necessary to establish this task's stated behavior.

## Parent disposition of the independent review

Reviewer: GPT-6-Luna, xhigh, one native Codex worker. The original reviewed
plan SHA-256 was
`ff669fc6a7ace9f42d0459f6a90bada3d5198dade4d39dc38b20c9bd5c231000`.
The preserved report is `docs/kokoro_backends_plan_review.md`, SHA-256
`cce15f5d931658e029a9016c61ec77dc61924c73991f1e69decfc442ed85e778`.
Parent independently read the report and checked the referenced source.

**Decision:** Acceptable with focused amendments. Keep the current architecture
and task boundary. This is plan approval for the local next steps, not evidence
that the pending implementation amendments or release acceptance have passed.

| Recommendation | Parent decision and rationale |
|---|---|
| R1: full voice-name validation | Accepted as required. Prefix-only checks regress the previous ONNX constructor's validation. Fail before synthesis with an actionable error, using backend assets rather than inference. |
| R2: synthetic factory routing coverage | Accepted as required. Parser-only coverage does not establish the new default or selected adapter; a few patched-constructor tests cover the public factory and retained Piper compatibility. |
| R3: precise multiprocess evidence; optional real-spawn test | Accepted with one small addition: the real-spawn, model-free test is part of completion because process transport is central to this change and fake executors do not exercise it. Do not rerun models, require all six workers to receive work, or introduce benchmarks. |
| R4: document broad MLX logging suppression | Accepted as a documentation amendment. Installed MLX pipeline source emits through Python's root logger; current suppression restores the prior process-wide threshold. No concurrency/logging framework or extra audit is justified for the synchronous CLI. |
| R5: name usage document and defer README/packaging repair | Accepted in two parts: create `docs/kokoro_backends.md` for this task; retain the existing root README/packaging defect as later release work. Do not expand this backend task into installation/distribution repair. |

### Factual qualifications to the reviewer report

- R1's hypothetical partial audiobook is not established for an invalid global
  `--voice` alone. The same voice is used for all chapters, and `cli.py:185-187`
  returns code 3 without producing output when all chapter synthesis fails.
  The confirmed defect is delayed, repeated, non-actionable failure after a
  valid-prefix but nonexistent voice passes initialization. That is sufficient
  reason to accept the validation amendment.
- R3 attributes the explicit all-six-workers limitation to the verification
  note. That exact limitation was stated in this plan; the verification note
  currently records only short-sentence model compatibility and excludes speed.
  Keep the limitation explicit in both documents during implementation.

No production code, tests, dependency files, approved release definition, task
row, or owner edit changed during the plan-review round. At that point the
focused validation/tests/docs remained pending. The subsequent authorized
implementation is recorded below. Existing model smoke receipts remain
point-in-time evidence; they predate these validation amendments.

## Implementation closeout, 2026-10-09

Benjamin authorized GPT-6-Luna at xhigh and GPT-6.1-Sol at high for this
implementation. Both ran as native Codex workers in the current session.
Production source had one owner; tests and documentation used disjoint file
ownership, with existing fixture integration after the production handoff.

- Luna implemented exact voice membership from ONNX NPZ metadata and cached
  MLX voice files, plus seven synthetic voice-validation tests. ONNX rejects
  unknown names before the neural-model download. MLX resolves its cached
  snapshot with `local_files_only=True` after its existing model initialization.
  Both reject unavailable catalogues with sanitized initialization errors.
- Sol added five factory-routing tests and one bounded real-spawn test, adapted
  old synthetic fixtures to the new validation, wrote `docs/kokoro_backends.md`,
  and updated `docs/kokoro_backends_verification.md`. MLX run instructions
  explicitly include `uv run --extra mlx`.
- Parent reviewed the production changes, tests and docs, and independently
  checked both new catalogue helpers against the real cached assets: 54 voices
  each, default `af_heart` present, invalid `a_not_a_voice` absent. This read
  metadata only; no neural model was loaded and no download/inference ran.

Final parent command
`uv run --no-sync --offline python -m unittest discover -s tests -v` passed
all 38 tests. `uv lock --check` passed with 126 packages and
`git diff --check` passed. Sol also verified the CLI help command. Parent
compared SHA-256 values against the pre-implementation snapshot: the owner
prompt, approved release definition, original review report, dependencies,
CLI/factory and other protected baseline files were unchanged in this round.

**Result:** The accepted amendments and scoped local implementation are
complete. The six-process/two-thread ONNX default, optional MLX selection,
ordered WAV contract, safe diagnostics and cleanup behavior are retained.
The real-spawn synthetic test verifies actual process transport and ordered
output without requiring all six workers to receive tasks or making timing
claims. These are lasting local code/test/doc changes, not a workaround.

**Limits:** Ruff remains unavailable and unverified. No new neural-model run,
full book, speed/listening/offline check or clean-machine install ran after
these amendments. The prior approved exact-sentence model receipts and current
catalogue checks are recorded separately in the verification note. They do not
provide blanket dependency, native-output, network, security or release
clearance. Publication and task-row completion require the normal separate
decision; neither was performed in this implementation.
