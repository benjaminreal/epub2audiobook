# Product Specification — epub2audiobook v0.1.0

## 1. Overview

**epub2audiobook** is a Python CLI tool that converts ePub files into M4B audiobooks with chapter markers, using Piper TTS for speech synthesis. It runs entirely locally on macOS Apple Silicon with no cloud dependencies, no API costs, and no subscriptions.

**Version:** 0.1.0 (MVP)
**Platform:** macOS (Apple Silicon — M1/M2/M3+, ARM64 native)
**License:** MIT

### What v0.1.0 Does

- Accepts a single ePub file via CLI argument or native macOS file dialog
- Extracts text in spine order, preserving chapter structure
- Generates speech audio per chapter using Piper TTS (`en_US-lessac-medium` voice)
- Assembles chapters into a single M4B file with chapter markers
- Embeds metadata (title, author, cover art) for Apple Books display
- Saves output to `~/Downloads` or a user-specified path

### What v0.1.0 Does Not Do

- Batch processing (multiple books)
- Voice selection or quality presets
- Resume/checkpoint for interrupted conversions
- Parallel chapter processing
- Calibre plugin integration
- Non-English language support
- Speed/pitch controls
- Cloud TTS fallback
- Voice cloning

---

## 2. Pipeline Architecture

### 2.1 Stage 1: Input Handling

**Input:** ePub file path from CLI argument, or user selection via native macOS file dialog.

**Processing:**
1. If a CLI argument is provided, use it as the ePub path.
2. If no argument is given, invoke a native macOS file dialog via `osascript` (AppleScript subprocess). The dialog filters for `.epub` files using the UTI `org.idpf.epub-container`. If the user cancels the dialog, print usage help and exit.
3. Validate the path:
   - File exists on disk.
   - File has `.epub` extension.
   - File is a valid ZIP archive (ePub files are ZIP containers).
   - File is not DRM-protected: open the ZIP and check for the presence of `META-INF/encryption.xml`. If this file exists and contains `<EncryptedData>` elements, the ePub is DRM-protected.

**Output:** A validated `Path` object pointing to the ePub file.

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| File not found | `Path.exists()` returns False | Print error with provided path, exit code 1 |
| Not an .epub file | Extension check | Print error suggesting correct file type, exit code 1 |
| Invalid ZIP/corrupt file | `zipfile.is_zipfile()` returns False | Print error, exit code 1 |
| DRM-protected | `encryption.xml` contains `EncryptedData` | Print error explaining DRM cannot be processed, exit code 1 |
| File dialog cancelled | osascript returns non-zero or empty stdout | Print usage help, exit code 1 |

**Dependencies:** None (stdlib `zipfile`, `subprocess`, `pathlib`).

---

### 2.2 Stage 2: Metadata Extraction

**Input:** Validated ePub `Path` from Stage 1.

**Processing:**
1. Open the ePub using `ebooklib.epub.read_epub()`.
2. Extract Dublin Core metadata:
   - **Title:** `book.get_metadata('DC', 'title')` → first result's text content. Fallback: derive from filename (strip extension, replace underscores/hyphens with spaces).
   - **Author:** `book.get_metadata('DC', 'creator')` → first result's text content. Fallback: `"Unknown Author"`.
   - **Language:** `book.get_metadata('DC', 'language')` → first result's text content. Fallback: `"en"`.
3. Extract cover image:
   - Check `book.get_metadata('OPF', 'cover')` for a cover item ID.
   - Retrieve the cover image item via `book.get_item_with_id()`.
   - If no OPF cover metadata, scan manifest items for an item with `properties="cover-image"` or a media type starting with `image/` and a name containing "cover".
   - Fallback: no cover (skip cover embedding in Stage 6).

**Output:** A `BookMetadata` dataclass containing `title: str`, `author: str`, `language: str`, `cover_image: bytes | None`, `cover_format: str | None` (e.g., `"jpeg"`, `"png"`).

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| ebooklib cannot parse ePub | Exception from `read_epub()` | Log error with details, exit code 3 |
| No title in metadata | Empty result from DC query | Use filename-derived title, log warning |
| No author in metadata | Empty result from DC query | Use "Unknown Author", log warning |
| Cover image corrupt/unreadable | Exception reading item content | Skip cover, log warning, continue |

**Dependencies:** `ebooklib`.

---

### 2.3 Stage 3: Text Extraction

**Input:** The `EpubBook` object from Stage 2.

