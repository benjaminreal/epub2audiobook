# epub2audiobook v1.0: Release Definition

**Status:** Final, approved by the owner in Session #3, 2026-10-07. Change it only by explicit owner decision.
**Owner decisions behind this definition:**
- v1.0 is a Calibre plugin plus a separately installed engine.
- v1.0 supports macOS on Apple Silicon only.
- v1.0 supports English and Spanish.
- Kokoro on ONNX with multiprocess parallelism is the default backend. MLX on the GPU is opt-in.
- The engine is distributed as GitHub releases only.
- Models are stored in `~/Library/Application Support`.
- Piper is dropped.
- The plugin records only the M4B format on the book.

---

## 1. What v1.0 is

A Calibre user on an Apple Silicon Mac selects one or more books and chooses **Convert to Audiobook**. A few minutes to an hour later, each book has an M4B audiobook attached, with chapters, cover and metadata. Everything runs locally: no cloud services, no API costs, no account.

v1.0 consists of two installable parts:

| Part | What it is | Why it's separate |
|---|---|---|
| **Engine** (`epub2audiobook`) | The current Python CLI, extended. Runs in its own environment, installed from a tagged GitHub release with `uv tool install` (see §2). | Calibre's bundled Python can't reliably load compiled packages such as `onnxruntime`, `numpy` or MLX. The engine has to run outside Calibre. |
| **Calibre plugin** | A thin `InterfaceAction` plugin with a toolbar button, context menu, settings dialog and job queue. It calls the engine as a subprocess and adds the result to the library. | Gives the plugin a small, pure-Python footprint, which suits the Calibre plugin index. The KFX Output plugin uses the same pattern with Kindle Previewer. |

**License:** GPL-3.0 for both parts. Kokoro's phonemizer uses espeak-ng, which is GPL, and Calibre is GPL-3. Dropping Piper doesn't change this. GPL-3.0 replaces the MIT license in the current spec.

## 2. Scope

### In scope

**Engine**
- Kokoro is the only TTS engine, with two backends: ONNX with CPU parallelism (default, about 10× real time) and MLX on the Apple GPU (opt-in extra, about 27×). Piper, its code, its `--engine` flag and the `piper-tts` dependency are removed.
- English and Spanish:
  - The language is taken from the ePub `dc:language`, and a `--language` flag overrides it.
  - Each language has its own preprocessor rules: abbreviations, numbers, Roman numerals and ordinals.
  - Each language has a default voice, chosen by listening test (Spanish candidates: `ef_dora`, `em_alex`, `em_santa`).
- Audio quality Tier A:
  - loudness normalized to about −18 LUFS with peaks at or below −3 dBTP;
  - `--speed`;
  - pauses at chapter titles and scene breaks;
  - empty and front-matter chapters dropped;
  - text cleanup (ellipses, dashes, `***`, "St.").
- **Resume:** an interrupted conversion restarts from the last finished chapter. Chapter WAVs are kept in a stable work directory that is keyed by a hash of the book.
- **Plugin-facing contract:**
  - `--progress json` emits machine-readable progress lines;
  - stable exit codes;
  - cancellation on SIGTERM, with cleanup;
  - `epub2audiobook doctor` checks FFmpeg, the models, the backend and disk space.
- First-run model download with a clear size notice. After that, conversion works fully offline.
- **Model location:** `~/Library/Application Support/epub2audiobook/models/`, shared by both backends. On first run, models already in `~/.local/share/kokoro_onnx` are moved there instead of downloaded again.
- **Distribution:** tagged GitHub releases on `github.com/benjaminreal/epub2audiobook`. Nothing is published to PyPI.
  - Default install: `uv tool install git+https://github.com/benjaminreal/epub2audiobook@v1.0.0`
  - With MLX: `uv tool install "epub2audiobook[mlx] @ git+https://github.com/benjaminreal/epub2audiobook@v1.0.0"`
  - To upgrade, users reinstall with the new tag. `epub2audiobook doctor` reports whether a newer release exists, using the GitHub releases API. It only reports and never upgrades.

**Calibre plugin**
- Convert the selected books (one or many). Each book runs as a Calibre background job, and books are processed one at a time.
- Settings:
  - engine path (auto-detected);
  - backend (ONNX or MLX, if installed);
  - voice per language;
  - speed.
