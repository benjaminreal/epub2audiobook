# Ruff baseline cleanup plan review

Date: 2026-10-10  
Reviewer runtime: `codex / gpt-6-luna / xhigh`  
Review scope: read-only review of `docs/ruff_baseline_cleanup_plan.md`, current source, Ruff configuration, and live findings. No source changes or unit tests were run.

## Verdict

Approve the bounded cleanup plan for implementation after the required dispositions below. The inventory is complete for the requested command, and the proposed edits are the minimum direct fixes for the 15 current findings. No Ruff configuration, dependency, lockfile, broad formatting, or audiobook-conversion work is needed.

## Live confirmation

- Repository: branch `fix/ruff-baseline-cleanup`, HEAD `94e55904054d9a4fb9048d454a65823725d0f8bb`.
- `pyproject.toml`: Ruff target `py310`, line length `88`, selected rules `E`, `F`, `W`, and `I`; no additional Ruff configuration was present in that file.
- `uv run --no-sync --offline ruff --version`: `ruff 0.15.16`.
- `uv run --no-sync --offline ruff check --statistics epub2audiobook tests`: exit 1, `Found 15 errors`; counts are `cli.py` 11 (I001 1, F541 7, F401 1, E501 2), `assembler.py` 2 (F401 1, E501 1), and `preprocessor.py` 2 (E501 2). These match the plan.
- The only source lines identified by the plan are the lines reported by the live check. The proposed import removals leave the `parser` module import and `check_ffmpeg` import in place; the proposed wrapping preserves the original call arguments and strings.
- The worktree already has a modified `product_definition_prompt.md` and the untracked review plan. The prompt SHA-256 is `3c2fc0bb44422604b7ba307326e24a1a5784aee588fd13f20a4fe582a9f7a6c1`, matching the plan's protected value.
- The external verification helper and original-source captures exist under `/private/tmp/ruff-baseline-cleanup-q_0ee0i1`. The helper checks retained imports, a normalized AST comparison, captured `--help` output, and the protected prompt hash. I inspected it but did not run it because source edits have not begun.

## Recommendations

1. **REQUIRED — Disposition the `assembler.DependencyError` module attribute.** Removing the unused import also removes the currently accessible `epub2audiobook.assembler.DependencyError` name. A repository search found no in-repo consumer, but external consumers cannot be ruled out from this checkout. Record that this incidental re-export is not a supported API before removing it; if it is supported, keep an explicit re-export (such as a redundant alias Ruff recognizes) instead of suppressing F401.

2. **REQUIRED — Scope the final diff relative to the existing worktree.** The prompt edit and untracked plan predate implementation and are outside the three-file source cleanup. Compare the implementation delta to the captured originals, require source changes only in `cli.py`, `assembler.py`, and `preprocessor.py`, and preserve the prompt hash. Do not interpret the total working-tree file list as the cleanup patch's file list.

3. **OPTIONAL — Describe CLI-output verification coverage precisely.** Comparing `--help` covers argparse help, including the wrapped default-output help at `cli.py` line 262. It does not execute the custom no-path usage text (lines 65–73), success message (line 223), or skipped-chapter warning (line 231). The normalized AST check should catch semantic changes to those literal-only f-strings and wrapped expressions. If an independent runtime check is desired, capture the no-path branch with `open_file_dialog` replaced to return `None`; this can remain a temporary check, not a permanent test.

## Minimal post-edit verification

Run the unchanged Ruff command and require zero findings; run the existing model-free unittest command stated in the plan; run the existing helper against its pre-edit captures; and run `git diff --check`. Review the source-only diff against the three-file scope, confirm CLI `--help` output equality, and recheck the protected prompt hash. The plan records 39 existing tests; this review did not rerun them.

## Non-goals

No new dependencies or tests, Ruff suppressions/config changes, whole-file formatting, full-book conversion, model/download activity, task-database changes, or repository-wide security/listening claims.