**Processing:**
1. Iterate `book.spine` to get items in reading order. Each entry is `(item_id, linear)`. Process only items where `linear == 'yes'` (or is the default).
2. For each spine item, retrieve the `EpubHtml` item via `book.get_item_with_id(item_id)`.
3. Parse the HTML content with BeautifulSoup4. Extract visible text, preserving paragraph boundaries as line breaks.
4. **Chapter title detection** (in priority order):
   a. Match the spine item's href against `book.toc` entries. If a TOC entry points to this item, use its title.
   b. Extract the first `<h1>`, `<h2>`, or `<h3>` element's text from the HTML.
   c. Fall back to `"Chapter {N}"` where N is the 1-based spine index.
5. **Flat ePub handling:** If the spine contains 3 or fewer items and the total text exceeds 20,000 characters, treat the ePub as flat. In this case, split the content of each spine item at `<h1>` and `<h2>` heading tags to create synthetic chapter boundaries. Each heading becomes the title of the following chapter. Text before the first heading becomes a "Prologue" or "Introduction" chapter.
6. **Short chapter filtering:** Chapters with fewer than 50 characters of text after preprocessing are flagged as "short" but still included. They will produce brief audio segments. No merging with adjacent chapters in MVP.

**Output:** An ordered list of `Chapter` dataclasses: `{index: int, title: str, text: str, source_href: str}`.

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| Spine item not found | `get_item_with_id()` returns None | Log warning with item ID, skip this item |
| HTML parsing fails | BeautifulSoup exception | Log warning, skip this chapter, continue |
| Zero chapters extracted | Empty chapter list after processing | Log error, exit code 3 |
| No text in chapter | Extracted text is empty/whitespace-only | Log warning, include with empty text (will produce silence or skip in TTS) |

**Dependencies:** `ebooklib`, `beautifulsoup4`.

---

### 2.4 Stage 4: Text Preprocessing

**Input:** Raw text from each `Chapter` object (Stage 3).

**Processing:** Apply these 9 rules sequentially, in order:

1. **HTML tag stripping** — Remove any residual HTML tags. Convert `<p>`, `<br>`, `<div>` boundaries to newlines to preserve sentence structure.

2. **HTML entity decoding** — Decode all named and numeric HTML entities: `&amp;` → `&`, `&mdash;` → ` — `, `&nbsp;` → space, `&#8220;` → `"`, etc. Use Python's `html.unescape()`.

3. **Unicode normalization** — Apply NFC normalization. Replace:
   - Smart quotes (`\u201c` `\u201d` `\u2018` `\u2019`) → ASCII `"` and `'`
   - Em-dash (`\u2014`) → ` -- `
   - En-dash (`\u2013`) → `-`
   - Horizontal ellipsis (`\u2026`) → `...`
   - Common ligatures (`fi` → `fi`, `fl` → `fl`)

4. **Abbreviation expansion** — Replace common abbreviations with spoken forms:
   - `Mr.` → `Mister`, `Mrs.` → `Missus`, `Ms.` → `Mizz`
   - `Dr.` → `Doctor`, `Prof.` → `Professor`
   - `St.` → `Saint` (when followed by a name; `Street` in addresses — MVP: always `Saint`)
   - `etc.` → `etcetera`, `e.g.` → `for example`, `i.e.` → `that is`
   - `vs.` → `versus`, `Jr.` → `Junior`, `Sr.` → `Senior`

5. **URL and email removal** — Strip URLs matching `https?://\S+` and emails matching `\S+@\S+\.\S+`. Replace each with a single space.

6. **Footnote marker removal** — Remove superscript footnote markers: digits or symbols enclosed in `<sup>` tags (caught by HTML stripping) and standalone bracketed references like `[1]`, `[2]`, `[*]`.

7. **Control character removal** — Strip all Unicode control characters (U+0000–U+001F) except newline (`\n`) and tab (`\t`).

8. **Whitespace normalization** — Collapse runs of whitespace (multiple spaces, tabs) into single spaces. Normalize multiple consecutive newlines into double newlines (paragraph breaks). Strip leading/trailing whitespace from each paragraph.

9. **Sentence boundary preservation** — Ensure that paragraph-ending text has appropriate punctuation. Insert a period after paragraphs that end with alphanumeric characters without terminal punctuation. This improves Piper's prosody at paragraph boundaries.

**Output:** Cleaned text string for each chapter, ready for TTS.

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| Text becomes empty after preprocessing | Length check | Log warning, mark chapter as empty |
| Regex error in preprocessing | Exception from `re` operations | Log error with rule name, return text processed up to the failing rule |

**Dependencies:** None (stdlib `re`, `html`, `unicodedata`).

---

### 2.5 Stage 5: TTS Generation

**Input:** Preprocessed text for each chapter (Stage 4), chapter metadata (title, index).

