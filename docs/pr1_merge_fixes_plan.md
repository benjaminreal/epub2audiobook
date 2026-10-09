[drafted by gpt-6.1-sol]

# PR #1 minimal merge-fix plan

Status: Implemented and verified locally after one Luna 6 xhigh plan review. Starting commit: `0c08dea97a46a18ae37edb243baba073273681f7`.

## Objective and boundary

Close the demonstrated output-path failure and application-level book-content logging/temporary-audio privacy gaps before reconsidering PR #1. Preserve the existing sequential parser → preprocessor → TTS → assembler architecture, CLI flags, audio format, chapter-skip behavior, and overwrite warning. This is a local implementation/test run, not permission to commit, push, merge, rewrite history, change account/git settings, or invoke a speech model.

The owner's existing edit to `product_definition_prompt.md` must remain byte-identical. Use synthetic fixtures only. Scratch, generated WAV/M4B/wheels, and review command output belong outside Dropbox. No dependency additions, environment rebuilds, or private-book reads are needed.

## In-scope behavior fixes

### 1. Validate every output branch before engine initialization

In `cli.py`, resolve a directory/default/explicit `.m4b` destination through one validation path. Ensure its parent is a directory and can be created if absent. Preserve directory-first semantics: any existing directory argument, including one named `.m4b`, receives `{title}.m4b` inside it. Reject a directory/nonregular object at the resolved final file destination, an unusable existing output file, and a nonwritable parent. Preserve invalid-extension rejection. Use actual filesystem behavior rather than only `os.access`; a uniquely named temporary sibling probe can establish parent writeability without truncating the destination. Clean up the probe. Check an existing output's writeability without modifying bytes. Convert OSError into InputError with a useful safe filesystem message.

Preflight cannot remove races. Catch relevant late filesystem OSError failures at the assembly/output boundary, including output stat and process launch, and return processing exit code 3 rather than an uncaught traceback. Do not build an atomic-output/resume subsystem or change overwrite semantics. Keep helpers private and near the existing path resolver/assembler responsibility.

### 2. Keep book text and phonemes out of TTS diagnostics

In `tts_engine.py`, eliminate the explicit text excerpt and arbitrary backend exception text from public TTSError messages. Use safe stage/exception-type information and chapter indices in CLI reporting. Suppress exception chaining where it could expose text in an ordinary traceback. Apply the same policy to both initialization and synthesis, including already-raised TTSError propagation. Preserve actionable errors for missing dependencies and invalid engine/voice selection when they do not contain book text.

The installed Kokoro backend emits phonemes in debug logs and some exceptions. Cover its initialization and synthesis with narrowly scoped suppression of that backend logger; restore previous state in `finally`. Test the actual `kokoro_onnx` logger at DEBUG with its own output handler, covering construction and create calls. Do not disable root logging, mutate environment variables, modify third-party packages, or invent a logging framework. The current engine is sequential, so no parallel-backend design is needed. Define the claim narrowly: content-free TTS diagnostics for the supported application paths, not a guarantee about all native dependencies/network traffic. Titles/authors/paths in normal progress output remain and should be described as sensitive when sharing logs.

### 3. Clean the current conversion's intermediate directory on exit

In `cli.py`, give the existing conversion temporary directory a single structured lifetime so success, all-TTS failure, assembly failure, and Python interruption remove its files. Use TemporaryDirectory or a focused try/finally around that directory. Never delete unrelated directories, model caches, input EPUBs, or the final output. No new keep-debug-files flag or resume machinery is needed. A forced kill cannot guarantee cleanup; do not claim otherwise. Keep existing return codes/partial-chapter warning behavior.

Update only the contradictory sentences in `CLAUDE.md`: remove the required text snippet and replace preserve-on-failure with cleanup-on-exit. This implements the owner's privacy-fix request; do not add the previously proposed merge checklist or unrelated instruction changes.

## Explicitly deferred / owner decisions

- Model digest verification and download timeout, Kokoro backend rework, voice-validation ordering, parser defects/empty TOC, broad initialization refactor: existing v0.2 work, unchanged here.
- Missing README and console entry point: distribution work, unchanged here.
- Commit identity is already public. Report the remaining privacy decision; do not rewrite history or change git config. A future squash alone cannot erase published commits.
- Do not clean the whole lint backlog. Remove only the two new unnecessary f-string prefixes in touched CLI help lines, and avoid introducing new lint findings.

## Tests and acceptance

