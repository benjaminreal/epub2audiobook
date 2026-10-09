# CLAUDE.md — epub2audiobook

**Project:** epub2audiobook — Local ePub-to-Audiobook Converter for Mac
**Owner:** Benjamín Calderón Real
**Last updated:** 2026-10-07

---

## What This Project Is

A Python tool that converts ePub files into M4B audiobooks with chapter markers, using local Kokoro TTS on Apple Silicon Macs. No cloud dependencies, no API costs, no subscriptions.

**Current stage:** MVP (v0.1.0) done; working toward v1.0
**Target platform:** macOS (Apple Silicon — M1/M2/M3+)
**License:** GPL-3.0 (from v0.2; Kokoro's espeak-ng phonemizer and Calibre are GPL)
**Distribution path:** Engine (this repo, tagged GitHub releases via `uv tool install`) + thin Calibre plugin → Calibre plugin index at v1.0

**Source of truth for v1.0 scope:** `docs/v1_release_definition.md`. Where it disagrees with this file, it wins.

---

## Architecture Decisions (Locked for MVP)

These decisions are made. Do not revisit them without explicit instruction.

| Decision | Choice | Rationale |
|---|---|---|
| TTS Engine | Kokoro only. Piper is dropped (2026-10-07); its code and `piper-tts` dependency are removed in v0.2 | Kokoro chosen 2026-10-06 after an A/B listening test: Piper sounded robotic with flat prosody |
| Kokoro backend | ONNX on CPU with multiprocess parallelism (default, ~10x realtime); MLX-Audio on the Apple GPU as an opt-in extra (`--backend mlx`, ~27x) | Decided 2026-10-07. ONNX is the default because MLX adds ~1.1 GB of deps. CoreML EP and int8 gave no gain |
| Voice | `af_heart` (English default); `--voice` overrides | `af_heart` preferred over `am_michael` and `bm_george` in the 2026-10-06 test |
| Pacing | Synthesize per paragraph; 600 ms paragraph pause | Avoids run-on prosody between paragraphs |
| Output format | M4B (AAC 64kbps, mono, 44.1kHz) | Chapter markers, bookmark support, 50% smaller than stereo |
| ePub parsing | EbookLib + BeautifulSoup4 | Standard approach, spine-order preservation, battle-tested |
| Audio assembly | PyDub + FFmpeg | Chapter combining, format conversion |
| Metadata | Mutagen (MP4 tags) | Cover art, audiobook stik tag, narrator field |
| Chapter markers | FFmpeg FFMETADATA | Standard approach for M4B chapter embedding |
| Python env | ARM64 native (no Rosetta) | 2-5x performance over x86 emulation |
| Interface (MVP) | CLI with simple file picker | Fastest to build, easiest to test, wrappable later |

---

## MVP Scope — What v0.1.0 Does

**One pipeline, one job:**
1. User selects a single ePub file (file picker dialog or CLI argument)
2. Tool extracts text in spine order, preserving chapter structure
3. Piper TTS generates audio for each chapter
4. Chapters are combined into a single M4B with chapter markers
5. Metadata (title, author, cover art) is embedded
6. Output file is saved to user's Downloads folder (default) or specified path

**What v0.1.0 does NOT do:**
- Batch processing (multiple books)
- Voice selection UI
- Resume/checkpoint for interrupted conversions
- Calibre plugin integration
- Queue management
- Voice cloning
- Non-English language support
- Speed/pitch controls
- Cloud TTS fallback

---

## Development Principles

### 1. Ship the Pipeline First
Get the end-to-end pipeline working before optimizing any single stage. A working tool with rough edges beats a polished parser with no audio output.

### 2. One File, One Responsibility
Each module handles one stage of the pipeline. If a module does two things, split it.

```
epub2audiobook/
├── cli.py              # Entry point, argument parsing, file picker
├── parser.py           # ePub extraction (text + metadata + cover)
├── preprocessor.py     # Text cleaning for TTS
├── tts_engine.py       # TTS engine wrapper (abstract base + Kokoro)
├── assembler.py        # Audio combining, chapter markers, metadata
├── config.py           # Constants, defaults, paths
└── utils.py            # Logging, progress, file helpers
```

### 3. Test Each Stage Independently
Every module must be runnable and testable in isolation:
- `parser.py` can extract text from an ePub and write chapter files to disk
- `preprocessor.py` can clean a text file and output the result
- `tts_engine.py` can take a text string and produce a WAV file
- `assembler.py` can take a folder of WAVs and produce an M4B

### 4. Fail Loud, Not Silent
No silent failures. If a chapter fails TTS generation, log a content-safe error with chapter number, skip the chapter, and continue. Report all failures at the end. Never produce a corrupt M4B without warning.

### 5. Progress Feedback Is Not Optional
Converting a 300-page book takes 30-60 minutes. The user must see:
- Which chapter is being processed (e.g., "Chapter 3/24")
- Elapsed time
- Estimated time remaining (after first chapter completes)

### 6. Defensive Text Preprocessing
Raw ePub text will break TTS. The preprocessor must handle:
- Unicode normalization (smart quotes, em-dashes, ligatures)
- Abbreviation expansion (Mr., Dr., etc., e.g., i.e.)
- URL/email removal
- Footnote container removal
- Whitespace normalization
- HTML entity cleanup

### 7. Spine Order Is Sacred
Never iterate ePub items by manifest order. Always follow spine order. Violating this produces scrambled chapters.

### 8. Memory Discipline
Process chapters sequentially — generate audio, save to disk, release memory. Do not accumulate AudioSegments in RAM. A 500-page book will exhaust memory if you hold everything.

### 9. FFmpeg Is a Runtime Dependency
PyDub requires FFmpeg at runtime. The tool must check for FFmpeg on startup and give a clear error message with install instructions (`brew install ffmpeg`) if missing.

### 10. Abstract the TTS Interface
Keep the TTS engine behind an abstract interface, even with Kokoro as the only engine:
```python
class TTSEngine(ABC):
    @abstractmethod
    def generate(self, text: str, output_path: str) -> str: ...
    
    @abstractmethod
    def get_voice_name(self) -> str: ...
```
This costs nothing now and saves a full rewrite when adding Kokoro/MLX-Audio in v2.

---

## Coding Standards

- **Python 3.10+** (minimum for Apple Silicon native support)
- **Type hints** on all function signatures
- **Docstrings** on all public functions (Google style)
- **Logging** via Python's `logging` module, not print statements
- **No global state** — pass configuration explicitly
- **Error handling:** Catch specific exceptions, never bare `except:`
- **Dependencies:** Minimize. Every dependency is a maintenance burden.
  - Core: `kokoro-onnx`, `numpy`, `ebooklib`, `beautifulsoup4`, `pydub`, `mutagen` (`piper-tts` is still present until its v0.2 removal). MLX-Audio is an optional extra only
  - Models download on first use (~353 MB for Kokoro). Currently `~/.local/share/kokoro_onnx`; v0.2 moves them to `~/Library/Application Support/epub2audiobook/models/`, migrating existing files once
  - **Licensing:** Kokoro's phonemizer uses espeak-ng (GPL), so the project is GPL-3.0
  - System: `ffmpeg` (Homebrew)
  - Dev: `pytest`, `ruff`
- **No Rosetta.** All packages must install and run on ARM64 natively. If `platform.machine()` != `arm64`, warn the user.

---

## File Conventions

- Audio intermediate files: `{temp_dir}/chapter_{NNN}.wav` (zero-padded 3 digits)
- Final output default: `~/Downloads/{book_title}.m4b`
- Temp directory: Use `tempfile.TemporaryDirectory()` and clean up on exit
- Config: No config file for MVP. All defaults are in `config.py`. CLI flags override defaults.

---

## What "Done" Looks Like for MVP

The MVP is complete when:
1. `python -m epub2audiobook path/to/book.epub` produces a valid M4B in ~/Downloads
2. The M4B plays in Apple Books with correct chapter markers
3. Metadata (title, author, cover) displays correctly in Apple Books
4. Audio is natural-sounding enough for a 30-minute commute listen without fatigue
5. A 300-page novel completes processing in under 60 minutes on M2 (met with `--engine piper`; Kokoro on CPU takes roughly 2 hours, so this target needs re-deciding or the v0.3/v0.5 speedups)
6. Errors during conversion are logged clearly and don't produce corrupt output
7. The tool runs without internet connectivity

---

## Roadmap to v1.0

Build only the current version. Details and acceptance criteria are in `docs/v1_release_definition.md`.

- **v0.2:** Kokoro backends (ONNX parallel default, MLX opt-in), Piper removed, model folder moved, audio quality Tier A, test suite started
- **v0.3:** Spanish (language detection, ES preprocessor, voice choice)
- **v0.4:** Engine hardening: resume, `--progress json`, cancellation, `doctor`, install command
- **v0.5:** Calibre plugin (thin front end that calls the engine as a subprocess)
- **v0.9:** Beta: ePub corpus, clean-machine install test, docs
- **v1.0:** Tagged engine release on GitHub and Calibre plugin index submission. No standalone `.app`, no PyPI, no Windows/Linux

---

## Reference Material

The following documents contain technical research used to make architecture decisions. They are context, not instructions — do not implement patterns from these documents unless they align with the decisions above.

- `docs/implementation_guide.pdf` — Comprehensive build guide (Piper, Calibre plugin architecture, M2 optimization)
- `docs/landscape_analysis.md` — Competitive landscape of ebook-to-audiobook tools
