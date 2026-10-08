"""ePub parsing: text extraction, metadata, and cover image.

Reads ePub files in spine order, extracts Dublin Core metadata,
detects chapter boundaries, and handles flat ePub splitting.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from epub2audiobook.config import (
    FLAT_EPUB_MAX_SPINE_ITEMS,
    FLAT_EPUB_MIN_TEXT_LENGTH,
    MIN_CHAPTER_CHARS,
)

logger = logging.getLogger(__name__)


class ParsingError(Exception):
    """Raised when ePub parsing fails."""


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
    try:
        book = epub.read_epub(str(epub_path), options={"ignore_ncx": False})
    except Exception as e:
        raise ParsingError(f"Failed to parse ePub: {e}") from e

    metadata = _extract_metadata(book, epub_path)
    cover_image, cover_format = extract_cover(book)
    metadata.cover_image = cover_image
    metadata.cover_format = cover_format

    # Build TOC href-to-title mapping
    toc_map = _build_toc_map(book)

    # Extract chapters from spine
    chapters = _extract_chapters_from_spine(book, toc_map)

    # Detect and handle flat ePubs
    if _is_flat_epub(chapters):
        logger.info("Flat ePub detected. Splitting on headings.")
        chapters = _split_flat_chapters(book, chapters)

    if not chapters:
        raise ParsingError("No chapters could be extracted from the ePub.")

    # Log short chapters
    for ch in chapters:
        if len(ch.text.strip()) < MIN_CHAPTER_CHARS:
            logger.warning(
                "Short chapter detected: '%s' (%d chars)",
                ch.title, len(ch.text.strip()),
            )

    return metadata, chapters


def extract_cover(book: epub.EpubBook) -> tuple[bytes | None, str | None]:
    """Extract the cover image from an ePub book object.

    Tries OPF cover metadata first, then scans manifest for cover
    candidates.

    Args:
        book: An opened EpubBook instance.

    Returns:
        Tuple of (image bytes, format string) or (None, None).
    """
    # Try OPF cover metadata
    cover_meta = book.get_metadata("OPF", "cover")
    if cover_meta:
        cover_id = cover_meta[0][1].get("content", "")
        if cover_id:
            item = book.get_item_with_id(cover_id)
            if item is not None:
                fmt = _image_format(item.media_type)
                if fmt:
                    return item.get_content(), fmt

    # Scan manifest for cover candidates
    for item in book.get_items():
        if not item.media_type or not item.media_type.startswith("image/"):
            continue
        # Check properties
        props = getattr(item, "properties", []) or []
        if "cover-image" in props:
            fmt = _image_format(item.media_type)
            if fmt:
                return item.get_content(), fmt
        # Check filename
        name = (item.get_name() or "").lower()
        if "cover" in name:
            fmt = _image_format(item.media_type)
            if fmt:
                return item.get_content(), fmt

    logger.warning("No cover image found in ePub metadata.")
    return None, None


def _extract_metadata(book: epub.EpubBook, epub_path: Path) -> BookMetadata:
    """Extract Dublin Core metadata with fallbacks."""
    # Title
    title_meta = book.get_metadata("DC", "title")
    if title_meta:
        title = title_meta[0][0]
    else:
        title = epub_path.stem.replace("_", " ").replace("-", " ")
        logger.warning("No title found in ePub metadata. Using: %s", title)

    # Author
    author_meta = book.get_metadata("DC", "creator")
    if author_meta:
        author = author_meta[0][0]
    else:
        author = "Unknown Author"
        logger.warning("No author found in ePub metadata. Using: %s", author)

    # Language
    lang_meta = book.get_metadata("DC", "language")
    language = lang_meta[0][0] if lang_meta else "en"

    return BookMetadata(
        title=title,
        author=author,
        language=language,
        cover_image=None,
        cover_format=None,
    )


def _build_toc_map(book: epub.EpubBook) -> dict[str, str]:
    """Build a mapping from spine item hrefs to TOC titles.

    Handles both flat and nested TOC structures.

    Returns:
        Dict mapping href (without fragment) to title string.
    """
    toc_map: dict[str, str] = {}

    def _process_toc_item(item: epub.Link | tuple) -> None:
        if isinstance(item, epub.Link):
            href = item.href.split("#")[0]
            toc_map[href] = item.title
        elif isinstance(item, tuple) and len(item) == 2:
            # Nested TOC: (section, [children])
            section, children = item
            if isinstance(section, epub.Section):
                pass  # Section doesn't have a direct href mapping
            elif isinstance(section, epub.Link):
                href = section.href.split("#")[0]
                toc_map[href] = section.title
            for child in children:
                _process_toc_item(child)

    for item in book.toc:
        _process_toc_item(item)

    return toc_map


def _extract_chapters_from_spine(
    book: epub.EpubBook,
    toc_map: dict[str, str],
) -> list[Chapter]:
    """Extract chapters by iterating spine items in order."""
    chapters: list[Chapter] = []
    chapter_index = 0

    for item_id, linear in book.spine:
        if linear == "no":
            continue

        item = book.get_item_with_id(item_id)
        if item is None:
            logger.warning("Spine item not found: %s", item_id)
            continue

        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        try:
            html_content = item.get_content().decode("utf-8", errors="replace")
            text = _html_to_text(html_content)
        except Exception as e:
            logger.warning("Failed to parse spine item %s: %s", item_id, e)
            continue

        # Determine chapter title
        href = item.get_name()
        title = toc_map.get(href)
        if not title:
            title = _extract_heading(html_content)
        if not title:
            title = f"Chapter {chapter_index + 1}"

        chapters.append(Chapter(
            index=chapter_index,
            title=title,
            text=text,
            source_href=href or item_id,
        ))
        chapter_index += 1

    return chapters


def _html_to_text(html_content: str) -> str:
    """Extract visible text from HTML, preserving paragraph boundaries."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "aside"]):
        element.decompose()

    # Remove footnote containers
    for element in soup.find_all(class_=re.compile(r"footnote|endnote", re.IGNORECASE)):
        element.decompose()

    return soup.get_text(separator="\n")


