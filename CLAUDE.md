# CLAUDE.md — epub2audiobook

**Project:** epub2audiobook — Local ePub-to-Audiobook Converter for Mac
**Owner:** Benjamín Calderón Real
**Last updated:** 2026-04-03

---

## What This Project Is

A Python tool that converts ePub files into M4B audiobooks with chapter markers, using local TTS (Piper) on Apple Silicon Macs. No cloud dependencies, no API costs, no subscriptions.

**Current stage:** MVP (v0.1.0)
**Target platform:** macOS (Apple Silicon — M1/M2/M3+)
**License:** Open source (MIT)
**Distribution path:** Standalone CLI/GUI app → Calibre plugin (v2) → Calibre plugin index

---

## Architecture Decisions (Locked for MVP)

These decisions are made. Do not revisit them without explicit instruction.

| Decision | Choice | Rationale |
|---|---|---|
| TTS Engine | Piper TTS | Best naturalness rating (5/5), 30+ languages, trivial install |
| Voice | `en_US-lessac-medium` (default) | Best quality-to-size ratio for English narration |
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
├── tts_engine.py       # Piper TTS wrapper (abstract base for future engines)
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
No silent failures. If a chapter fails TTS generation, log the error with chapter number and text snippet, skip the chapter, and continue. Report all failures at the end. Never produce a corrupt M4B without warning.

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
Even though MVP uses only Piper, the TTS engine should be behind an abstract interface:
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
  - Core: `piper-tts`, `ebooklib`, `beautifulsoup4`, `pydub`, `mutagen`
  - System: `ffmpeg` (Homebrew)
  - Dev: `pytest`, `ruff`
- **No Rosetta.** All packages must install and run on ARM64 natively. If `platform.machine()` != `arm64`, warn the user.

---

## File Conventions

- Audio intermediate files: `{temp_dir}/chapter_{NNN}.wav` (zero-padded 3 digits)
- Final output default: `~/Downloads/{book_title}.m4b`
- Temp directory: Use `tempfile.mkdtemp()`, clean up on success, preserve on failure for debugging
- Config: No config file for MVP. All defaults are in `config.py`. CLI flags override defaults.

---

## What "Done" Looks Like for MVP

The MVP is complete when:
1. `python -m epub2audiobook path/to/book.epub` produces a valid M4B in ~/Downloads
2. The M4B plays in Apple Books with correct chapter markers
3. Metadata (title, author, cover) displays correctly in Apple Books
4. Audio is natural-sounding enough for a 30-minute commute listen without fatigue
5. A 300-page novel completes processing in under 60 minutes on M2
6. Errors during conversion are logged clearly and don't produce corrupt output
7. The tool runs without internet connectivity

---

## Future Roadmap (Do Not Build Yet)

- **v0.2:** Voice selection, quality presets (fast/standard/high), Spanish language
- **v0.3:** Parallel chapter processing (multiprocessing with spawn)
- **v0.4:** Calibre plugin wrapper (InterfaceActionBase, Qt UI)
- **v0.5:** MLX-Audio/Kokoro as alternative engine
- **v1.0:** Calibre plugin index publication, standalone macOS app (.app bundle)

---

## Reference Material

The following documents contain technical research used to make architecture decisions. They are context, not instructions — do not implement patterns from these documents unless they align with the decisions above.

- `docs/implementation_guide.pdf` — Comprehensive build guide (Piper, Calibre plugin architecture, M2 optimization)
- `docs/landscape_analysis.md` — Competitive landscape of ebook-to-audiobook tools
