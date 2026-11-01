"""16×16 icons and frame helpers for the lamp.

Data only, no Home Assistant imports. A frame is a list of 256 brightness
values (0-255), row-major, index ``y * 16 + x``.

Icons are drawn as 16 strings of 16 characters:

    ``.`` or space  off
    ``-``           dim (40)
    ``+``           half (128)
    ``#``           full (255)

To add an icon, add an entry to ``ICONS``; ``tests/test_icons.py`` checks the
size and characters of every grid.
"""

from __future__ import annotations

from collections.abc import Sequence

SIZE = 16
PIXELS = SIZE * SIZE
LEVELS: dict[str, int] = {".": 0, " ": 0, "-": 40, "+": 128, "#": 255}

Grid = tuple[str, ...]

ICONS: dict[str, Grid] = {
    "door": (
        "................",
        "....########....",
        "....#......#....",
        "....#.####.#....",
        "....#.#..#.#....",
        "....#.####.#....",
        "....#......#....",
        "....#......#....",
        "....#....#.#....",
        "....#......#....",
        "....#.####.#....",
        "....#.#..#.#....",
        "....#.####.#....",
        "....#......#....",
        "..############..",
        "................",
    ),
    "bell": (
        "................",
        ".......##.......",
        ".....######.....",
        "....##....##....",
        "....#......#....",
        "...##......##...",
        "...#........#...",
        "...#........#...",
        "...#........#...",
        "..##........##..",
        "..#..........#..",
        ".##############.",
        "................",
        "......####......",
        ".......##.......",
        "................",
    ),
    "shower": (
        "................",
        "...#######......",
        "...#.....#......",
        "...#....###.....",
        "...#...#####....",
        "...#............",
        "...#...+.+.+....",
        "...#............",
        "...#..+.+.+.+...",
        "...#............",
        "...#...+.+.+....",
        "...#............",
        "...#..+.+.+.+...",
        "...#............",
        ".#####..........",
        "................",
    ),
    "fan": (
        "................",
        "......###.......",
        ".....#####......",
        ".....#####......",
        "......####......",
        "..##...##...##..",
        ".####.####.####.",
        ".#######.######.",
        ".######.#######.",
        ".####.####.####.",
        "..##...##...##..",
        "......####......",
        "......#####.....",
        "......#####.....",
        ".......###......",
        "................",
    ),
    "light_bulb": (
        "................",
        "......####......",
        ".....#....#.....",
        "....#......#....",
        "...#...--...#...",
        "...#..-..-..#...",
        "...#..-..-..#...",
        "...#...--...#...",
        "....#..--..#....",
        ".....#.--.#.....",
        "......####......",
        "......####......",
        "......####......",
        ".......##.......",
        "................",
        "................",
    ),
    "warning": (
        "................",
        ".......##.......",
        ".......##.......",
        "......####......",
        "......#..#......",
        ".....##..##.....",
        ".....#.##.#.....",
        "....##.##.##....",
        "....#..##..#....",
        "...##..##..##...",
        "...#........#...",
        "..##...##...##..",
        "..#....##....#..",
        ".##..........##.",
        ".##############.",
        "................",
    ),
    "check": (
        "................",
        "................",
        "..............#.",
        ".............##.",
        "............##..",
        "...........##...",
        "..........##....",
        ".#.......##.....",
        ".##.....##......",
        "..##...##.......",
        "...##.##........",
        "....###.........",
        ".....#..........",
        "................",
        "................",
        "................",
    ),
    "cross": (
        "................",
        ".#............#.",
        ".##..........##.",
        "..##........##..",
        "...##......##...",
        "....##....##....",
        ".....##..##.....",
        "......####......",
        "......####......",
        ".....##..##.....",
        "....##....##....",
        "...##......##...",
        "..##........##..",
        ".##..........##.",
        ".#............#.",
        "................",
    ),
    "clock": (
        "................",
        ".....######.....",
        "...##......##...",
        "..#....#.....#..",
        "..#....#.....#..",
        ".#.....#......#.",
        ".#.....#......#.",
        ".#.....####...#.",
        ".#............#.",
        ".#............#.",
        ".#............#.",
        "..#..........#..",
        "..#..........#..",
        "...##......##...",
        ".....######.....",
        "................",
    ),
    "wifi": (
        "................",
        "................",
        "....########....",
        "..##........##..",
        ".#............#.",
        "#....######....#",
        "...##......##...",
        "..#..........#..",
        ".....######.....",
        "....#......#....",
        "................",
        "......####......",
        "......#..#......",
        ".......##.......",
        ".......##.......",
        "................",
    ),
    "thermometer": (
        "................",
        ".......##.......",
        "......#..#......",
        "......#..#..##..",
        "......#..#......",
        "......#..#..#...",
        "......#..#......",
        "......#++#..##..",
        "......#++#......",
        "......#++#..#...",
        ".....#.++.#.....",
        "....#.++++.#....",
        "....#.++++.#....",
        ".....#.++.#.....",
        "......####......",
        "................",
    ),
    "droplet": (
        "................",
        ".......##.......",
        ".......##.......",
        "......####......",
        "......####......",
        ".....######.....",
        ".....######.....",
        "....###+####....",
        "....##+#####....",
        "...###+######...",
        "...###+######...",
        "...####+#####...",
        "....###++###....",
        ".....######.....",
        "......####......",
        "................",
    ),
    "bolt": (
        "................",
        ".........###....",
        "........###.....",
        ".......###......",
        "......###.......",
        ".....###........",
        "....########....",
        "...########.....",
        "........###.....",
        ".......###......",
        "......###.......",
        ".....###........",
        "....###.........",
        "...##...........",
        "...#............",
        "................",
    ),
    "home": (
        "................",
        ".......##.......",
        "......####......",
        ".....##..##.....",
        "....##....##....",
        "...##......##...",
        "..##........##..",
        ".##..........##.",
        "..#..........#..",
        "..#..........#..",
        "..#....###...#..",
        "..#....#.#...#..",
        "..#....#.#...#..",
        "..#....#.#...#..",
        "..############..",
        "................",
    ),
    "person": (
        "................",
        "......####......",
        ".....######.....",
        ".....######.....",
        ".....######.....",
        "......####......",
        "................",
        "....########....",
        "...##########...",
        "..##.######.##..",
        "..##.######.##..",
        "..##.######.##..",
        ".....##..##.....",
        ".....##..##.....",
        ".....##..##.....",
        "................",
    ),
    "arrow_up": (
        "................",
        ".......##.......",
        "......####......",
        ".....######.....",
        "....###..###....",
        "...###.##.###...",
        "..###..##..###..",
        "..##...##...##..",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "................",
    ),
    "arrow_down": (
        "................",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "..##...##...##..",
        "..###..##..###..",
        "...###.##.###...",
        "....###..###....",
        ".....######.....",
        "......####......",
        ".......##.......",
        "................",
    ),
    "arrow_left": (
        "................",
        "................",
        "......##........",
        ".....###........",
        "....###.........",
        "...###..........",
        "..###...........",
        ".##############.",
        ".##############.",
        "..###...........",
        "...###..........",
        "....###.........",
        ".....###........",
        "......##........",
        "................",
        "................",
    ),
    "arrow_right": (
        "................",
        "................",
        "........##......",
        "........###.....",
        ".........###....",
        "..........###...",
        "...........###..",
        ".##############.",
        ".##############.",
        "...........###..",
        "..........###...",
        ".........###....",
        "........###.....",
        "........##......",
        "................",
        "................",
    ),
    "heart": (
        "................",
        "................",
        "..####....####..",
        ".######..######.",
        "################",
        "################",
        "################",
        ".##############.",
        "..############..",
        "...##########...",
        "....########....",
        ".....######.....",
        "......####......",
        ".......##.......",
        "................",
        "................",
    ),
    "smiley": (
        "................",
        ".....######.....",
        "...##......##...",
        "..#..........#..",
        ".#............#.",
        ".#...##..##...#.",
        "#....##..##....#",
        "#..............#",
        "#..............#",
        "#..#........#..#",
        ".#..#......#..#.",
        ".#...######...#.",
        "..#..........#..",
        "...##......##...",
        ".....######.....",
        "................",
    ),
}

