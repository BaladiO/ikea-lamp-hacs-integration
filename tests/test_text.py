"""Tests for text sanitising."""

from __future__ import annotations

import pytest

from custom_components.obegraensad_lamp.text import LEFT_ARROW, sanitize, scroll_width


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DOOR", "DOOR"),
        ("Hello world!", "Hello world!"),
        ("Tür auf, Größe", "Tür auf, Größe"),
        ("Café crème", "Cafe creme"),
        ("21°C", "21oC"),
        ("Done 🎉✅", "Done"),
        ("line1\nline2\t end", "line1 line2 end"),
        ("“quoted” – dash…", '"quoted" - dash...'),
        ("go → there ← back", f"go ~ there {LEFT_ARROW} back"),
        ("ﬁle Ｆｕｌｌ", "file Full"),
        ("Œuvre", "OEuvre"),
        ("  spaces   collapse  ", "spaces collapse"),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    """Characters outside the font are transliterated or dropped."""
    assert sanitize(raw).text == expected


def test_unrenderable_script_is_dropped() -> None:
    """Arabic letters cannot be drawn and are reported as dropped."""
    result = sanitize("باب DOOR")
    assert result.text == "DOOR"
    assert result.dropped
    assert result.changed


def test_unchanged_reports_nothing() -> None:
    """Plain ASCII is not flagged as changed."""
    result = sanitize("BATH")
    assert not result.changed


def test_truncation() -> None:
    """Long text is cut with an ellipsis."""
    result = sanitize("A" * 500, max_length=20)
    assert result.text == "A" * 17 + "..."
    assert result.truncated


def test_all_output_is_drawable() -> None:
    """Every output character is one the font has."""
    out = sanitize("".join(chr(c) for c in range(0, 0x3000))).text
    assert all(32 <= ord(c) <= 127 or c in "ÄÖÜßäöü" for c in out)


def test_scroll_width_counts_bytes() -> None:
    """Umlauts take two bytes in the firmware's width calculation."""
    assert scroll_width("AB") == 12
    assert scroll_width("Ä") == 12
