[drafted by gpt-6-luna]

# Independent review: Kokoro backend plan

**Verdict:** Acceptable with focused amendments.

**Reviewed plan SHA-256:** `ff669fc6a7ace9f42d0459f6a90bada3d5198dade4d39dc38b20c9bd5c231000` (unchanged during review).

**Reviewer model and effort:** GPT-6-Luna, xhigh.

This review covered the approved v1 release definition, the plan and verification note, the named backend/CLI/dependency files, and relevant synthetic/privacy/CLI tests. I made no code or plan edits, ran no tests, and made no model calls, installs, downloads, task writes, or publication actions. The unrelated `product_definition_prompt.md` owner edit remains untouched.

The plan has the right boundary: it treats this as one v0.2 task, preserves the ONNX default and MLX opt-in, avoids a new backend framework or benchmark program, and does not turn v1 release criteria into gates for this task. The remaining required changes are narrow: check full voice names and exercise backend factory routing with synthetic tests.

## Recommendations

### R1 — High · Must-have: validate the complete voice name

`KokoroParallelEngine` and `MLXKokoroEngine` currently check only whether the first character of a voice name has a language mapping (`epub2audiobook/onnx_parallel.py:101-103`; `epub2audiobook/mlx_backend.py:35-38`). They then pass the unchecked name to the model (`onnx_parallel.py:66-68`; `mlx_backend.py:65-71`). The prior Kokoro engine checked membership in the model's complete voice list and returned an `Unknown Kokoro voice` error (`tts_engine.py:194-214`).

With the new path, a name such as `a_not_a_voice` can pass construction and fail only during chapter synthesis. ONNX sanitizes that worker error to a generic exception type (`onnx_parallel.py:73-76, 184-189`); the CLI then marks the chapter failed and continues (`cli.py:172-181`). A multi-chapter book can therefore finish with audio missing chapters after an invalid `--voice` value.

**Smallest plan amendment:** make exact voice membership an acceptance criterion for both backends, with an actionable, content-safe invalid-voice error before a chapter can be skipped. Add synthetic tests for valid and invalid full names. The plan need not prescribe how each backend obtains its voice catalogue.

### R2 — Medium · Must-have: test backend routing, not only flag parsing

The CLI defines `--backend {onnx,mlx}` with ONNX as the default (`cli.py:264-276`) and the factory routes Kokoro to the matching engine while retaining Piper for its default ONNX selection (`tts_engine.py:290-323`). The new backend test checks that parsing `--backend mlx` stores the value and directly exercises the MLX adapter (`tests/test_kokoro_backends.py:160-222`), but it does not assert that the factory selects ONNX by default or MLX when requested.

**Smallest plan amendment:** add a no-model factory test with patched engine constructors for default ONNX, explicit MLX, and legacy Piper with the default backend. Also assert that Piper plus MLX returns the existing clear selection error. This closes the CLI compatibility and selection acceptance row without model work.

### R3 — Low · Optional: keep the multiprocess claim precise; no six-worker model rerun is needed

The supplied ONNX smoke is a short sentence, so it does not demonstrate that all six workers each synthesized work or establish throughput. The verification note already says it does not exercise all six real workers and does not claim speed (`docs/kokoro_backends_verification.md:31-41`). The synthetic scheduling test checks a six-worker pool request, at most twelve outstanding items, output ordering and pauses (`tests/test_kokoro_backends.py:69-89`); a separate test checks the worker's CPU provider and ONNX thread options (`:115-157`). The model smoke provides basic real-model output evidence, but its receipt does not record worker assignment.

**Disposition:** keep the current explicit limitation; do not require a full-book run, benchmark, or new model call for this task. If the owner wants separate proof that the real `spawn` path uses multiple processes, the smallest no-model addition is one synthetic test using the real spawn executor, a module-level cheap worker stub, and enough chunks to observe more than one child process. It should not require that every one of six workers receive a task; scheduler timing makes that a stronger and less stable condition than the task needs.