**Processing:**
1. **Dependency check:** Verify Piper TTS is available. Check if the voice model (`en_US-lessac-medium`) is downloaded. If not, auto-download on first run (~50MB). Log a message: `"Downloading voice model en_US-lessac-medium (first run only)..."`.
2. **Temp directory:** Create a temporary directory via `tempfile.mkdtemp(prefix="epub2audiobook_")`.
3. **Sequential processing:** For each chapter in order:
   a. If chapter text is empty, create a 1-second silent WAV file for that chapter (preserves chapter marker in final M4B).
   b. If chapter text exceeds 10,000 characters, split at sentence boundaries (`.` `!` `?` followed by whitespace) into chunks under 10,000 characters each. Generate audio for each chunk separately, then concatenate the chunk WAVs into a single chapter WAV using PyDub.
   c. Generate WAV audio using the Piper Python library: pass text to `piper.PiperVoice`, receive raw audio data, write to `chapter_NNN.wav` (zero-padded 3 digits).
   d. Release the WAV audio from memory after writing to disk (memory discipline).
4. **Progress reporting:** After each chapter completes, log:
   ```
   [3/24] "The Journey Begins"... 12:34 elapsed, ~38:00 remaining
   ```
   ETA is calculated from average time per chapter after the first chapter completes.

**Output:** Ordered list of WAV file paths in the temp directory: `chapter_001.wav`, `chapter_002.wav`, etc.

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| Piper not installed | ImportError on `import piper` | Print install instructions, exit code 2 |
| Model not found and download fails | Exception during model download | Print error with manual download URL, exit code 2 |
| TTS fails for a chapter | Exception from Piper | Log error with chapter number and text snippet (first 100 chars), skip chapter, continue. Report all failures at end. |
| Disk full during WAV write | IOError/OSError | Log error, clean up partial files, exit code 3 |
| Chunk concatenation fails | PyDub exception | Log error with chapter number, skip chapter, continue |

**Dependencies:** `piper-tts`, `pydub`.

---

### 2.6 Stage 6: Audio Assembly

**Input:** List of chapter WAV paths (Stage 5), `BookMetadata` (Stage 2), chapter titles, cover image bytes.

**Processing — Phase 1: FFmpeg (Audio + Chapters):**
1. Calculate chapter timestamps by reading each WAV file's duration via PyDub (`len()` returns milliseconds). Build a cumulative timeline:
   - Chapter 1: START=0, END=duration_1
   - Chapter 2: START=duration_1, END=duration_1 + duration_2
   - etc.
2. Generate an FFMETADATA file:
   ```
   ;FFMETADATA1
   title=Book Title
   artist=Author Name

   [CHAPTER]
   TIMEBASE=1/1000
   START=0
   END=180000
   title=Chapter 1

   [CHAPTER]
   TIMEBASE=1/1000
   START=180000
   END=420000
   title=Chapter 2
   ```
3. Generate an FFmpeg concat list file:
   ```
   file '/path/to/chapter_001.wav'
   file '/path/to/chapter_002.wav'
   ```
4. Run FFmpeg to concatenate, encode, and embed chapters:
   ```
   ffmpeg -f concat -safe 0 -i concat_list.txt \
          -i metadata.txt -map_metadata 1 \
          -c:a aac -b:a 64k -ac 1 -ar 44100 \
          -movflags +faststart \
          output.m4b
   ```

**Processing — Phase 2: Mutagen (Metadata + Cover):**
1. Open the M4B file with `mutagen.mp4.MP4`.
2. Set metadata tags:
   - `\xa9nam` → title
   - `\xa9ART` → author
   - `\xa9alb` → title (album = book title)
   - `aART` → `"Piper TTS (lessac)"` (album artist = narrator)
   - `stik` → `[2]` (media kind: Audiobook)
3. If cover image is available, embed via `covr` tag using `MP4Cover` with the appropriate format (`FORMAT_JPEG` or `FORMAT_PNG`).
4. Save the MP4 tags. Mutagen preserves FFmpeg's chapter metadata when saving.

**Output:** Complete M4B file at a temporary path, ready for final placement.

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| FFmpeg not installed | `shutil.which("ffmpeg")` returns None | Print install instructions (`brew install ffmpeg`), exit code 2 |
| FFmpeg encoding fails | Non-zero exit code from subprocess | Log FFmpeg stderr, exit code 3 |
| Mutagen cannot open M4B | Exception from `MP4()` | Log error, exit code 3. M4B may still be playable without metadata. |
| Cover image format unsupported | Format is not JPEG or PNG | Log warning, skip cover embedding, continue |

**Dependencies:** `pydub` (WAV duration), `mutagen` (metadata), FFmpeg (system).

---

### 2.7 Stage 7: Output Delivery

**Input:** Complete M4B file from Stage 6, target output path.

**Processing:**
1. Determine output path:
   - If `--output` flag provided, use that path.
   - Otherwise, default to `~/Downloads/{sanitized_title}.m4b`.
   - Sanitize title for filename: remove characters not in `[a-zA-Z0-9 _-]`, replace spaces with underscores, truncate to 200 characters.