- Preview a voice on a short sample.
- The finished M4B is added to the book record as a format, and nothing else on the record changes (no custom columns). Users find converted books with `formats:m4b`. Saving a copy to a folder is optional.
- The plugin finds the engine at `~/.local/bin/epub2audiobook`, the `uv tool` default. The path can be overridden in settings.
- Errors from the engine are shown in the Calibre job details and are never silently dropped.

### Out of scope for v1.0 (v1.x or later)
- Windows and Linux. The ONNX default keeps this feasible later.
- A standalone macOS `.app` bundle.
- MP3 or per-chapter output.
- Piper or any second TTS engine.
- A PyPI package.
- Custom Calibre columns.
- Voice blending, a separate dialogue voice, and the Tier B/C engines (Chatterbox, Dia and others).
- Languages other than English and Spanish.
- Cloud TTS and voice cloning.

## 3. Acceptance criteria

| # | Criterion |
|---|---|
| V1-01 | On a clean Apple Silicon Mac, a user installs the engine and the plugin by following the README, without using a terminal beyond one documented install command. |
| V1-02 | Converting a book from Calibre attaches an M4B to that book. The M4B plays in Apple Books with correct chapters, title, author and cover. |
| V1-03 | A 300-page English novel converts in **≤ 60 minutes** on an M2 with the default ONNX backend, and in ≤ 25 minutes with MLX. This is tight: 10 hours of audio at 10.3× is about 58 minutes. |
| V1-04 | A Spanish ePub is detected as Spanish, voiced with a Spanish voice, and passes an owner listening check. Abbreviations and numbers are read correctly. |
| V1-05 | Loudness of the output is −18 ± 1 LUFS with true peak at or below −3 dBTP, measured with `ffmpeg ebur128`. |
| V1-06 | Cancelling or killing a conversion leaves no corrupt M4B in the library. Re-running resumes without redoing finished chapters. |
| V1-07 | A batch of 5 books runs unattended, and each book's success or failure is reported separately. |
| V1-08 | With models already present and the network disabled, conversion succeeds. |
| V1-09 | A `pytest` suite covers the parser, preprocessor (EN and ES), assembler and CLI contract, and passes. A corpus of at least 10 real ePubs converts without crashes, covering EPUB2, EPUB3, flat, image-heavy and no-cover books. |
| V1-10 | The plugin is listed in the Calibre plugin index: it has its own MobileRead Plugins thread with a single `.zip` attached to the first post and a "Version History" section, and the index entry has been sent to a moderator. The engine has a tagged `v1.0.0` GitHub release with a changelog, and the README install command works on a clean Mac. |

## 4. Proposed path from v0.1.0

The current CLAUDE.md roadmap puts the Calibre plugin at v0.4 and MLX at v0.5. This path reorders the work so the engine is finished before the plugin wraps it.

| Version | Content | Existing task |
|---|---|---|
| v0.2 | Kokoro backends (ONNX parallel default, MLX opt-in), Piper removed, models moved to Application Support, Tier A quality, test suite started | `8c68c073`, `d0985e9d` |
| v0.3 | Spanish: language detection, ES preprocessor, voice choice | `9e54e8ca` (parked; would be rescoped) |
| v0.4 | Engine hardening: resume, `--progress json`, cancellation, `doctor`, packaging and install command | — |
| v0.5 | Calibre plugin: action, settings, jobs, add the format to the library | — |
| v0.9 | Beta: run the ePub corpus, clean-machine install test, docs | — |
| v1.0 | Tag the `v1.0.0` engine release on GitHub and submit the plugin to the Calibre index | — |

## 5. Resolved questions (2026-10-07)

| Question | Decision |
|---|---|
| Engine distribution | GitHub releases only, installed with `uv tool install git+…@<tag>`. No PyPI package. |
| Model location | `~/Library/Application Support/epub2audiobook/models/`. Existing models are moved there once. |
| Piper | Dropped in v1.0. Kokoro is the only engine. |
| Calibre index requirements | No rules on licensing or external dependencies. The plugin needs its own thread in the MobileRead Plugins forum with a single `.zip` attached to the first post and a "Version History" section, and a private message to a moderator with the index entry. The Plugin Updater reads the version, minimum Calibre version and platforms from the plugin code, so we choose the minimum version ourselves. |
| Book record | Attach the M4B format only. No custom column. |

## 6. Remaining open items

- **Minimum Calibre version:** choose it at v0.5 from the Calibre APIs the plugin actually uses.
- **Spanish default voice:** choose it by listening test in v0.3.