### R4 — Low · Optional: state the MLX logging suppression scope accurately

`_suppress_mlx_content_logs()` uses `logging.disable(logging.CRITICAL)` and restores the previous threshold in `finally` (`mlx_backend.py:17-25`). That setting suppresses Python logging process-wide while each generation step is advanced; it is broader than only MLX-Audio records. Current generation is synchronous, and tests verify both secret-log suppression and restoration after normal completion and failure (`tests/test_kokoro_backends.py:160-211, 224-256`).

**Disposition:** no broader privacy/security audit or new gate is needed here. Clarify in the review/verification wording that Python log records from all loggers are suppressed temporarily; consider narrowing the suppression only if concurrent application logging becomes relevant. The plan already limits its privacy claim to supported Python diagnostics and excludes native/direct stdout/stderr behavior (`docs/kokoro_backends_plan.md:87-90`; `docs/kokoro_backends_verification.md:48-52`).

### R5 — Low · Defer: name the backend usage document, leave release packaging out of scope

The repository has no root `README.md`, although `pyproject.toml` declares `readme = "README.md"` (`pyproject.toml:5-10`). The plan asks for concise install/use guidance but leaves its destination unspecified (`docs/kokoro_backends_plan.md:69-71`). For this backend task, a dedicated document such as `docs/kokoro_backends.md` is enough to explain the ONNX default, MLX optional-extra install/selection, Apple Silicon requirement, base-versus-optional dependencies, first-use model download, and MLX pacing. Do not add clean-machine packaging or a README repair as a backend acceptance gate; track the missing packaging artifact with the later release-packaging work.

## Scope checks

- **CLI compatibility:** `--engine` remains available; `--backend` defaults to ONNX, and `create_tts_engine` preserves Piper when used with the default backend. MLX with Piper fails clearly. The plan correctly keeps Piper removal separate.
- **Optional dependency isolation:** MLX dependencies are in the `mlx` extra with macOS/arm64 markers (`pyproject.toml:22-27`); MLX imports are deferred until its backend is selected (`tts_engine.py:309-317`, `mlx_backend.py:39-46`). The base dependency list does not include MLX packages.
- **Failure and cleanup:** ONNX worker failures are converted to content-free exception types and partial WAVs are removed (`onnx_parallel.py:73-76, 184-189`). The CLI registers backend close before its temporary directory exits (`cli.py:149-163`); its existing synthetic interruption test checks close-before-directory-removal (`tests/test_cli_merge_fixes.py:136-188`). The plan correctly disclaims forced-kill cleanup.
- **WAV contract:** ONNX writes mono, 16-bit, 24 kHz WAV headers (`onnx_parallel.py:169-183`); the MLX adapter checks 24 kHz, one-dimensional audio and emits 16-bit PCM, while the shared writer supplies mono WAV headers (`mlx_backend.py:73-86`; `tts_engine.py:118-128`). The provided real smoke receipts report 24 kHz mono 16-bit output. Current synthetic tests could assert channel count and sample width as a small polish, but the available evidence is adequate for this task.
- **Overbuilding and missing gates:** do not add full-book timing/listening, offline operation, clean-machine installation, forced-kill guarantees, or release checks to this task. The plan explicitly leaves those as later validation and does not rely on historical benchmark speeds (`docs/kokoro_backends_plan.md:17-19, 92-95`).

## Minimal plan amendment and completion sequence

1. Add exact voice-name validation and synthetic coverage for both backends.
2. Add synthetic factory routing coverage for default ONNX, explicit MLX and legacy Piper compatibility.
3. Name a concise backend usage document under `docs/`; keep the missing root README/packaging issue for the release-packaging task.
4. Make only accepted code changes, then run the existing focused synthetic suite, lock and whitespace checks, and final scoped diff/protected-owner-edit review as the plan proposes. Record the limitations above; no new inference or all-six-worker benchmark is required.
5. Present the changed-file scope and evidence for the normal commit/PR decision. Do not treat that presentation as publication or task completion.