Add a small focused stdlib unittest suite under `tests/`; no new dependencies. Use mock engine/parser boundaries and synthetic data. Patch the default output directory to scratch; never touch real Downloads. Inject PermissionError for deterministic permission coverage, supplementing actual permissions only when useful. Test observable behavior rather than mirroring helpers:

1. Default, directory, new explicit `.m4b`, existing writable file and invalid extension.
2. Parent is a regular file, destination is an invalid type, nonwritable parent/target, mocked late filesystem failure. Demonstrate bad destinations fail before engine creation and existing output bytes stay unchanged during preflight.
3. Backend RuntimeError and TTSError containing distinct text/phoneme markers, initialization failure, and backend debug logging: markers absent from application stderr/stdout/error strings; logger state restored after success/failure.
4. Intermediate cleanup on success, all-TTS failure, assembly failure and KeyboardInterrupt; unrelated sentinel remains intact.
5. Optional scratch-only synthetic WAV-to-M4B smoke check with ffprobe; skip if tools are missing. Do not add parser/chunking/scene-break tests unrelated to these fixes.

Run `uv run --no-sync --offline python -m unittest discover -s tests -v` using the existing environment. Run Ruff head versus the starting commit to identify new findings by code/file/message, not count alone. Run `git diff --check`. Verify the protected owner file hash. Optional wheel rebuild only if packaging files change (not expected). No full book, listening test, packet capture, vulnerability database scan, or clean-machine install is claimed.

## Execution and ownership

1. Parent writes this plan.
2. One Luna 6 (`gpt-6-luna`) xhigh worker reviews scope, minimum work, correctness, privacy, tests, and architecture; writes `docs/pr1_merge_fixes_plan_review.md`. No implementation.
3. Parent assesses every recommendation, records accepted/rejected decisions in this plan, and finalizes it. One plan-review round.
4. Luna 6 xhigh implementation worker A owns output validation, assembly filesystem handling, CLI temporary lifetime, and relevant tests.
5. After A finishes, Luna 6 xhigh implementation worker B owns TTS privacy behavior, tests, minimal CLAUDE corrections, and the two CLI help f-string cleanups. Sequential ownership prevents CLI edit collisions.
6. Parent reviews the resulting diff. A Luna 6 xhigh test worker runs the final targeted suite and synthetic integration check, records `docs/pr1_merge_fixes_verification.md`, and reports remaining risks. It may correct test defects, but reports production issues to the parent rather than expanding scope.
7. Parent verifies final results and returns the plan, review report, changes, tests, and remaining merge/privacy decisions. PR stays open; no outbound GitHub writes.

## Parent disposition of Luna recommendations

- R1 accepted: preserve directory-first semantics and test default output validation.
- R2 accepted: late filesystem handling covers assembly and output-stat paths; catches stay specific.
- R3 accepted: suppress the real Kokoro logger only during backend work and test direct handler output/restoration.
- R4 accepted: sanitize ordinary and TTSError backend failures, and assert final CLI log/summary markers are absent.
- R5 accepted: one TemporaryDirectory lifetime; test interruption cleanup and unrelated sentinel preservation.
- R6 accepted: drop unrelated parser/TTS regression additions; mock default destination and permission failures; integration smoke stays optional and scratch-only.
- R7 not selected: retain two sequential implementation workers to honor the requested Luna worker workflow. A owns CLI paths/lifetime; B owns TTS privacy and minimal instruction corrections. B may make narrow CLI diagnostic adjustments after A finishes. The final test worker provides separate verification. No extra plan-review round.

Remaining owner decision: commit identity/history handling before publication or merge. Existing model/parser/distribution deferrals are not silently marked resolved.

## Execution closeout

All four delegated workers used `gpt-6-luna` at `xhigh` in the current Codex session: plan review, CLI implementation, TTS implementation, and final testing. The parent accepted R1–R6 and kept the requested sequential split instead of R7.

Worker A stopped after two failed suite runs due to a recursive test mock. The owner explicitly approved the exact test-only correction and rerun. Final verification also corrected one in-scope default-output diagnostic after parent review.

Final result: 18 focused tests passed; no new Ruff finding identities, 15 retained baseline findings; git diff --check passed; protected owner prompt hash unchanged. See `pr1_merge_fixes_verification.md`. Parent reviewed the final diff and confirmed no dependency/model/parser/assembler implementation changes. Production changes are limited to CLI filesystem/lifetime behavior and TTS diagnostics, with two matching instruction corrections. This is a lasting local code fix, not an operational workaround.

At the implementation verification closeout, changes were uncommitted and no PR update or merge had been performed. Commit identity/history disposition and the explicitly listed deferrals remain unresolved; this result is not a blanket privacy or release clearance.