# 3×5 digits, scaled up by the renderer
DIGITS_3X5: dict[str, tuple[str, str, str, str, str]] = {
    "0": ("###", "#.#", "#.#", "#.#", "###"),
    "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"),
    "3": ("###", "..#", ".##", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"),
    "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"),
    "7": ("###", "..#", ".#.", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"),
    "9": ("###", "#.#", "###", "..#", "###"),
    "-": ("...", "...", "###", "...", "..."),
    ".": ("...", "...", "...", "...", ".#."),
    "%": ("#.#", "..#", ".#.", "#..", "#.#"),
}


def grid_to_frame(grid: Sequence[str], on: int = 255) -> list[int]:
    """Convert a 16×16 grid to a frame; ``on`` scales the full level."""
    if len(grid) != SIZE or any(len(row) != SIZE for row in grid):
        raise ValueError("icon grids must be 16 rows of 16 characters")
    frame: list[int] = []
    for row in grid:
        for char in row:
            if char not in LEVELS:
                raise ValueError(f"unknown icon character {char!r}")
            frame.append(LEVELS[char] * on // 255)
    return frame


def icon_frame(name: str, brightness: int = 255) -> list[int]:
    """Frame for a built-in icon."""
    try:
        return grid_to_frame(ICONS[name], brightness)
    except KeyError:
        raise KeyError(f"unknown icon {name!r}") from None


def hex_rows_to_frame(rows: Sequence[str]) -> list[int]:
    """16 strings of 16 hex digits; 0 = off, F = full (each step = 17)."""
    if len(rows) != SIZE:
        raise ValueError("expected 16 rows")
    frame: list[int] = []
    for raw in rows:
        row = raw.strip()
        if len(row) != SIZE:
            raise ValueError("each row needs 16 hex digits")
        try:
            frame.extend(int(char, 16) * 17 for char in row)
        except ValueError:
            raise ValueError(f"row {row!r} is not hexadecimal") from None
    return frame


def blank_frame() -> list[int]:
    """All pixels off."""
    return [0] * PIXELS


def scale(
    values: Sequence[float], low: float | None = None, high: float | None = None, top: int = 15
) -> list[int]:
    """Scale values to 0..``top``; the range defaults to the data's own."""
    if not values:
        return []
    lo = min(values) if low is None else low
    hi = max(values) if high is None else high
    if hi <= lo:
        return [
            top // 2 if low is None and high is None else (top if v >= hi else 0) for v in values
        ]
    return [round(max(0.0, min(1.0, (v - lo) / (hi - lo))) * top) for v in values]


def resample(values: Sequence[float], count: int) -> list[float]:
    """Average ``values`` into ``count`` buckets (or repeat them if fewer)."""
    if not values:
        return []
    if len(values) <= count:
        return [values[i * len(values) // count] for i in range(count)]
    out: list[float] = []
    for i in range(count):
        start = i * len(values) // count
        end = (i + 1) * len(values) // count
        bucket = values[start:end]
        out.append(sum(bucket) / len(bucket))
    return out


def bar_graph(
    values: Sequence[float],
    low: float | None = None,
    high: float | None = None,
    brightness: int = 255,
) -> list[int]:
    """Vertical bars, one column per value, the latest on the right.

    More than 16 values are averaged down; fewer are drawn right-aligned.
    Bars have height 1-16 so a zero still shows as a baseline.
    """
    columns = list(values)[-SIZE * 8 :]
    if len(columns) > SIZE:
        columns = resample(columns, SIZE)
    heights = [h + 1 for h in scale(columns, low, high, top=SIZE - 1)]
    offset = SIZE - len(heights)
    frame = blank_frame()
    for i, height in enumerate(heights):
        x = offset + i
        for y in range(SIZE - height, SIZE):
            # the top pixel full, the body slightly dimmer for readability
            frame[y * SIZE + x] = brightness if y == SIZE - height else brightness * 3 // 5
    return frame


def progress_bar(fraction: float, brightness: int = 255) -> list[int]:
    """Horizontal bar across the middle, filled to ``fraction`` (0-1)."""
    fraction = max(0.0, min(1.0, fraction))
    frame = blank_frame()
    filled = round(fraction * 14)
    for x in range(SIZE):
        for y in (5, 10):
            frame[y * SIZE + x] = brightness // 3
    for y in range(5, 11):
        frame[y * SIZE] = brightness // 3
        frame[y * SIZE + SIZE - 1] = brightness // 3
        for x in range(1, 1 + filled):
            if 6 <= y <= 9:
                frame[y * SIZE + x] = brightness
    return frame


def number_frame(value: float | int | str, brightness: int = 255) -> list[int]:
    """Draw a number with the 3×5 digits, as large as it fits.

    Two characters are drawn at 2× (6×10 each), up to four at 1×. Longer
    values raise ``ValueError``.
    """
    text = _format_number(value)
    for factor, gap in ((2, 2), (1, 1)):
        width = len(text) * 3 * factor + (len(text) - 1) * gap
        if width <= SIZE:
            break
    else:
        raise ValueError(f"{text!r} does not fit on 16 pixels")
    frame = blank_frame()
    x0 = (SIZE - width) // 2
    y0 = (SIZE - 5 * factor) // 2
    for index, char in enumerate(text):
        glyph = DIGITS_3X5[char]
        left = x0 + index * (3 * factor + gap)
        for gy, row in enumerate(glyph):
            for gx, cell in enumerate(row):
                if cell != "#":
                    continue
                for dy in range(factor):
                    for dx in range(factor):
                        frame[(y0 + gy * factor + dy) * SIZE + left + gx * factor + dx] = brightness
    return frame


def _format_number(value: float | int | str) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, float) and not value.is_integer():
        text = f"{value:.1f}" if abs(value) < 10 else str(round(value))
    else:
        text = str(int(value))
    if not text or any(c not in DIGITS_3X5 for c in text):
        raise ValueError(f"cannot draw {value!r}")
    return text