2. If the output path already exists, log a warning: `"Overwriting existing file: {path}"`.
3. Move (or copy) the M4B from the temp directory to the output path.
4. Clean up the temp directory on success (delete all intermediate WAV files, concat list, metadata file).
5. On failure (any stage raised an exception), preserve the temp directory and log its path for debugging.
6. Print a summary to stdout:
   ```
   Audiobook created successfully!
     Output:    ~/Downloads/The_Great_Gatsby.m4b
     Size:      142.3 MB
     Duration:  4:32:15
     Chapters:  12
     Time:      47:23
   ```

**Output:** M4B file at the target path. Exit code 0.

**Error Conditions:**
| Condition | Detection | Behavior |
|---|---|---|
| Output directory doesn't exist | `Path.parent.exists()` check | Create parent directories, log info |
| Insufficient disk space for copy | IOError during file move | Log error with required space, exit code 3 |
| Permission denied on output path | PermissionError | Log error suggesting alternative path, exit code 3 |

**Dependencies:** None (stdlib `shutil`, `pathlib`).

---

## 3. Edge Cases and Failure Modes

| # | Edge Case | Detection Method | User-Facing Message | Recovery Behavior |
|---|---|---|---|---|
| 1 | **Flat ePub** (no chapter structure, single HTML document) | Spine has ≤3 items and total text >20K chars | `"No chapter structure detected. Splitting on headings."` | Split on `<h1>`/`<h2>` tags. If no headings found, treat entire book as a single chapter titled with the book title. |
| 2 | **Very short chapters** (title pages, copyright, dedication) | Chapter text <50 characters after preprocessing | `"Short chapter detected: '{title}' (N chars)"` | Include as-is. Will produce a brief audio segment. No merging. |
| 3 | **Missing metadata** (no author, no cover, no title) | Empty results from Dublin Core queries | `"Warning: No {field} found in ePub metadata. Using default."` | Use fallbacks: filename for title, "Unknown Author" for author, skip cover embedding. |
| 4 | **TTS-breaking characters** (unmatched quotes, unusual Unicode symbols) | Piper raises exception or produces garbled audio | `"Warning: TTS failed for chapter {N}. Skipping."` | Log the error with a text snippet. Skip the chapter. Report all skipped chapters at the end. |
| 5 | **DRM-protected ePub** | `META-INF/encryption.xml` exists and contains `<EncryptedData>` elements | `"Error: This ePub is DRM-protected and cannot be converted. Please use a DRM-free ePub."` | Refuse to process. Exit code 1. |
| 6 | **FFmpeg not installed** | `shutil.which("ffmpeg")` returns None | `"Error: FFmpeg is required but not installed. Install with: brew install ffmpeg"` | Exit code 2. Do not attempt conversion. |
| 7 | **Piper model not downloaded** (first run) | Model file not found in expected directory | `"Downloading voice model en_US-lessac-medium (~50MB, first run only)..."` | Auto-download the model. If download fails (no internet), print manual download URL and exit code 2. |
| 8 | **Insufficient disk space** | Check available space before TTS generation: estimate ~10MB per chapter (WAV) + final M4B size | `"Error: Insufficient disk space. Need approximately {N} GB, {M} GB available."` | Exit code 3 before starting TTS generation. |
| 9 | **Very large books** (1000+ pages, 50+ chapters) | Chapter count or total text length exceeds threshold | `"Large book detected ({N} chapters). This may take a while."` | Process sequentially as normal. Memory discipline (process one chapter, write to disk, release). No special handling beyond the warning and accurate ETA. |

---

## 4. CLI Interface Design

### 4.1 Command Syntax

```
python -m epub2audiobook [epub_path] [OPTIONS]
```

### 4.2 Arguments and Flags

| Argument/Flag | Type | Required | Default | Description |
|---|---|---|---|---|
| `epub_path` | positional | No | — | Path to the .epub file. If omitted, opens a native macOS file dialog. |
| `--output`, `-o` | option | No | `~/Downloads/{title}.m4b` | Output path for the M4B file. |
| `--verbose`, `-v` | flag | No | off | Enable debug-level logging to stderr. |
| `--version` | flag | No | — | Print version number and exit. |

### 4.3 Example Invocations

```bash
# Basic usage — output goes to ~/Downloads/
python -m epub2audiobook book.epub

# Specify output path
python -m epub2audiobook book.epub --output ~/Audiobooks/book.m4b

# Open file picker (no path argument)
python -m epub2audiobook

# Verbose mode for debugging
python -m epub2audiobook book.epub -v
```

### 4.4 Progress Output Format

During conversion, the tool prints progress to stderr:

