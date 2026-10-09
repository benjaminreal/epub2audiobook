[drafted by gpt-6-luna]

# PR #1 merge-fix verification

## Result

The focused merge-fix suite passes: **18 tests passed**. The final run used:

```text
uv run --no-sync --offline python -m unittest discover -s tests -v
Ran 18 tests in 0.034s
OK
```

No speech model was loaded, no model files were downloaded, and no private book was read. All fixtures and generated test outputs were synthetic and kept in temporary directories outside Dropbox.

## Corrections and coverage

The late-output-stat test now resolves its expected output path before patching `Path.stat()`, then compares it to a lexically normalized absolute path inside the mock. This prevents the mock from recursively calling the patched `Path.stat()` through `Path.resolve()` and lets the test verify that a late `PermissionError` returns processing code 3 with an output-filesystem diagnostic and no traceback.

Output tests cover default and explicit destinations, creation of a missing explicit parent, preservation of existing output bytes during preflight, invalid extensions and destination types, injected permission failures, and rejection of invalid default and explicit targets before engine creation. They also cover late assembly/stat failures and temporary-directory cleanup after success, all-chapter failure, assembly failure, and `KeyboardInterrupt`, while preserving an unrelated sentinel.

TTS tests cover sanitizing content-bearing backend `RuntimeError` and `TTSError` messages, safe initialization errors, Kokoro constructor and synthesis logging suppression, restoration of the backend logger after success and failure, actionable dependency/selection errors, and content-marker absence from CLI warnings and summaries.

## Checks

- `git diff --check` exited 0.
- `product_definition_prompt.md` matched the protected baseline SHA-256: `3c2fc0bb44422604b7ba307326e24a1a5784aee588fd13f20a4fe582a9f7a6c1`.
- Ruff was run with `uvx --offline ruff check --no-cache epub2audiobook tests --output-format json`. It exited 1 because 15 baseline findings remain. Compared with `ruff-before.json` by file, rule code, message, and occurrence count, there are no new production findings or test findings; two CLI `F541` findings were removed. The remaining findings are in `assembler.py`, `cli.py`, and `preprocessor.py`.
- `ffprobe` was available, but the optional synthetic WAV-to-M4B smoke check was not run. No real TTS or full-book conversion is claimed.

## Scope and limits

The change remains within the PR #1 output preflight, late filesystem error handling, TTS diagnostic privacy, temporary audio lifetime, focused tests, and the two related `CLAUDE.md` corrections. The existing owner edit in `product_definition_prompt.md` was preserved byte-for-byte. No commit, push, merge, or history/configuration change was made.

The privacy result is limited to the supported application paths: TTS exception text is reduced to safe stage/type details, and suppression applies narrowly to the `kokoro_onnx` logger around backend construction and synthesis. Normal progress output still includes book titles, authors, and paths; arbitrary native dependency output and network behavior are outside this check. Model-download integrity/timeouts, parser work, distribution packaging, and the commit-identity/history decision remain deferred.
