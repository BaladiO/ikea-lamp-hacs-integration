"""Tests for the icon library and frame helpers."""

from __future__ import annotations

import pytest

from custom_components.obegraensad_lamp import icons


@pytest.mark.parametrize("name", sorted(icons.ICONS))
def test_icon_grid_is_16x16(name: str) -> None:
    """Every icon has 16 rows of 16 known characters and lights something."""
    grid = icons.ICONS[name]
    assert len(grid) == 16
    for row in grid:
        assert len(row) == 16, f"{name}: {row!r}"
        assert set(row) <= set(icons.LEVELS), f"{name}: {row!r}"
    frame = icons.icon_frame(name)
    assert len(frame) == 256
    assert any(frame)


def test_required_icons_exist() -> None:
    """The set from the brief is complete."""
    required = {
        "door", "bell", "shower", "fan", "light_bulb", "warning", "check", "cross", "clock",
        "wifi", "thermometer", "droplet", "bolt", "home", "person", "arrow_up", "arrow_down",
        "arrow_left", "arrow_right", "heart", "smiley",
    }  # fmt: skip
    assert required <= set(icons.ICONS)


def test_icon_brightness_and_errors() -> None:
    """Brightness scales the levels; bad input raises."""
    frame = icons.icon_frame("heart", 100)
    assert max(frame) == 100
    with pytest.raises(KeyError):
        icons.icon_frame("nope")
    with pytest.raises(ValueError):
        icons.grid_to_frame(["." * 16] * 15)
    with pytest.raises(ValueError):
        icons.grid_to_frame(["x" * 16] * 16)


def test_hex_rows() -> None:
    """Hex digits map to 0-255 in steps of 17."""
    rows = ["0123456789ABCDEF"] + ["0" * 16] * 15
    frame = icons.hex_rows_to_frame(rows)
    assert frame[:16] == [i * 17 for i in range(16)]
    assert frame[15] == 255
    with pytest.raises(ValueError):
        icons.hex_rows_to_frame(["0" * 16] * 15)
    with pytest.raises(ValueError):
        icons.hex_rows_to_frame(["0" * 15] * 16)
    with pytest.raises(ValueError):
        icons.hex_rows_to_frame(["G" * 16] * 16)


def test_scale_and_resample() -> None:
    """Values are scaled to 0-15 and averaged into buckets."""
    assert icons.scale([0, 5, 10]) == [0, 8, 15]
    assert icons.scale([5, 5]) == [7, 7]
    assert icons.scale([0, 20], 0, 10) == [0, 15]
    assert icons.scale([]) == []
    assert icons.resample([1, 3, 5, 7], 2) == [2, 6]
    assert icons.resample([1, 2], 4) == [1, 1, 2, 2]


def test_bar_graph() -> None:
    """Latest value on the right; the maximum fills the column."""
    frame = icons.bar_graph([0, 10])
    column = [frame[y * 16 + 15] for y in range(16)]
    assert all(column)
    left = [frame[y * 16 + 14] for y in range(16)]
    assert sum(1 for v in left if v) == 1
    assert not any(frame[y * 16 + 13] for y in range(16))
    assert len(icons.bar_graph(list(range(100)))) == 256


def test_progress_bar() -> None:
    """Half full lights 7 of 14 inner columns."""
    frame = icons.progress_bar(0.5)
    row = frame[7 * 16 : 8 * 16]
    assert row.count(255) == 7


@pytest.mark.parametrize("value", [0, 7, 42, -5, 3.5, "12%", 1234])
def test_number_frame(value: float | str) -> None:
    """Numbers up to 4 characters fit."""
    assert any(icons.number_frame(value))


def test_number_frame_errors() -> None:
    """Too long or unknown characters raise."""
    with pytest.raises(ValueError):
        icons.number_frame(123456)
    with pytest.raises(ValueError):
        icons.number_frame("12a")