```
epub2audiobook v0.1.0
Loading: The Great Gatsby.epub
Author:  F. Scott Fitzgerald
Chapters: 12 detected

[1/12]  "Chapter 1"... done (3:45)
[2/12]  "Chapter 2"... done (4:12)    6:30 elapsed, ~25:00 remaining
[3/12]  "Chapter 3"... processing...
```

After completion:
```
Audiobook created successfully!
  Output:    ~/Downloads/The_Great_Gatsby.m4b
  Size:      142.3 MB
  Duration:  4:32:15
  Chapters:  12
  Time:      47:23
```

If chapters were skipped:
```
Warning: 2 chapters skipped due to TTS errors:
  - Chapter 7: "In the early morning the sun threw my shadow..." (TTS generation failed)
  - Chapter 11: "" (empty chapter)
```

### 4.5 Exit Codes

| Code | Meaning | Examples |
|---|---|---|
| 0 | Success | Audiobook created and saved |
| 1 | Input error | File not found, invalid ePub, DRM-protected, dialog cancelled |
| 2 | Dependency error | FFmpeg not installed, Piper model missing and download failed |
| 3 | Processing error | TTS failed for all chapters, assembly failed, disk full |

### 4.6 Error Output Format

All errors and warnings go to stderr, prefixed:
```
ERROR: File not found: /path/to/book.epub
WARNING: No cover image found in ePub metadata.
```

Debug-level messages (visible with `--verbose`) include module name and timestamp:
```
DEBUG [parser] 2026-04-03 14:23:01 - Spine item 3: content.xhtml (2,450 chars)
DEBUG [tts]    2026-04-03 14:23:05 - Generating audio for chapter 3 (2,450 chars, 1 chunk)
```

---

## 5. Module Interface Contracts

### 5.1 config.py — Constants and Defaults

```python
"""Application constants and default configuration values."""

# Version
VERSION: str = "0.1.0"

# TTS
DEFAULT_VOICE: str = "en_US-lessac-medium"
MAX_TTS_CHUNK_CHARS: int = 10_000

# Audio encoding
DEFAULT_BITRATE: str = "64k"
DEFAULT_SAMPLE_RATE: int = 44_100
DEFAULT_CHANNELS: int = 1  # mono

# Output
DEFAULT_OUTPUT_DIR: Path = Path.home() / "Downloads"
MAX_FILENAME_LENGTH: int = 200

# Chapter detection
MIN_CHAPTER_CHARS: int = 50
FLAT_EPUB_MAX_SPINE_ITEMS: int = 3
FLAT_EPUB_MIN_TEXT_LENGTH: int = 20_000

# Logging
LOG_FORMAT: str = "%(levelname)s [%(name)s] %(asctime)s - %(message)s"
```

No functions. Import-only module.

---

### 5.2 utils.py — Logging, Progress, File Helpers

```python
def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure root logger and return the application logger.

    Args:
        verbose: If True, set level to DEBUG. Otherwise, INFO.

    Returns:
        Configured Logger instance for 'epub2audiobook'.
    """

def check_ffmpeg() -> bool:
    """Check if FFmpeg is available on the system PATH.

    Returns:
        True if FFmpeg is found.

    Raises:
        DependencyError: If FFmpeg is not found. Message includes
            install instructions ('brew install ffmpeg').
    """

def check_disk_space(path: Path, required_bytes: int) -> bool:
    """Check if sufficient disk space is available.

    Args:
        path: Directory to check.
        required_bytes: Minimum bytes required.

    Returns:
        True if sufficient space is available.

    Raises:
        DiskSpaceError: If insufficient space. Message includes
            required and available amounts.
    """

def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize a string for use as a filename.

    Removes characters not in [a-zA-Z0-9 _-], replaces spaces with
    underscores, truncates to max_length.

    Args:
        name: Raw string (e.g., book title).
        max_length: Maximum filename length.

    Returns:
        Sanitized filename string (without extension).
    """

def format_duration(seconds: float) -> str:
    """Format a duration in seconds to H:MM:SS or M:SS.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like '4:32:15' or '3:45'.
    """

def estimate_audio_size(total_chars: int) -> int:
    """Estimate the total disk space needed for audio generation.

    Estimates WAV intermediate files and final M4B size based on
    character count and average speaking rate.

    Args:
        total_chars: Total character count across all chapters.

    Returns:
        Estimated bytes required (WAVs + final M4B).
    """
```

