"""Make text fit the lamp's 5×7 system font (``signs.cpp``).

The font has printable ASCII 32-125, ``~`` drawn as a right arrow, DEL (127)
as a left arrow, and Ä Ö Ü ß ä ö ü, which the firmware reads from their UTF-8
form. Everything else would be drawn blank or as a wrong glyph, so it is
transliterated or dropped here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

MAX_LENGTH = 160

LEFT_ARROW = "\x7f"
FONT_EXTRA = frozenset("ÄÖÜßäöü")

REPLACEMENTS: dict[str, str] = {
    "‘": "'",
    "’": "'",
    "‚": ",",
    "“": '"',
    "”": '"',
    "„": '"',
    "«": '"',
    "»": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "…": "...",
    "•": "*",
    "·": "*",
    "×": "x",
    "÷": "/",
    "€": "EUR",
    "£": "GBP",
    "°": "o",
    "→": "~",
    "⇒": "~",
    "➜": "~",
    "←": LEFT_ARROW,
    "⇐": LEFT_ARROW,
    "Æ": "AE",
    "æ": "ae",
    "Œ": "OE",
    "œ": "oe",
    "Ø": "O",
    "ø": "o",
    "Ł": "L",
    "ł": "l",
    "Đ": "D",
    "đ": "d",
    "ẞ": "SS",
}

_WHITESPACE = re.compile(r"\s+")


@dataclass
class SanitizedText:
    """Result of :func:`sanitize`."""

    text: str
    replaced: dict[str, str] = field(default_factory=dict)
    dropped: set[str] = field(default_factory=set)
    truncated: bool = False

    @property
    def changed(self) -> bool:
        """Whether anything was altered."""
        return bool(self.replaced or self.dropped or self.truncated)


def _is_supported(char: str) -> bool:
    return 32 <= ord(char) <= 126 or char == LEFT_ARROW or char in FONT_EXTRA


def sanitize(text: str, max_length: int = MAX_LENGTH) -> SanitizedText:
    """Transliterate ``text`` to characters the lamp can draw."""
    result = SanitizedText(text="")
    out: list[str] = []
    for char in _WHITESPACE.sub(" ", text):
        if _is_supported(char):
            out.append(char)
            continue
        if char in REPLACEMENTS:
            result.replaced[char] = REPLACEMENTS[char]
            out.append(REPLACEMENTS[char])
            continue
        # é -> e, ﬁ -> fi, full-width letters -> ASCII
        decomposed = "".join(
            c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c)
        )
        if decomposed and all(_is_supported(c) for c in decomposed):
            result.replaced[char] = decomposed
            out.append(decomposed)
        else:
            # emoji, other scripts, control characters
            result.dropped.add(char)
    cleaned = _WHITESPACE.sub(" ", "".join(out)).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3].rstrip() + "..."
        result.truncated = True
    result.text = cleaned
    return result


def scroll_width(text: str) -> int:
    """Scroll steps the firmware uses for ``text``.

    ``Screen.scrollText`` takes the byte length times 6, so umlauts count twice.
    """
    return len(text.encode("utf-8")) * 6
