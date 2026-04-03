# Product Definition Prompt — epub2audiobook

Use this prompt with Claude Code to refine the product specification and begin development.

---

## Prompt

```
You are a senior Python developer building a local ePub-to-audiobook converter for macOS Apple Silicon. Your job is to produce a detailed product specification and then implement it incrementally.

Read the CLAUDE.md file in this project root first. It contains locked architecture decisions, MVP scope, development principles, and coding standards. Do not deviate from those decisions without explicit instruction from me.

## Context

I'm building an open-source tool called epub2audiobook that converts ePub files into M4B audiobooks with chapter markers using Piper TTS, running entirely locally on Apple Silicon Macs. No cloud dependencies.

The MVP is deliberately narrow: one book at a time, one TTS engine (Piper), one voice (en_US-lessac-medium), English only, CLI interface with optional file picker, output to ~/Downloads.

## Task 1: Product Specification

Before writing any code, produce a product specification document (product_spec.md) that covers:

### 1.1 Pipeline Architecture
Define the exact data flow from ePub input to M4B output. For each stage:
- Input format and source
- Processing logic (what happens, not how to code it)
- Output format and destination
- Error conditions and how they're handled
- Dependencies required

Stages:
1. **Input handling** — Accept ePub path via CLI arg or file picker dialog. Validate file exists and is valid ePub.
2. **Metadata extraction** — Pull title, author, language, cover image from ePub Dublin Core metadata.
3. **Text extraction** — Parse ePub in spine order. Extract clean text per chapter. Identify chapter boundaries and titles.
4. **Text preprocessing** — Clean extracted text for TTS consumption. Handle Unicode, abbreviations, URLs, footnotes, whitespace.
5. **TTS generation** — Convert each chapter's text to WAV audio using Piper TTS.
6. **Audio assembly** — Combine chapter WAVs into single M4B with chapter markers, embedded metadata, and cover art.
7. **Output** — Save final M4B to Downloads folder or user-specified path. Report results.

### 1.2 Edge Cases and Failure Modes
Enumerate specific edge cases the MVP must handle:
- ePub with no chapter structure (flat HTML)
- ePub with very short "chapters" (title pages, copyright pages, dedication)
- Missing metadata fields (no author, no cover)
- Characters that break Piper TTS
- ePub files with DRM (detect and refuse gracefully)
- FFmpeg not installed
- Piper model not downloaded
- Disk space insufficient for audio generation
- Very large books (1000+ pages) — memory implications

For each edge case, specify: detection method, user-facing message, and recovery behavior.

### 1.3 CLI Interface Design
Define the command-line interface:
- Command syntax and arguments
- Default behaviors (output path, voice, bitrate)
- Progress output format (what the user sees during a 45-minute conversion)
- Exit codes and error output format

Example invocations:
```
# Basic usage
python -m epub2audiobook book.epub

# Specify output path
python -m epub2audiobook book.epub --output ~/Audiobooks/book.m4b

# Use file picker (no path argument)
python -m epub2audiobook
```

### 1.4 Dependency Checklist
List every dependency with:
- Package name and version constraint
- Why it's needed (one sentence)
- Install method (pip vs. brew vs. system)
- ARM64 compatibility status
- What happens if it's missing (error message)

### 1.5 Acceptance Criteria
Define 8-10 concrete, testable acceptance criteria for the MVP. Each criterion must be:
- Binary (pass/fail, no "mostly works")
- Testable with a specific procedure
- Tied to a user-observable outcome

Example format:
> **AC-01:** Given a valid ePub with 10+ chapters, when running `python -m epub2audiobook book.epub`, then an M4B file appears in ~/Downloads within 60 minutes, plays in Apple Books, and shows correct chapter markers for each chapter.

### 1.6 Module Interface Contracts
For each module in the project structure (cli.py, parser.py, preprocessor.py, tts_engine.py, assembler.py), define:
- Public functions with signatures and type hints
- Input/output contracts (what each function promises)
- Error behavior (what exceptions it raises and when)

Do NOT write implementation code yet. Define interfaces only.

## Task 2: Implementation Plan

After I approve the product spec, produce an implementation plan with:
- Ordered list of implementation steps (which module first, which last)
- For each step: what to build, how to test it in isolation, definition of done
- Estimated complexity per step (simple / moderate / complex)
- Dependencies between steps (what blocks what)

## Constraints

- Read CLAUDE.md before starting. Reference it when making decisions.
- Do not add features beyond MVP scope. If you think something is missing, flag it as a question — don't add it.
- Do not use multiprocessing in MVP. Sequential chapter processing only.
- Do not build a Calibre plugin. This is a standalone tool.
- Do not use tkinter for the file picker — use a native macOS file dialog via PyObjC or a simple CLI prompt. If PyObjC adds too much complexity, skip the file picker and require a CLI path argument for MVP.
- All code must run natively on ARM64. No Rosetta.
- Keep the total dependency count under 10 Python packages.
```

---

## How to Use This

1. Open the project directory in Claude Code
2. Make sure CLAUDE.md is in the project root
3. Paste the prompt above (everything inside the code block)
4. Review the product spec Claude Code produces
5. Iterate on the spec — challenge edge cases, tighten acceptance criteria
6. Once spec is approved, tell Claude Code to proceed to Task 2 (implementation plan)
7. Once plan is approved, begin implementation module by module

**Key rule:** Do not let Claude Code skip the spec and jump to code. The spec is the artifact that prevents scope creep and hallucinated features during implementation.