```python
class ProgressTracker:
    """Tracks and displays conversion progress.

    Attributes:
        total_chapters: Total number of chapters to process.
    """

    def __init__(self, total_chapters: int) -> None:
        """Initialize the tracker.

        Args:
            total_chapters: Total number of chapters.
        """

    def start_chapter(self, index: int, title: str) -> None:
        """Signal that a chapter has started processing.

        Args:
            index: 1-based chapter index.
            title: Chapter title.
        """

    def finish_chapter(self, index: int) -> None:
        """Signal that a chapter has finished processing.

        Prints progress line with elapsed time and ETA (after first
        chapter completes).

        Args:
            index: 1-based chapter index.
        """

    def get_elapsed(self) -> float:
        """Return elapsed time in seconds since first start_chapter call."""

    def get_eta(self) -> float | None:
        """Return estimated seconds remaining, or None if not enough data."""
```

```python
class DependencyError(Exception):
    """Raised when a required system dependency is missing."""

class DiskSpaceError(Exception):
    """Raised when insufficient disk space is available."""
```

---

### 5.3 cli.py — Entry Point and Argument Parsing

```python
def main() -> int:
    """Application entry point.

    Parses arguments, runs the conversion pipeline, handles top-level
    errors, and returns an exit code.

    Returns:
        Exit code: 0 (success), 1 (input error), 2 (dependency error),
        3 (processing error).
    """

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list. If None, uses sys.argv[1:].

    Returns:
        Namespace with attributes: epub_path (Path | None),
        output (Path | None), verbose (bool).
    """

def validate_input(path: Path) -> Path:
    """Validate that the given path is a processable ePub file.

    Checks: file exists, has .epub extension, is a valid ZIP archive,
    is not DRM-protected.

    Args:
        path: Path to validate.

    Returns:
        The validated Path.

    Raises:
        InputError: If any validation check fails. Message describes
            the specific issue.
    """

def open_file_dialog() -> Path | None:
    """Open a native macOS file dialog to select an ePub file.

    Uses osascript to invoke a Cocoa file dialog filtered to
    .epub files (UTI: org.idpf.epub-container).

    Returns:
        Path to the selected file, or None if the user cancelled.
    """
```

```python
class InputError(Exception):
    """Raised for input validation failures."""
```

---

### 5.4 parser.py — ePub Extraction

```python
@dataclass
class BookMetadata:
    """Metadata extracted from an ePub file.

    Attributes:
        title: Book title. Never empty (fallback: filename).
        author: Author name. Fallback: 'Unknown Author'.
        language: Language code (e.g., 'en'). Fallback: 'en'.
        cover_image: Raw bytes of the cover image, or None.
        cover_format: Image format ('jpeg' or 'png'), or None.
    """
    title: str
    author: str
    language: str
    cover_image: bytes | None
    cover_format: str | None


@dataclass
class Chapter:
    """A single chapter extracted from an ePub.

    Attributes:
        index: 0-based chapter index.
        title: Chapter title (from TOC, heading, or generated).
        text: Raw extracted text (before preprocessing).
        source_href: The ePub spine item href this chapter came from.
    """
    index: int
    title: str
    text: str
    source_href: str


def parse_epub(epub_path: Path) -> tuple[BookMetadata, list[Chapter]]:
    """Parse an ePub file and extract metadata and chapters.

    Reads the ePub in spine order. Detects flat ePubs and splits on
    headings if necessary. Extracts Dublin Core metadata and cover image.

    Args:
        epub_path: Path to a validated ePub file.

    Returns:
        Tuple of (BookMetadata, list of Chapters in reading order).

    Raises:
        ParsingError: If the ePub cannot be parsed or yields zero chapters.
    """

def extract_cover(book: ebooklib.epub.EpubBook) -> tuple[bytes | None, str | None]:
    """Extract the cover image from an ePub book object.

    Tries OPF cover metadata first, then scans manifest for cover
    candidates.

    Args:
        book: An opened EpubBook instance.

    Returns:
        Tuple of (image bytes, format string) or (None, None) if no
        cover found.
    """
```

```python
class ParsingError(Exception):
    """Raised when ePub parsing fails."""
```

---

### 5.5 preprocessor.py — Text Cleaning

```python
def preprocess_text(text: str) -> str:
    """Run the full text preprocessing pipeline.

    Applies all cleaning rules in sequence: HTML stripping, entity
    decoding, Unicode normalization, abbreviation expansion, URL removal,
    footnote removal, control character removal, whitespace normalization,
    sentence boundary preservation.

    Args:
        text: Raw chapter text from the parser.

    Returns:
        Cleaned text ready for TTS.
    """

def strip_html_tags(text: str) -> str:
    """Remove HTML tags, converting block elements to newlines."""

def decode_html_entities(text: str) -> str:
    """Decode HTML entities (named and numeric) to characters."""

def normalize_unicode(text: str) -> str:
    """NFC normalize and replace smart quotes, dashes, ligatures."""

def expand_abbreviations(text: str) -> str:
    """Expand common abbreviations to spoken forms."""

def remove_urls_and_emails(text: str) -> str:
    """Remove URLs and email addresses."""

def remove_footnote_markers(text: str) -> str:
    """Remove bracketed footnote references like [1], [*]."""

def remove_control_characters(text: str) -> str:
    """Remove Unicode control characters except newline and tab."""

def normalize_whitespace(text: str) -> str:
    """Collapse whitespace runs, normalize paragraph breaks."""

def preserve_sentence_boundaries(text: str) -> str:
    """Ensure paragraphs end with terminal punctuation."""
```