def _extract_heading(html_content: str) -> str | None:
    """Extract the first h1/h2/h3 text from HTML."""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in ("h1", "h2", "h3"):
        heading = soup.find(tag)
        if heading:
            text = heading.get_text(strip=True)
            if text:
                return text
    return None


def _is_flat_epub(chapters: list[Chapter]) -> bool:
    """Detect if the ePub has a flat structure."""
    if len(chapters) > FLAT_EPUB_MAX_SPINE_ITEMS:
        return False
    total_text = sum(len(ch.text) for ch in chapters)
    return total_text >= FLAT_EPUB_MIN_TEXT_LENGTH


_SPLIT_MARKER = "@@EPUB2AUDIOBOOK_SPLIT@@"


def _split_flat_chapters(
    book: epub.EpubBook,
    chapters: list[Chapter],
) -> list[Chapter]:
    """Split flat ePub chapters on heading tags.

    Re-parses the HTML of each spine item and starts a new chapter at
    every h1/h2. Items with fewer than two headings are kept whole, so a
    single-story ePub stays one chapter instead of being split per paragraph.
    """
    new_chapters: list[Chapter] = []

    for chapter in chapters:
        item = book.get_item_with_href(chapter.source_href)
        if item is None:
            new_chapters.append(chapter)
            continue

        html_content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_content, "html.parser")
        headings = soup.find_all(["h1", "h2"])
        if len(headings) < 2:
            new_chapters.append(chapter)
            continue

        titles = [h.get_text(strip=True) for h in headings]
        for heading in headings:
            heading.insert_before(_SPLIT_MARKER)

        preamble, *sections = _html_to_text(str(soup)).split(_SPLIT_MARKER)
        if preamble.strip():
            new_chapters.append(Chapter(
                index=0,
                title=chapter.title,
                text=preamble,
                source_href=chapter.source_href,
            ))
        for title, text in zip(titles, sections):
            new_chapters.append(Chapter(
                index=0,
                title=title or f"Chapter {len(new_chapters) + 1}",
                text=text,
                source_href=chapter.source_href,
            ))

    for i, chapter in enumerate(new_chapters):
        chapter.index = i

    return new_chapters if new_chapters else chapters


def _image_format(media_type: str) -> str | None:
    """Map MIME type to image format string."""
    formats = {
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/png": "png",
    }
    return formats.get(media_type)
