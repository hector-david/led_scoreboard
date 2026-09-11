"""Render a clock face for the 32x16 panel. No BLE, no clock, just pixels.

Everything here is pure: give it a `datetime` and it hands back a 32x16 image.
That keeps the design loop off the radio -- `custom_clock.py --preview` renders a
contact sheet of a whole day in a second, and you can iterate on colours and
layout without touching the panel.

Why hand-built bitmap glyphs rather than a TrueType font: at ten pixels tall a
scaled vector font turns into grey mush, and the stems land on half-pixels. The
6x10 digits below are the ones `../src/led_scoreboard.py` already puts on this
exact panel, so they are known to read from across a room. `--glow` adds the
soft edge afterwards, which is the part that genuinely helps on LEDs.

Layout, 32 wide by 16 tall:

    +--------------------------------+
    |                                |  rows 0-1   margin
    |   HH : MM   (6x10 glyphs)      |  rows 2-11
    |                                |  rows 12-13 margin
    |################----------------|  rows 14-15 seconds bar
    +--------------------------------+
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

WIDTH = 32
HEIGHT = 16

DIGIT_W = 6
DIGIT_H = 10
SMALL_W = 3
SMALL_H = 5
GAP = 1
COLON_W = 2

RGB = Tuple[int, int, int]
Frame = List[List[RGB]]

# Tall 6x10 digits, lifted verbatim from ../src/led_scoreboard.py -- already
# proven legible on this panel rather than freshly invented here.
DIGITS: Dict[str, Sequence[str]] = {
    "0": ("011110", "100001", "100001", "100001", "100001",
          "100001", "100001", "100001", "100001", "011110"),
    "1": ("001100", "011100", "001100", "001100", "001100",
          "001100", "001100", "001100", "001100", "011110"),
    "2": ("011110", "100001", "000001", "000001", "000010",
          "000100", "001000", "010000", "100000", "111111"),
    "3": ("011110", "100001", "000001", "000001", "001110",
          "000001", "000001", "000001", "100001", "011110"),
    "4": ("000110", "001010", "001010", "010010", "010010",
          "100010", "111111", "000010", "000010", "000010"),
    "5": ("111111", "100000", "100000", "100000", "111110",
          "000001", "000001", "000001", "100001", "011110"),
    "6": ("001110", "010000", "100000", "100000", "111110",
          "100001", "100001", "100001", "100001", "011110"),
    "7": ("111111", "000001", "000010", "000010", "000100",
          "000100", "001000", "001000", "010000", "010000"),
    "8": ("011110", "100001", "100001", "100001", "011110",
          "100001", "100001", "100001", "100001", "011110"),
    "9": ("011110", "100001", "100001", "100001", "100001",
          "011111", "000001", "000001", "000010", "011100"),
    " ": ("000000",) * 10,
}

# 3x5 for the date line, where four characters of 6x10 would never fit.
SMALL: Dict[str, Sequence[str]] = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("111", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("110", "101", "101", "101", "101"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "/": ("001", "001", "010", "100", "100"),
    "-": ("000", "000", "111", "000", "000"),
    ".": ("000", "000", "000", "000", "100"),
    ":": ("000", "010", "000", "010", "000"),
    " ": ("000", "000", "000", "000", "000"),
}

NAMED_COLORS: Dict[str, RGB] = {
    "white": (255, 255, 255),
    "red": (255, 40, 20),
    "green": (0, 255, 90),
    "blue": (0, 120, 255),
    "cyan": (0, 210, 255),
    "magenta": (255, 0, 160),
    "yellow": (255, 190, 0),
    "orange": (255, 90, 20),
    "amber": (255, 140, 0),
    "pink": (255, 80, 140),
    "purple": (170, 80, 255),
    "off": (0, 0, 0),
}


def parse_color(value: str) -> RGB:
    """Accept `#00d4ff`, `00d4ff`, `0,212,255`, or a name from NAMED_COLORS."""
    text = value.strip().lower()
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            raise ValueError(f"{value!r} needs exactly three comma-separated channels")
        try:
            rgb = tuple(int(p) for p in parts)
        except ValueError:
            raise ValueError(f"{value!r} has a non-numeric channel") from None
        if not all(0 <= c <= 255 for c in rgb):
            raise ValueError(f"{value!r} has a channel outside 0-255")
        return rgb  # type: ignore[return-value]
    hexed = text[1:] if text.startswith("#") else text
    if len(hexed) == 3:
        hexed = "".join(c * 2 for c in hexed)
    if len(hexed) != 6:
        raise ValueError(
            f"{value!r} is not a colour. Try #00d4ff, 0,212,255, or one of: "
            + ", ".join(sorted(NAMED_COLORS))
        )
    try:
        return (int(hexed[0:2], 16), int(hexed[2:4], 16), int(hexed[4:6], 16))
    except ValueError:
        raise ValueError(f"{value!r} is not valid hex") from None


def scale_color(color: RGB, factor: float) -> RGB:
    return tuple(max(0, min(255, round(c * factor))) for c in color)  # type: ignore[return-value]


@dataclass(frozen=True)
class Palette:
    time: RGB = (0, 210, 255)
    colon: RGB = (255, 255, 255)
    bar: RGB = (255, 90, 20)
    bar_track: RGB = (10, 14, 22)
    date: RGB = (255, 190, 0)
    pm: RGB = (255, 90, 140)
    background: RGB = (0, 0, 0)


@dataclass(frozen=True)
class FaceSettings:
    """The whole design surface. Every field is reachable from the CLI."""

    h24: bool = False
    seconds_bar: bool = True
    bar_height: int = 2
    blink_colon: bool = True
    pm_dot: bool = True
    leading_zero: bool = False
    show_date: bool = False
    date_format: str = "%m/%d"
    date_every: int = 20  # seconds of each minute given over to the date
    date_for: int = 5
    glow: float = 0.0
    palette: Palette = field(default_factory=Palette)

    def __post_init__(self) -> None:
        if not 0 <= self.bar_height <= HEIGHT:
            raise ValueError(f"bar_height must be 0-{HEIGHT}, got {self.bar_height}")
        if not 0.0 <= self.glow <= 1.0:
            raise ValueError(f"glow must be 0.0-1.0, got {self.glow}")
        if self.date_every <= 0:
            raise ValueError("date_every must be positive")
        if not 0 < self.date_for < self.date_every:
            raise ValueError("date_for must be positive and shorter than date_every")
        if self.show_date:
            if 60 % self.date_every:
                # The cycle is phased off `second`, so one that does not tile a
                # minute fuses two windows at every minute boundary and the date
                # sits there for twice as long as asked.
                raise ValueError(
                    f"date_every must divide 60 so the cycle tiles a minute, "
                    f"got {self.date_every}"
                )
            self._check_date_format()

    def _check_date_format(self) -> None:
        """Reject a date format now rather than mid-run, on the panel.

        `showing_date` only fires for a few seconds of each cycle, so a format
        that cannot render would otherwise wait until the first date window --
        after the radio is up and frames are streaming -- to raise. Probing every
        month, both day widths, both halves of the day and every weekday covers
        the whole variable surface of strftime rather than just this instant.
        """
        probes = [datetime(2024, month, day, hour, 5)
                  for month in range(1, 13) for day in (1, 28) for hour in (9, 21)]
        probes += [datetime(2024, 1, day) for day in range(1, 8)]  # Mon..Sun
        for probe in probes:
            rendered = probe.strftime(self.date_format)
            try:
                draw_small_text(blank(self.palette), rendered, 0, self.palette.date)
            except ValueError as exc:
                raise ValueError(
                    f"date_format {self.date_format!r} renders {rendered!r}: {exc}"
                ) from None


# ------------------------------------------------------------------
# Framebuffer
# ------------------------------------------------------------------


def blank(palette: Palette) -> Frame:
    return [[palette.background for _ in range(WIDTH)] for _ in range(HEIGHT)]


def put(frame: Frame, x: int, y: int, color: RGB) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        frame[y][x] = color


def draw_glyph(frame: Frame, rows: Sequence[str], x: int, y: int, color: RGB) -> None:
    for dy, bits in enumerate(rows):
        for dx, bit in enumerate(bits):
            if bit == "1":
                put(frame, x + dx, y + dy, color)


def text_width(text: str, glyph_w: int) -> int:
    return len(text) * glyph_w + max(0, len(text) - 1) * GAP if text else 0


def draw_small_text(frame: Frame, text: str, y: int, color: RGB, x: Optional[int] = None) -> None:
    """Draw with the 3x5 font, centred unless `x` is given.

    Refuses rather than clips. A date one glyph too wide would otherwise lose its
    first and last character off the edges and render a *different, plausible*
    date -- the worst possible failure for a clock.
    """
    unknown = sorted({c for c in text.upper() if c not in SMALL})
    if unknown:
        raise ValueError(
            f"no 3x5 glyph for {''.join(unknown)!r}. Available: "
            + "".join(sorted(SMALL))
        )
    text = text.upper()
    width = text_width(text, SMALL_W)
    if width > WIDTH:
        raise ValueError(
            f"{text!r} needs {width}px but the panel is {WIDTH} wide "
            f"(the 3x5 font fits {(WIDTH + GAP) // (SMALL_W + GAP)} characters)"
        )
    cursor = (WIDTH - width) // 2 if x is None else x
    for ch in text:
        draw_glyph(frame, SMALL[ch], cursor, y, color)
        cursor += SMALL_W + GAP


def apply_glow(frame: Frame, amount: float, background: RGB) -> Frame:
    """Bleed a fraction of each lit pixel into its dark neighbours.

    A real LED does this in the diffuser and it is most of why the firmware
    faces look softer than a naive bitmap blit. Only dark pixels receive light,
    so glyph strokes keep their edges instead of washing out.
    """
    if amount <= 0:
        return frame
    out = [row[:] for row in frame]
    for y in range(HEIGHT):
        for x in range(WIDTH):
            source = frame[y][x]
            if source == background:
                continue
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not (0 <= nx < WIDTH and 0 <= ny < HEIGHT):
                    continue
                if frame[ny][nx] != background:
                    continue  # never dull a lit pixel with its neighbour's spill
                spill = scale_color(source, amount)
                current = out[ny][nx]
                out[ny][nx] = tuple(  # type: ignore[assignment]
                    max(a, b) for a, b in zip(current, spill)
                )
    return out


# ------------------------------------------------------------------
# The face
# ------------------------------------------------------------------


def clock_text(when: datetime, settings: FaceSettings) -> str:
    """`HH:MM` for the panel. 12-hour renders 1-12, never 0, like every clock."""
    if settings.h24:
        hour = when.hour
    else:
        hour = when.hour % 12 or 12
    text = f"{hour:02d}" if (settings.h24 or settings.leading_zero) else f"{hour:d}"
    return f"{text}:{when.minute:02d}"


def time_layout_width(text: str) -> int:
    """Pixels a `H:MM` / `HH:MM` string occupies, colon and gaps included.

    Public because the interesting property -- that the widest possible face
    still fits 32 columns -- is worth asserting in a test rather than eyeballing.
    """
    digits = [c for c in text if c != ":"]
    return len(digits) * DIGIT_W + COLON_W + len(digits) * GAP


def showing_date(when: datetime, settings: FaceSettings) -> bool:
    if not settings.show_date:
        return False
    return (when.second % settings.date_every) < settings.date_for


def render(when: datetime, settings: Optional[FaceSettings] = None) -> Image.Image:
    """A `datetime` in, a 32x16 RGB image out."""
    settings = settings or FaceSettings()
    palette = settings.palette
    frame = blank(palette)

    bar_rows = settings.bar_height if settings.seconds_bar else 0
    body_h = HEIGHT - bar_rows

    if showing_date(when, settings):
        text = when.strftime(settings.date_format)
        draw_small_text(frame, text, (body_h - SMALL_H) // 2, palette.date)
    else:
        _draw_time(frame, when, settings, body_h)

    if bar_rows:
        _draw_seconds_bar(frame, when, settings, bar_rows)

    frame = apply_glow(frame, settings.glow, palette.background)
    return to_image(frame)


def _draw_time(frame: Frame, when: datetime, settings: FaceSettings, body_h: int) -> None:
    palette = settings.palette
    text = clock_text(when, settings)
    digits = [c for c in text if c != ":"]

    x = max(0, (WIDTH - time_layout_width(text)) // 2)
    y = max(0, (body_h - DIGIT_H) // 2)

    split = text.index(":")
    for index, ch in enumerate(digits):
        draw_glyph(frame, DIGITS[ch], x, y, palette.time)
        x += DIGIT_W + GAP
        if index == split - 1:
            lit = palette.colon
            if settings.blink_colon and when.second % 2:
                lit = scale_color(palette.colon, 0.18)
            for dy in (2, 3, 6, 7):
                put(frame, x, y + dy, lit)
                put(frame, x + 1, y + dy, lit)
            x += COLON_W + GAP

    if settings.pm_dot and not settings.h24 and when.hour >= 12:
        # Anchored to the digit block rather than to the panel corner. The widest
        # layout is 30px drawn from x=1, so columns 0 and 31 are free at every
        # size -- but rows 0-1 are not, once a taller seconds bar pushes the
        # digits up into them.
        for dy in (0, 1):
            put(frame, WIDTH - 1, y + dy, palette.pm)


def _draw_seconds_bar(frame: Frame, when: datetime, settings: FaceSettings, rows: int) -> None:
    palette = settings.palette
    # Include microseconds so a once-a-second repaint still lands on a fresh
    # column rather than repeating one when a write runs slightly early.
    progress = (when.second + when.microsecond / 1_000_000) / 60.0
    lit = int(round(progress * WIDTH))
    for y in range(HEIGHT - rows, HEIGHT):
        for x in range(WIDTH):
            put(frame, x, y, palette.bar if x < lit else palette.bar_track)


def to_image(frame: Frame) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    img.putdata([frame[y][x] for y in range(HEIGHT) for x in range(WIDTH)])
    return img


def preview_sheet(
    moments: Sequence[datetime],
    settings: Optional[FaceSettings] = None,
    *,
    scale: int = 10,
    per_row: int = 4,
    pad: int = 6,
) -> Image.Image:
    """A contact sheet of rendered faces, for judging a design without the panel."""
    if not moments:
        raise ValueError("nothing to preview")
    settings = settings or FaceSettings()
    cols = min(per_row, len(moments))
    rows = (len(moments) + cols - 1) // cols
    cell_w, cell_h = WIDTH * scale, HEIGHT * scale
    sheet = Image.new(
        "RGB",
        (cols * cell_w + (cols + 1) * pad, rows * cell_h + (rows + 1) * pad),
        (24, 24, 28),
    )
    for index, moment in enumerate(moments):
        tile = render(moment, settings).resize((cell_w, cell_h), Image.NEAREST)
        col, row = index % cols, index // cols
        sheet.paste(tile, (pad + col * (cell_w + pad), pad + row * (cell_h + pad)))
    return sheet