No custom exceptions. All functions are pure text transformations that cannot fail (they return the input text unchanged on edge cases).

---

### 5.6 tts_engine.py — TTS Abstraction and Piper Implementation

```python
from abc import ABC, abstractmethod


class TTSEngine(ABC):
    """Abstract base class for text-to-speech engines."""

    @abstractmethod
    def generate(self, text: str, output_path: Path) -> Path:
        """Generate audio from text and save to a WAV file.

        Args:
            text: The text to synthesize.
            output_path: Path where the WAV file should be written.

        Returns:
            The output_path on success.

        Raises:
            TTSError: If audio generation fails.
        """

    @abstractmethod
    def get_voice_name(self) -> str:
        """Return the human-readable name of the current voice.

        Returns:
            Voice name string (e.g., 'Piper TTS (lessac)').
        """


class PiperTTSEngine(TTSEngine):
    """Piper TTS engine implementation.

    Uses the piper-tts Python library. Auto-downloads the voice model
    on first use.
    """

    def __init__(self, voice: str = "en_US-lessac-medium") -> None:
        """Initialize the Piper TTS engine.

        Args:
            voice: Piper voice model name.

        Raises:
            DependencyError: If piper-tts is not installed.
            TTSError: If the voice model cannot be loaded or downloaded.
        """

    def generate(self, text: str, output_path: Path) -> Path:
        """Generate audio from text using Piper TTS.

        For texts exceeding MAX_TTS_CHUNK_CHARS, splits at sentence
        boundaries and concatenates the results.

        Args:
            text: The text to synthesize.
            output_path: Path for the output WAV file.

        Returns:
            The output_path.

        Raises:
            TTSError: If Piper fails to generate audio.
        """

    def get_voice_name(self) -> str:
        """Return 'Piper TTS (lessac)'."""

    def generate_silence(self, output_path: Path, duration_ms: int = 1000) -> Path:
        """Generate a silent WAV file.

        Used for empty chapters to preserve chapter markers.

        Args:
            output_path: Path for the output WAV file.
            duration_ms: Duration of silence in milliseconds.

        Returns:
            The output_path.
        """
```

```python
class TTSError(Exception):
    """Raised when TTS generation fails."""
```

---

### 5.7 assembler.py — Audio Assembly and Metadata Embedding

```python
def assemble_audiobook(
    chapter_wav_paths: list[Path],
    metadata: BookMetadata,
    chapter_titles: list[str],
    output_path: Path,
) -> Path:
    """Assemble chapter WAV files into a single M4B audiobook.

    Runs the two-phase assembly:
    1. FFmpeg: concatenate WAVs, encode to AAC, embed chapter markers.
    2. Mutagen: embed metadata tags and cover art.

    Args:
        chapter_wav_paths: Ordered list of WAV file paths.
        metadata: Book metadata (title, author, cover).
        chapter_titles: Ordered list of chapter title strings
            (must match length of chapter_wav_paths).
        output_path: Final output path for the M4B file.

    Returns:
        The output_path on success.

    Raises:
        DependencyError: If FFmpeg is not available.
        AssemblyError: If FFmpeg encoding or Mutagen tagging fails.
    """

def create_ffmetadata(
    chapter_wav_paths: list[Path],
    chapter_titles: list[str],
    title: str,
    author: str,
) -> str:
    """Generate an FFMETADATA1 text file content.

    Reads each WAV file's duration using PyDub to calculate chapter
    timestamps.

    Args:
        chapter_wav_paths: Ordered list of WAV file paths.
        chapter_titles: Ordered list of chapter titles.
        title: Book title for the file-level metadata.
        author: Author name for the file-level metadata.

    Returns:
        FFMETADATA file content as a string.
    """

def encode_m4b(
    concat_list_path: Path,
    metadata_path: Path,
    output_path: Path,
) -> Path:
    """Run FFmpeg to concatenate WAVs and encode to M4B.

    Args:
        concat_list_path: Path to the FFmpeg concat list file.
        metadata_path: Path to the FFMETADATA file.
        output_path: Path for the output M4B file.

    Returns:
        The output_path.

    Raises:
        AssemblyError: If FFmpeg returns a non-zero exit code.
            Message includes FFmpeg's stderr output.
    """

def embed_metadata(
    m4b_path: Path,
    metadata: BookMetadata,
    narrator: str,
) -> None:
    """Embed metadata and cover art into an M4B file using Mutagen.

    Sets iTunes-compatible tags: title, artist, album, album artist,
    media kind (Audiobook), and cover art.

    Args:
        m4b_path: Path to the M4B file.
        metadata: Book metadata.
        narrator: Narrator name for the album artist tag.

    Raises:
        AssemblyError: If Mutagen cannot open or save the file.
    """
```

