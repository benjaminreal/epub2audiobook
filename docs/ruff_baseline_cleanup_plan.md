[drafted by gpt-6.1-sol]

# Ruff baseline cleanup plan

Date: 2026-10-10. Status: Luna 6 xhigh review completed, parent dispositions
incorporated, both workers finished, and combined parent verification passed.
Changes are local and uncommitted on `fix/ruff-baseline-cleanup`.

## Objective

Resolve the 15 confirmed baseline findings from Ruff 0.15.16 so
`uv run --no-sync --offline ruff check epub2audiobook tests` exits 0, preserving
runtime behavior, text processing, CLI output, imports needed for deferred
dependency checks, and existing tests. The already prepared ten introduced
fixes are published separately in a small PR. This baseline cleanup is local
implementation work; its publication and merge are separate actions.

## Inventory and minimum edits

| File | Findings | Minimum change |
|---|---|---|
| `epub2audiobook/cli.py` | I001 (1), F541 (7), F401 (1), E501 (2): 11 | Sort existing imports; remove seven unnecessary f-string prefixes; remove only unused `BookMetadata` from the deferred parser import; wrap warning/help expressions without changing strings. |
| `epub2audiobook/assembler.py` | F401 (1), E501 (1): 2 | Preserve `DependencyError` with an explicit same-name re-export (retain `check_ffmpeg`); wrap the metadata log call without changing its arguments. |
| `epub2audiobook/preprocessor.py` | E501 (2): 2 | Wrap two `re.sub` calls; keep regex strings, replacements, flags and execution order exactly unchanged. |

Keep Ruff configuration, dependencies, lockfile, public CLI choices and model
behavior unchanged. No whole-file formatter, blanket autofix, suppression or
rule disabling. Do not fix unrelated defects or change source book content.
Protect `product_definition_prompt.md` (SHA-256
`3c2fc0bb44422604b7ba307326e24a1a5784aee588fd13f20a4fe582a9f7a6c1`).
No model runs, downloads, new dependencies or task-database changes.

## Review and implementation

1. Luna 6 at xhigh reviews scope, minimum work, behavioral risks, verification
   quality and omissions. It produces recommendations in a report; no source
   edits during review. Parent reads the report and records each disposition.
2. After parent disposition, Luna 6 at xhigh owns only `cli.py`; Sol 6.1 at
   high owns only `assembler.py` and `preprocessor.py`. Work may run in parallel
   with disjoint file ownership. Workers do not run Git mutations or touch the
   separate PR, documentation, protected prompt or each other's files.
3. Parent reviews all changes once, checks the exact file scope and owner-prompt
   hash, and verifies the combined tree. No new permanent tests for mechanical
   edits unless the review finds a concrete untested behavior risk.

## Verification and acceptance

- Capture the 15-finding JSON inventory and original three source files before
  edits, outside Dropbox. Use the existing Python 3.12 uv environment.
- Review a normalized AST comparison: ignore import sorting/unused symbols and
  normalize literal-only f-strings to strings; all other syntax must match.
  Also check retained imports explicitly, treating an explicit same-name alias
  as the equivalent existing binding. This complements the existing suite.
- Run `uv run --no-sync --offline ruff check epub2audiobook tests`: zero
  findings, exit 0 under the unchanged configuration.
- Run `uv run --no-sync --offline python -m unittest discover -s tests -q`:
  all existing model-free checks pass (currently 39).
- Compare CLI `--help` output before/after; run `git diff --check`; check exact
  changed-file scope and protected prompt SHA-256.
- No further full-book conversions: this task changes formatting and unused
  names. Retain the earlier real-backend results as their point-in-time evidence.
- Record final commands/results and any remaining uncertainty. Do not claim a
  repository-wide security audit, clean installation or listening verification.

## Parent disposition of Luna's review

Review: `codex / gpt-6-luna / xhigh`, one completed T3 delegated review.
The report is preserved in [ruff_baseline_cleanup_review.md](ruff_baseline_cleanup_review.md).
It confirms all 15 findings and finds no need for expanded formatting,
dependencies, model runs or permanent tests. Parent read the complete report
and inspected the affected imports, strings and regex calls.

1. **R1 accepted with the compatibility-preserving option.** Rather than
   declaring the existing `assembler.DependencyError` module attribute
   unsupported, keep it through `DependencyError as DependencyError`. This
   explicit re-export resolves F401 and preserves external access. Keep
   `check_ffmpeg`; remove only the function-local unused `BookMetadata` in CLI.
2. **R2 accepted.** Compare source edits against the three captured originals,
   not against all dirty files. The owner prompt and this plan predate worker
   implementation; they are not source cleanup edits. Preserve the owner hash.
3. **R3 accepted as a verification qualification.** CLI `--help` equality
   checks argparse output only. The normalized AST comparison verifies the
   custom no-path usage, success and skipped-chapter messages; it does not
   execute those paths. The existing model-free suite supplements this check.
   No extra runtime no-path test is necessary for literal-preserving edits.

PR #3, containing the earlier ten introduced fixes and verification notes,
has been merged as `1cb52dd13cbe82308347e3d96090ac64af7d1215`. Local `master`
and the local baseline branch were fast-forwarded to that commit; its tracked
tree equals the tested PR head. Workers implement only this separate baseline
cleanup; publication of their new changes has not been requested.

## Implementation and parent verification

T3 task receipts confirm `codex / gpt-6-luna / xhigh` implemented the 11 CLI
findings and `codex / gpt-6.1-sol / high` implemented the four assembler and
preprocessor findings. Their source ownership was disjoint and neither worker
made Git mutations. Parent reviewed both source diffs against the captured
originals; edits resolve exactly the planned findings. The explicit exception
re-export is retained, strings and regex contents are unchanged, and deferred
imports remain deferred. No additional tests, dependencies, rule suppressions
or configuration changes were introduced.

| Parent check | Result |
|---|---|
| `uv run --no-sync --offline ruff check epub2audiobook tests` | All checks passed; zero findings, exit 0. |
| `uv run --no-sync --offline python -m unittest discover -s tests -q` | All 39 tests passed in 0.311 seconds, exit 0. |
| `uv run --no-sync --offline python /private/tmp/ruff-baseline-cleanup-q_0ee0i1/verify_mechanical_changes.py` | Eight assertions passed: three normalized AST comparisons, three import-binding comparisons, CLI help equality and protected prompt hash. |
| `git diff --check` | Passed, exit 0. |
| Source scope and preservation | Only the three assigned Python files changed for this cleanup; the separate preexisting prompt edit retains its protected hash. |

The normalized AST comparisons preserve call arguments, control flow and
literal contents, allowing only the stated import edits and literal-only
f-string normalization. CLI help was compared at runtime. Those checks do not
execute every CLI branch; the existing synthetic suite provides additional
behavior coverage. No new real-model or book conversion was necessary or run.

These are lasting source fixes, not a suppression or workaround. The original
15 findings, source snapshots, behavior receipt and worker receipts are retained
under `/private/tmp/ruff-baseline-cleanup-q_0ee0i1`. That directory is temporary.
The review report in this repository is byte-identical to Luna's original,
SHA-256 `d785386e1ca456d494d9cd71fcf37a8c4d4ba54b7ae3022bbf553b12a185bfcc`.

Implementation is complete locally. The new cleanup and its plan/review have
not been committed, pushed or merged, and no task-database changes were made.
This is lint/behavior verification, not release, listening or repository-wide
security clearance.
