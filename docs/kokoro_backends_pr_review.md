# Kokoro backend PR review

**Date:** 2026-10-09. **Reviewer:** GPT-6.1-Sol, parent Codex session.
**Verdict:** No unresolved blocking findings in the reviewed backend scope.
This is a source and application-level privacy review, not release clearance
or a dependency vulnerability audit.

## Scope and outcome

Reviewed the complete changes against `master` at
`8e25e87351b21dc47c4cb2a7fcf2c4d618d69fae`: parallel ONNX, optional MLX,
factory routing, CLI lifetime, dependency declarations and lockfile, focused
tests, and backend documentation. The unrelated owner prompt edit is excluded.

One correctness/privacy finding was resolved: failure to unlink a partial ONNX
WAV previously bypassed worker shutdown and exposed the raw cleanup exception.
A synthetic regression test reproduced the raw exception before the fix.
Generation now attempts deletion and worker shutdown independently, reports
failures using exception types, and suppresses chained backend diagnostics.
The regression test verifies shutdown despite failed deletion and safe errors.
This is a lasting source fix; it cannot guarantee deletion when the filesystem
refuses it or successful shutdown if the executor itself fails.

Reviewed source-order writes, bounded scheduling, process-local model reuse,
CPU thread/provider settings, full-name voice validation, deferred MLX imports,
optional platform markers, logging restoration and temporary-file lifetime.
The CLI closes workers before removing its conversion directory, including
error and interruption exits. Prompt cancellation of running tasks is separate
work; shutdown can wait for already-running chunks.

## Verification

- `uv run --no-sync --offline python -m unittest discover -s tests -v`:
  **39 tests passed**, including a real two-process spawn test using a synthetic
  model and the new cleanup-failure regression. No model inference or downloads.
- `uv lock --check`: passed, resolving 126 packages.
- `uv run --no-sync --offline python -m epub2audiobook --help`: passed.
- `git diff --check`: passed.
- Lockfile comparison: no existing package versions changed or packages removed.
  MLX is an optional extra restricted to macOS arm64. Distribution URLs use
  `pypi.org`, `files.pythonhosted.org` and `github.com`; none contain URL
  credentials, queries or fragments, and distributions have locked hashes.
- Protected owner prompt SHA-256 remained
  `3c2fc0bb44422604b7ba307326e24a1a5784aee588fd13f20a4fe582a9f7a6c1`.

## Limits

Ruff is unavailable and lint was not verified. No GitHub Actions workflow is
configured in this checkout. Earlier approved real-model smoke runs produced
non-silent short WAVs, but predate the revised voice-validation constructors.
No additional model run, book processing, full conversion, speed benchmark,
listening test, clean-machine install or offline-network test was performed.

MLX suppression covers Python logging during synchronous generation, and
restores the prior global threshold; native/direct output and network behavior
were not verified. Model download integrity, packaging repair, Piper removal
and model-storage migration remain separate work.