```python
class AssemblyError(Exception):
    """Raised when audio assembly fails."""
```

---

## 6. Dependency Checklist

### Direct Python Dependencies (5 packages)

| Package | Version Constraint | Purpose | Install | ARM64 Status | If Missing |
|---|---|---|---|---|---|
| `piper-tts` | >=1.4.0 | Text-to-speech synthesis engine | `pip install piper-tts` | Native wheel (1.4.1+) | `"Install piper-tts: pip install piper-tts"` → exit code 2 |
| `ebooklib` | >=0.18 | ePub file parsing and spine/metadata access | `pip install ebooklib` | Pure Python | `"Install ebooklib: pip install ebooklib"` → exit code 2 |
| `beautifulsoup4` | >=4.12 | HTML content extraction from ePub documents | `pip install beautifulsoup4` | Pure Python | `"Install beautifulsoup4: pip install beautifulsoup4"` → exit code 2 |
| `pydub` | >=0.25 | WAV file manipulation and duration reading | `pip install pydub` | Pure Python | `"Install pydub: pip install pydub"` → exit code 2 |
| `mutagen` | >=1.47 | M4B/MP4 metadata tagging and cover art embedding | `pip install mutagen` | Pure Python | `"Install mutagen: pip install mutagen"` → exit code 2 |

### System Dependencies (1 package)

| Package | Version Constraint | Purpose | Install | ARM64 Status | If Missing |
|---|---|---|---|---|---|
| `ffmpeg` | >=5.0 | Audio encoding (WAV → AAC) and chapter marker embedding | `brew install ffmpeg` | Native (Homebrew) | `"FFmpeg is required but not installed. Install with: brew install ffmpeg"` → exit code 2 |

### Key Transitive Dependencies (for awareness)

| Package | Pulled In By | Notes |
|---|---|---|
| `onnxruntime` | `piper-tts` | Large binary (~200MB). ARM64 native wheel required. |
| `numpy` | `onnxruntime` | Numerical computing. ARM64 native wheel available. |
| `piper-phonemize` | `piper-tts` | Text-to-phoneme conversion for Piper. |
| `lxml` | `ebooklib` | XML/HTML parsing. C extension with ARM64 wheel available. |

### Dev Dependencies (not required at runtime)

| Package | Purpose | Install |
|---|---|---|
| `pytest` | Unit and integration testing | `pip install pytest` |
| `ruff` | Linting and formatting | `pip install ruff` |

---

## 7. Acceptance Criteria

**AC-01:** Given a valid ePub with 10+ chapters, when running `python -m epub2audiobook book.epub`, then an M4B file appears in `~/Downloads/` with a filename derived from the book title, and the file is playable in Apple Books.

**AC-02:** Given the M4B produced by AC-01, when opening it in Apple Books, then the chapter list displays the correct number of chapters with titles matching those detected from the ePub's table of contents or headings.

**AC-03:** Given the M4B produced by AC-01, when viewing its metadata in Apple Books or Finder, then the title, author, and cover art (if present in the source ePub) are displayed correctly.

**AC-04:** Given a 300-page novel ePub, when running on an Apple M2 Mac, then the conversion completes in under 60 minutes from start to finish.

**AC-05:** Given a system without FFmpeg installed, when running `python -m epub2audiobook book.epub`, then the tool prints an error message containing `brew install ffmpeg` and exits with code 2 without creating any output files.

**AC-06:** Given a DRM-protected ePub file, when running `python -m epub2audiobook drm_book.epub`, then the tool prints an error message stating the file is DRM-protected and exits with code 1.

**AC-07:** Given an ePub with no author metadata and no cover image, when running `python -m epub2audiobook book.epub`, then the tool produces a valid M4B with "Unknown Author" as the author and no cover art, without crashing.

**AC-08:** Given that the Piper voice model has been downloaded on a previous run, when running `python -m epub2audiobook book.epub` with no internet connection, then the conversion completes successfully without attempting any network requests.

**AC-09:** Given an ePub with a flat structure (single HTML document containing the entire book with `<h1>` headings), when running `python -m epub2audiobook flat_book.epub`, then the tool splits the content at headings and produces an M4B with chapter markers corresponding to each heading.

**AC-10:** Given a multi-chapter ePub, when conversion is in progress, then stderr displays a progress line for each chapter showing the chapter number, total count, chapter title, elapsed time, and estimated time remaining (after the first chapter completes).
