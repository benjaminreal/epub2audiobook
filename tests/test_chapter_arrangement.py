"""Tests for dropping non-spoken sections and joining note pages."""

import re
import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

from epub2audiobook import parser
from epub2audiobook.parser import Chapter


def _page(body: str, body_type: str = "") -> str:
    attr = f' epub:type="{body_type}"' if body_type else ""
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>t</title></head><body{attr}>{body}</body></html>"
    )


CONTENTS = _page(
    "<h2>Contents</h2>"
    '<p><a href="ch1.xhtml#a">Prologue</a></p>'
    '<p><a href="ch2.xhtml#b">1. The Mountain</a></p>'
    '<p><a href="ch3.xhtml#c">2. The River</a></p>'
)
TEXT = _page(
    "<h1>Prologue</h1><p>I am standing on the red railway car.</p>"
    '<p>The wind is <a href="https://example.com">strong</a> today.'
    '<sup><a href="note1.xhtml#n1" id="r1">*</a></sup></p>'
)
FOOTNOTE_TYPED = _page(
    '<div epub:type="footnote"><p class="fn"><sup>'
    '<a href="ch1.xhtml#r1" id="n1">*</a></sup> Except for my sister.</p></div>',
    "backmatter",
)
FOOTNOTE_UNTYPED = _page(
    '<p class="fn"><sup><a href="ch2.xhtml#r2" id="n2">*</a></sup> '
    "It is possible that my timeline is off.</p>",
    "backmatter",
)
ENDNOTES = _page(
    '<section epub:type="endnotes"><h1>Notes</h1>'
    "<p>1. Interview with the author, 2023.</p>"
    "<p>2. Census data, 1990.</p></section>"
)


class ClassifyDocumentTests(unittest.TestCase):
    def test_contents_page_is_toc(self):
        self.assertEqual(parser._classify_document(CONTENTS), "toc")

    def test_epub_type_toc_is_toc(self):
        nav = _page('<nav epub:type="toc"><ol><li>Prologue</li></ol></nav>')
        self.assertEqual(parser._classify_document(nav), "toc")

    def test_chapter_with_links_is_text(self):
        self.assertEqual(parser._classify_document(TEXT), "text")

    def test_footnote_pages_are_notes(self):
        self.assertEqual(parser._classify_document(FOOTNOTE_TYPED), "notes")
        self.assertEqual(parser._classify_document(FOOTNOTE_UNTYPED), "notes")

    def test_endnotes_section_is_notes(self):
        self.assertEqual(parser._classify_document(ENDNOTES), "notes")

    def test_small_inline_toc_does_not_hide_a_chapter(self):
        page = _page(
            '<nav epub:type="toc"><ol><li><a href="a.xhtml">One</a></li></ol></nav>'
            + "<p>A long paragraph of the chapter itself, read aloud.</p>" * 5
        )
        self.assertEqual(parser._classify_document(page), "text")

    def test_annotated_contents_is_not_notes(self):
        entries = "".join(
            f'<p><a href="ch{i}.xhtml#c">Chapter {i}</a> in which the hero '
            "travels far and learns a great deal about the world.</p>"
            for i in range(1, 6)
        )
        self.assertNotEqual(parser._classify_document(_page(entries)), "notes")

    def test_chapter_with_inline_footnote_is_text(self):
        page = _page(
            "<p>Main text of the chapter.</p>"
            '<aside epub:type="footnote"><p>A note.</p></aside>'
        )
        self.assertEqual(parser._classify_document(page), "text")


def _chapter(title: str, text: str, kind: str = "text") -> Chapter:
    # titles of the form "Chapter N" stand for ones the parser made up
    generated = bool(re.fullmatch(r"Chapter \d+", title))
    return Chapter(
        index=0,
        title=title,
        text=text,
        source_href=title,
        kind=kind,
        generated_title=generated,
    )


