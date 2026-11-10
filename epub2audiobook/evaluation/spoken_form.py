"""Normalize text to comparable spoken words.

Both the expected text and the speech-to-text output pass through the same
rules, so "$500" and "five hundred dollars" compare equal. The rules are
deliberately small; anything they miss shows up as a flag for review, not as
a silent pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))
NUMBER_WORDS = frozenset(
    _ONES[1:]
    + _TENS[2:]
    + ["hundred", "thousand", "million", "billion", "dollars", "percent"]
)


def number_to_words(n: int) -> list[str]:
    """Spell a non-negative integer the way a narrator reads a quantity."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        return [_TENS[tens]] + ([_ONES[ones]] if ones else [])
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_ONES[hundreds], "hundred"] + (number_to_words(rest) if rest else [])
    for scale, name in _SCALES:
        if n >= scale:
            high, rest = divmod(n, scale)
            return (
                number_to_words(high) + [name] + (number_to_words(rest) if rest else [])
            )
    raise ValueError(n)


def year_to_words(n: int) -> list[str]:
    """Spell 1100-1999 and 2010-2099 the way years are read ("nineteen ninety")."""
    high, low = divmod(n, 100)
    if low == 0:
        return number_to_words(high) + ["hundred"]
    if low < 10:
        return number_to_words(high) + ["oh"] + number_to_words(low)
    return number_to_words(high) + number_to_words(low)


def _spell(match: re.Match) -> str:
    sign, dollar, digits, percent = (
        match.group(1),
        match.group(2),
        match.group(3).replace(",", ""),
        match.group(4),
    )
    n = int(digits)
    if (
        not dollar
        and not percent
        and len(digits) == 4
        and (1100 <= n <= 1999 or 2010 <= n <= 2099)
    ):
        spoken = year_to_words(n)
    else:
        spoken = number_to_words(n)
    if sign:
        spoken.insert(0, "minus")
    if dollar:
        spoken.append("dollars")
    if percent:
        spoken.append("percent")
    return " " + " ".join(spoken) + " "


@dataclass(frozen=True)
class Token:
    """One comparable word and the original text it came from."""

    word: str
    original: str
    is_name: bool


def tokenize(text: str) -> list[Token]:
    """Split text into normalized spoken words.

    A token is marked as a name when it is capitalized and does not start a
    sentence. That heuristic marks some ordinary words too; it only decides
    how a flag is labelled.
    """
    text = text.replace("’", "'").replace("‘", "'")
    # A sign counts only at the start or after a space or bracket, not in "a-5"
    text = re.sub(r"((?<!\w)[-\u2212](?=\$?\d))?(\$)?(\d[\d,]*)(%)?", _spell, text)
    tokens: list[Token] = []
    sentence_start = True
    letters = r"[^\W_]+(?:'[^\W_]+)*"  # Unicode letters and digits, not "_"
    for raw in re.findall(rf"'?{letters}'?(?:-{letters})*|[.!?]", text):
        if raw in ".!?":
            sentence_start = True
            continue
        for part in raw.split("-"):
            word = part.lower().strip("'")
            if not word:
                continue
            is_name = (
                part[:1].isupper()
                and not sentence_start
                and part not in ("I", "I'm", "I'd", "I've", "I'll")
            )
            tokens.append(Token(word, part, is_name))
            sentence_start = False
    return tokens


def words(text: str) -> list[str]:
    """Return only the normalized words of text."""
    return [t.word for t in tokenize(text)]
