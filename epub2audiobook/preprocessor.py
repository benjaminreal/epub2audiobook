"""Text cleaning pipeline for TTS consumption.

Applies 9 sequential rules to transform raw ePub text into clean
text suitable for Piper TTS synthesis.
"""

import html
import re
import unicodedata

# Abbreviation expansion map
_ABBREVIATIONS: dict[str, str] = {
    r"\bMr\.": "Mister",
    r"\bMrs\.": "Missus",
    r"\bMs\.": "Mizz",
    r"\bDr\.": "Doctor",
    r"\bProf\.": "Professor",
    r"\bSt\.": "Saint",
    r"\bJr\.": "Junior",
    r"\bSr\.": "Senior",
    r"\betc\.": "etcetera",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\bvs\.": "versus",
}

# Unicode replacement map
_UNICODE_REPLACEMENTS: dict[str, str] = {
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote
    "\u2014": " -- ",  # em-dash
    "\u2013": "-",   # en-dash
    "\u2026": "...", # horizontal ellipsis
    "\ufb01": "fi",  # fi ligature
    "\ufb02": "fl",  # fl ligature
}


def preprocess_text(text: str) -> str:
    """Run the full text preprocessing pipeline.

    Applies all cleaning rules in sequence.

    Args:
        text: Raw chapter text from the parser.

    Returns:
        Cleaned text ready for TTS.
    """
    text = strip_html_tags(text)
    text = decode_html_entities(text)
    text = normalize_unicode(text)
    text = expand_abbreviations(text)
    text = remove_urls_and_emails(text)
    text = remove_footnote_markers(text)
    text = remove_control_characters(text)
    text = normalize_whitespace(text)
    text = preserve_sentence_boundaries(text)
    return text


def strip_html_tags(text: str) -> str:
    """Remove HTML tags, converting block elements to newlines.

    Args:
        text: Text potentially containing HTML tags.

    Returns:
        Text with HTML tags removed.
    """
    # Convert block-level elements to newlines
    text = re.sub(r"<\s*(?:p|br|div|h[1-6]|li|tr|blockquote)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove closing block tags
    text = re.sub(r"<\s*/\s*(?:p|div|h[1-6]|li|tr|blockquote)\s*>", "\n", text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    return text


def decode_html_entities(text: str) -> str:
    """Decode HTML entities (named and numeric) to characters.

    Args:
        text: Text with HTML entities.

    Returns:
        Text with entities decoded.
    """
    return html.unescape(text)


def normalize_unicode(text: str) -> str:
    """NFC normalize and replace smart quotes, dashes, ligatures.

    Args:
        text: Text with Unicode characters.

    Returns:
        Normalized text with ASCII-friendly replacements.
    """
    text = unicodedata.normalize("NFC", text)
    for char, replacement in _UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text


def expand_abbreviations(text: str) -> str:
    """Expand common abbreviations to spoken forms.

    Args:
        text: Text containing abbreviations.

    Returns:
        Text with abbreviations expanded.
    """
    for pattern, expansion in _ABBREVIATIONS.items():
        text = re.sub(pattern, expansion, text)
    return text


def remove_urls_and_emails(text: str) -> str:
    """Remove URLs and email addresses.

    Args:
        text: Text containing URLs or emails.

    Returns:
        Text with URLs and emails removed.
    """
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\S+@\S+\.\S+", "", text)
    return text


def remove_footnote_markers(text: str) -> str:
    """Remove bracketed footnote references like [1], [*].

    Args:
        text: Text with footnote markers.

    Returns:
        Text with footnote markers removed.
    """
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\[\*+\]", "", text)
    return text


def remove_control_characters(text: str) -> str:
    """Remove Unicode control characters except newline and tab.

    Args:
        text: Text with possible control characters.

    Returns:
        Text with control characters removed.
    """
    return "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace runs, normalize paragraph breaks.

    Args:
        text: Text with irregular whitespace.

    Returns:
        Text with normalized whitespace.
    """
    # Replace tabs with spaces
    text = text.replace("\t", " ")
    # Collapse multiple spaces into one
    text = re.sub(r" {2,}", " ", text)
    # Normalize multiple newlines to double newlines (paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Strip leading/trailing whitespace from the whole text
    return text.strip()


def preserve_sentence_boundaries(text: str) -> str:
    """Ensure paragraphs end with terminal punctuation.

    Appends a period to paragraphs that end with alphanumeric
    characters without terminal punctuation, improving TTS prosody.

    Args:
        text: Text with possible missing sentence endings.

    Returns:
        Text with terminal punctuation ensured.
    """
    paragraphs = text.split("\n\n")
    result = []
    for para in paragraphs:
        para = para.strip()
        if para and re.search(r"[a-zA-Z0-9]$", para):
            para += "."
        result.append(para)
    return "\n\n".join(result)