class ArrangeChaptersTests(unittest.TestCase):
    def test_drops_empty_and_toc_and_reindexes(self):
        chapters = [
            _chapter("Cover", ""),
            _chapter("Contents", "Contents\n\nPrologue", "toc"),
            _chapter("Prologue", "Prologue\n\nText."),
            _chapter("Chapter 4", "   "),
            _chapter("One", "One\n\nMore text."),
        ]
        arranged = parser._arrange_chapters(chapters)
        self.assertEqual([c.title for c in arranged], ["Prologue", "One"])
        self.assertEqual([c.index for c in arranged], [0, 1])

    def test_untitled_note_pages_become_one_notes_chapter(self):
        chapters = [
            _chapter("Prologue", "Prologue\n\nText."),
            _chapter("Chapter 2", "* Except for my sister.", "notes"),
            _chapter("Chapter 3", "† It is possible.", "notes"),
        ]
        arranged = parser._arrange_chapters(chapters)
        self.assertEqual([c.title for c in arranged], ["Prologue", "Notes"])
        self.assertEqual(
            arranged[1].text, "Notes\n\nExcept for my sister.\n\nIt is possible."
        )

    def test_titled_note_page_keeps_title_and_place(self):
        chapters = [
            _chapter("Photograph Captions", "Photograph Captions\n\n1. Me", "notes"),
            _chapter("Prologue", "Prologue\n\nText."),
            _chapter("Chapter 3", "* A footnote.", "notes"),
        ]
        arranged = parser._arrange_chapters(chapters)
        self.assertEqual(
            [c.title for c in arranged], ["Photograph Captions", "Prologue", "Notes"]
        )
        self.assertEqual(arranged[0].text, "Photograph Captions\n\n1. Me")

    def test_titled_note_pages_keep_their_markers(self):
        chapters = [
            _chapter("Notes to Chapter 1", "Notes to Chapter 1\n\n1. A", "notes"),
            _chapter("Notes to Chapter 2", "Notes to Chapter 2\n\n1. B", "notes"),
            _chapter("Chapter 3", "* C", "notes"),
        ]
        arranged = parser._arrange_chapters(chapters)
        self.assertEqual(
            [c.title for c in arranged], ["Notes to Chapter 1", "Notes to Chapter 2"]
        )
        self.assertEqual(arranged[1].text, "Notes to Chapter 2\n\n1. B\n\nC")

    def test_book_title_of_the_form_chapter_n_is_kept(self):
        chapter = Chapter(0, "Chapter 12", "* A note.", "x", kind="notes")
        self.assertEqual(parser._arrange_chapters([chapter])[0].title, "Chapter 12")

    def test_text_between_note_pages_splits_runs(self):
        chapters = [
            _chapter("Chapter 1", "* First.", "notes"),
            _chapter("Middle", "Middle\n\nText."),
            _chapter("Chapter 3", "* Second.", "notes"),
        ]
        titles = [c.title for c in parser._arrange_chapters(chapters)]
        self.assertEqual(titles, ["Notes", "Middle", "Notes"])


class NoteTextTests(unittest.TestCase):
    def test_note_page_text_is_kept(self):
        page = _page('<aside epub:type="footnote"><p>An aside note.</p></aside>')
        self.assertEqual(parser._html_to_text(page), "")
        self.assertEqual(parser._html_to_text(page, keep_notes=True), "An aside note.")


class ParseEpubTests(unittest.TestCase):
    def test_book_with_cover_contents_and_footnotes(self):
        book = epub.EpubBook()
        book.set_identifier("test-book")
        book.set_title("Test Book")
        book.set_language("en")
        book.add_author("Test Author")
        pages = [
            ("cover.xhtml", "Cover", _page('<img src="cover.jpg" alt=""/>')),
            ("contents.xhtml", "Contents", CONTENTS),
            ("ch1.xhtml", "Prologue", TEXT),
            ("ch2.xhtml", "1. The Mountain", _page("<h1>1</h1><p>Words.</p>")),
            ("note1.xhtml", None, FOOTNOTE_TYPED),
            ("note2.xhtml", None, FOOTNOTE_UNTYPED),
        ]
        items = []
        for name, title, html in pages:
            item = epub.EpubHtml(title=title or name, file_name=name, lang="en")
            item.content = html
            book.add_item(item)
            items.append((item, title))
        book.toc = [epub.Link(i.file_name, t, i.file_name) for i, t in items if t]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [i for i, _ in items]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.epub"
            epub.write_epub(str(path), book)
            _, chapters = parser.parse_epub(path)
        self.assertEqual(
            [c.title for c in chapters], ["Prologue", "1. The Mountain", "Notes"]
        )
        self.assertEqual(
            chapters[-1].text,
            "Notes\n\nExcept for my sister.\n\nIt is possible that my timeline is off.",
        )


if __name__ == "__main__":
    unittest.main()
