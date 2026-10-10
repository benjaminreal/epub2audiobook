# Kokoro backend usage

These commands are for a source checkout on macOS with Apple Silicon, using
the project's Python 3.12 environment. FFmpeg must also be available
(`brew install ffmpeg`). Release installation and the root README are separate
packaging work.

## Default: ONNX on the CPU

From the repository root:

```sh
uv sync --python 3.12
uv run python -m epub2audiobook path/to/book.epub
```

Kokoro defaults to ONNX and voice `af_heart`. It uses six spawned CPU workers
with two ONNX threads per worker, queues at most twelve chunks, and writes
audio in source order. Chapters remain sequential, and paragraphs end with
600 ms of silence. To select a voice or backend explicitly:

```sh
uv run python -m epub2audiobook path/to/book.epub --backend onnx --voice bm_george
```

ONNX checks the full voice name against its local voice pack before chapter
synthesis. Unknown names fail at initialization with available voice choices;
the parent process reads voice metadata without loading the neural model.

## Optional: MLX on the Apple GPU

MLX requires an Apple Silicon Mac and its optional dependencies:

```sh
uv sync --python 3.12 --extra mlx
uv run --extra mlx python -m epub2audiobook path/to/book.epub --backend mlx
```

The extra pins MLX-Audio 0.5.8, Misaki 0.9.4 with English support, and the
English spaCy 3.8.0 model wheel. The earlier estimate of approximately 1.1 GB
is for MLX dependencies; model assets need additional space. That historical
estimate is not a fresh measurement of this installation.

MLX uses `mlx-community/Kokoro-82M-bf16`. After loading it, the adapter checks
the full voice name against the cached `voices/*.safetensors` files with a
local-only cache lookup. `--voice bm_george` also works when that voice is
present. Both backends reject unsupported voice language prefixes.

MLX supplies its own sentence pacing, which may sound different from ONNX.
The adapter adds the same 600 ms paragraph pause; it does not promise identical
sentence timing or audio between backends.

## Downloads and current storage

First use may download public model assets. ONNX obtains its model and voice
pack from the public Kokoro ONNX GitHub release (historically about 353 MB),
currently stored in `~/.local/share/kokoro_onnx`. MLX model assets use the
Hugging Face cache, normally `~/.cache/huggingface/hub`, with cache location
overrides honored by Hugging Face. The optional spaCy wheel comes from its
public GitHub release during dependency installation. Moving models to
`~/Library/Application Support/epub2audiobook/models` is separate work.

The retained `--engine piper` option still uses the default backend selection;
combining Piper with `--backend mlx` fails clearly. Piper removal is a separate
v0.2 task.

## Diagnostics and verification

ONNX worker errors retain the exception type and omit backend exception text;
partial ONNX WAVs are removed after generation errors when the filesystem permits.
If deletion fails, the backend still attempts worker shutdown and reports only
exception types. The CLI closes its pool before removing conversion temporary files.

During MLX generation, `logging.disable(logging.CRITICAL)` temporarily
suppresses Python logging from all loggers and restores the previous threshold
afterward. This assumes the current synchronous, single-conversion CLI. It
does not establish privacy behavior for native libraries, direct stdout/stderr
writes, downloads, or network traffic.

See [verification and limits](kokoro_backends_verification.md) for synthetic
checks and the historical short model smoke receipts. Conversion performance,
listening quality, offline operation, and full-book conversion remain unverified
for these changes.
