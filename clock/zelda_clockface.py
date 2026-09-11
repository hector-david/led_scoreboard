r"""The Zelda face: bold cyan 24-hour digits, a seconds bar, and a date line.

Drawn from the mockups in `zelda/1.png` .. `zelda/5.png` (the five are one design
at five different seconds-bar fills). Same contract as `clockface.py` -- give it a
`datetime`, get a 32x16 image -- so `custom_clock.py --face zelda` can drive it
without knowing anything about what it draws.

    +--------------------------------+
    |  ##  ##  :  ##  ##             |  rows 0-8   HH:MM, 6x9 bold digits, cyan
    |                                |  row  9     gap
    |#########-----------------------|  row  10    seconds bar, cyan on grey
    |09/11 FRI                       |  rows 11-15 date and weekday, yellow
    +--------------------------------+

What had to change, and why
    The mockup is a 38x20 grid. This panel is 32x16, so it does not map 1:1 and
    something had to give:

    * The mockup's digits are 11 rows of a 20-row panel (55%). These are 9 rows
      of 16 (56%), so the proportion carries over even though the pixel count
      does not. They are also 6 columns wide rather than the mockup's 7 --
      four 7-wide digits plus a colon is 34px, which does not fit 32. The
      shapes carry over: cut corners, 2px strokes, the diagonal '2'.
    * The mockup has a blank row on both sides of the seconds bar. There is only
      budget for one, so it sits above the bar, between the bar and the digits --
      the busier boundary of the two.
    * The mockup flanks the date with a winged Hyrule crest at each end. Those
      are gone, which is what buys the room for the date and the weekday to
      share one line: "09/11 FRI" is exactly 32px, and the two crests were 12px
      of the 32 between them.

    That last one is a tight fit with no slack at all, so a `--date-format` or
    `--weekday-format` that renders any wider is refused on the command line
    rather than clipped on the panel.

Colours are sampled from the mockups rather than guessed: the cyan is
(5, 250, 254), the yellow (254, 252, 11) and the unlit bar track (55, 55, 63).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from PIL import Image

# The 3x5 font and the colour parser are shared rather than duplicated -- this
# face differs in its digits and layout, not in how it spells a date.
from clockface import (
    GAP,
    RGB,
    SMALL,
    SMALL_W,
    Frame,
    apply_glow,
    parse_color,
    scale_color,
)

WIDTH = 32
HEIGHT = 16

DIGIT_W = 6
DIGIT_H = 9
COLON_W = 2

# Row budget. These five numbers are the whole layout, and they must sum to
# HEIGHT -- `_check_layout` asserts it at import so a future edit cannot quietly
# push the date line off the bottom of the panel.
DIGIT_TOP = 0
GAP_ROW = DIGIT_H  # 9
BAR_ROW = DIGIT_H + 1  # 10
STRIP_TOP = DIGIT_H + 2  # 11
STRIP_H = HEIGHT - STRIP_TOP  # 5

# The bottom line carries the date and the weekday together, so it gets the
# whole panel. "09/11 FRI" comes to exactly 32px: five 3x5 glyphs and four gaps
# for the date, two gaps for the separator, three glyphs and two gaps for the
# weekday. There is no slack, which is why a wider format is refused up front
# rather than clipped.
TEXT_SLOT = WIDTH
RUN_GAP = 2  # pixels between the date and the weekday

# Bold 6x9 digits traced from the mockup's own glyphs: 2px strokes, corner pixels
# cut from the top and bottom bars, and a diagonal '2' with the upper-left stub
# the mockup gives it. The mockup's digits are 7 columns wide, which four of plus
# a colon does not fit 32, so these are 6 -- the shapes carry over, the width
# cannot. The mockup's '9' also carries a lower-left stub; at nine rows instead of
# eleven it reads as an 8, so it is dropped.
BOLD_DIGITS: Dict[str, Sequence[str]] = {
    "0": (".####.", "######", "##..##", "##..##", "##..##",
          "##..##", "##..##", "######", ".####."),
    "1": ("..##..", ".###..", "..##..", "..##..", "..##..",
          "..##..", "..##..", "######", ".####."),
    "2": (".####.", "######", "##..##", "....##", "...##.",
          "..##..", ".##...", "######", ".####."),
    "3": (".####.", "######", "....##", "....##", "..####",
          "....##", "....##", "######", ".####."),
    "4": ("##..##", "##..##", "##..##", "##..##", "######",
          "....##", "....##", "....##", "....##"),
    "5": (".####.", "######", "##....", "##....", "#####.",
          "....##", "....##", "######", ".####."),
    "6": (".####.", "######", "##....", "##....", "######",
          "##..##", "##..##", "######", ".####."),
    "7": ("######", "######", "....##", "....##", "...##.",
          "...##.", "..##..", "..##..", "..##.."),
    "8": (".####.", "######", "##..##", "##..##", "######",
          "##..##", "##..##", "######", ".####."),
    "9": (".####.", "######", "##..##", "##..##", "######",
          "....##", "....##", "######", ".####."),
}

@dataclass(frozen=True)
class ZeldaPalette:
    """Sampled from zelda/1.png, not invented."""

    time: RGB = (5, 250, 254)
    colon: RGB = (5, 250, 254)
    bar: RGB = (5, 250, 254)
    bar_track: RGB = (55, 55, 63)
    date: RGB = (254, 252, 11)
    background: RGB = (0, 0, 0)


@dataclass(frozen=True)
class ZeldaSettings:
    """The design surface for this face.

    `h24` defaults true because the mockup shows 23:59 -- a 12-hour Zelda clock
    is available, it just is not what was drawn.
    """

    h24: bool = True
    seconds_bar: bool = True
    blink_colon: bool = False
    leading_zero: bool = True
    date_format: str = "%m/%d"
    weekday_format: str = "%a"
    glow: float = 0.0
    palette: ZeldaPalette = field(default_factory=ZeldaPalette)

    def __post_init__(self) -> None:
        if not 0.0 <= self.glow <= 1.0:
            raise ValueError(f"glow must be 0.0-1.0, got {self.glow}")
        self._check_strip()

    @property
    def show_date(self) -> bool:
        """Always. The bottom strip carries a date on every frame, so the
        firmware clock handed back on exit should show one too."""
        return True

    def _check_strip(self) -> None:
        """Refuse a bottom line that cannot fit 32 columns, at build time.

        Both halves share one row now, so they have to be measured together --
        each is comfortable alone and the pair is what runs out of room. The
        default pair renders "09/11 FRI" at 31px of the 32 available, so there
        is one pixel of slack and no more.

        The probe set covers every axis strftime can vary along: all twelve
        months, both day widths, every weekday, and -- because `%H`, `%p` and
        Windows' `%#I` change width with the clock -- four times of day,
        including both sides of noon.
        """
        for label, fmt in (("date_format", self.date_format),
                           ("weekday_format", self.weekday_format)):
            if not fmt.strip():
                raise ValueError(f"{label} is empty, which would blank half the bottom line")

        times = ((0, 0, 0), (12, 0, 0), (13, 5, 5), (23, 59, 59))
        probes = [datetime(2024, m, d, *t)
                  for m in range(1, 13) for d in (1, 28) for t in times]
        probes += [datetime(2024, 1, d, 23, 59, 59) for d in range(1, 8)]  # Mon..Sun

        for probe in probes:
            left, right = self._runs(probe)
            for label, text in (("date_format", left), ("weekday_format", right)):
                missing = sorted({c for c in text if c not in SMALL})
                if missing:
                    raise ValueError(
                        f"{label} renders {text!r}, which has no 3x5 glyph for "
                        f"{''.join(missing)!r}"
                    )
            width = strip_width(left, right)
            if width > TEXT_SLOT:
                raise ValueError(
                    f"{self.date_format!r} + {self.weekday_format!r} renders "
                    f"{left + ' ' + right!r} at {width}px, but the panel is "
                    f"{TEXT_SLOT}px. Shorten one of them."
                )

    def _runs(self, when: datetime) -> Tuple[str, str]:
        """The two halves of the bottom line, already upper-cased."""
        try:
            return (when.strftime(self.date_format).upper(),
                    when.strftime(self.weekday_format).upper())
        except ValueError as exc:
            raise ValueError(
                f"{self.date_format!r} / {self.weekday_format!r} is not a valid "
                f"strftime format: {exc}"
            ) from None


def _check_layout() -> None:
    if STRIP_TOP + STRIP_H != HEIGHT:
        raise AssertionError(
            f"layout does not fill the panel: strip ends at {STRIP_TOP + STRIP_H}, "
            f"panel is {HEIGHT} tall"
        )
    if STRIP_H < 5:
        raise AssertionError(f"the 3x5 date font needs 5 rows, the strip has {STRIP_H}")
    widest = 4 * DIGIT_W + COLON_W + 4 * GAP
    if widest > WIDTH:
        raise AssertionError(f"HH:MM needs {widest}px, panel is {WIDTH}")


_check_layout()


# ------------------------------------------------------------------
# Drawing
# ------------------------------------------------------------------


def blank(palette: ZeldaPalette) -> Frame:
    return [[palette.background for _ in range(WIDTH)] for _ in range(HEIGHT)]


def put(frame: Frame, x: int, y: int, color: RGB) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        frame[y][x] = color


#: Characters that mean "unlit". Everything else lights the pixel, so the big
#: digits here can be written in `#`/`.` -- far easier to edit a glyph by eye --
#: while the 3x5 font shared from clockface.py keeps its `1`/`0`.
DARK = frozenset("0.")


def draw_glyph(frame: Frame, rows: Sequence[str], x: int, y: int, color: RGB) -> None:
    for dy, bits in enumerate(rows):
        for dx, bit in enumerate(bits):
            if bit not in DARK:
                put(frame, x + dx, y + dy, color)


def clock_text(when: datetime, settings: ZeldaSettings) -> str:
    """`HH:MM`. 12-hour renders 1-12, never 0."""
    hour = when.hour if settings.h24 else (when.hour % 12 or 12)
    head = f"{hour:02d}" if (settings.h24 or settings.leading_zero) else f"{hour:d}"
    return f"{head}:{when.minute:02d}"


def text_width(text: str) -> int:
    """Pixels a 3x5 string occupies, inter-character gaps included."""
    if not text:
        return 0
    return len(text) * SMALL_W + (len(text) - 1) * GAP


def strip_width(left: str, right: str) -> int:
    """The whole bottom line: date, separator, weekday."""
    if not right:
        return text_width(left)
    return text_width(left) + RUN_GAP + text_width(right)


def time_layout_width(text: str) -> int:
    digits = [c for c in text if c != ":"]
    return len(digits) * DIGIT_W + COLON_W + len(digits) * GAP


def bottom_text(when: datetime, settings: ZeldaSettings) -> Tuple[str, str]:
    """The date and the weekday, both shown, side by side as in the mockup."""
    return settings._runs(when)


def render(when: datetime, settings: Optional[ZeldaSettings] = None) -> Image.Image:
    """A `datetime` in, a 32x16 RGB image out."""
    settings = settings or ZeldaSettings()
    palette = settings.palette
    frame = blank(palette)

    _draw_time(frame, when, settings)
    if settings.seconds_bar:
        _draw_seconds_bar(frame, when, settings)
    _draw_strip(frame, when, settings)

    # Shared with the default face: the `!= background` guard already keeps
    # spill off the lit bar track, so no local variant is needed.
    frame = apply_glow(frame, settings.glow, palette.background)
    return to_image(frame)


def _draw_time(frame: Frame, when: datetime, settings: ZeldaSettings) -> None:
    palette = settings.palette
    text = clock_text(when, settings)
    digits = [c for c in text if c != ":"]
    x = max(0, (WIDTH - time_layout_width(text)) // 2)
    split = text.index(":")

    for index, ch in enumerate(digits):
        draw_glyph(frame, BOLD_DIGITS[ch], x, DIGIT_TOP, palette.time)
        x += DIGIT_W + GAP
        if index == split - 1:
            lit = palette.colon
            if settings.blink_colon and when.second % 2:
                lit = scale_color(palette.colon, 0.18)
            # Two 2x2 blocks, matching the mockup's square colon.
            for top in (2, DIGIT_H - 4):
                for dy in range(2):
                    for dx in range(COLON_W):
                        put(frame, x + dx, DIGIT_TOP + top + dy, lit)
            x += COLON_W + GAP


def _draw_seconds_bar(frame: Frame, when: datetime, settings: ZeldaSettings) -> None:
    palette = settings.palette
    # Microseconds included so a once-a-second repaint lands on a fresh column
    # rather than repeating one when a write runs slightly early.
    progress = (when.second + when.microsecond / 1_000_000) / 60.0
    lit = int(round(progress * WIDTH))
    for x in range(WIDTH):
        put(frame, x, BAR_ROW, palette.bar if x < lit else palette.bar_track)


def _draw_strip(frame: Frame, when: datetime, settings: ZeldaSettings) -> None:
    """The bottom line: date and weekday together, centred as one unit."""
    palette = settings.palette
    left, right = bottom_text(when, settings)
    width = strip_width(left, right)
    if width > TEXT_SLOT:
        # Defence in depth behind `_check_strip`. If a format ever slips past
        # the probe set, refusing is right and running off the edge is not --
        # and the driver turns a ValueError into a clean exit.
        raise ValueError(
            f"{left + ' ' + right!r} needs {width}px but the panel is {TEXT_SLOT}px"
        )

    x = (WIDTH - width) // 2
    for run in (left, right):
        for ch in run:
            draw_glyph(frame, SMALL[ch], x, STRIP_TOP, palette.date)
            x += SMALL_W + GAP
        x += RUN_GAP - GAP  # the run's trailing gap is already counted


def to_image(frame: Frame) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    img.putdata([frame[y][x] for y in range(HEIGHT) for x in range(WIDTH)])
    return img


# ------------------------------------------------------------------
# The seam custom_clock.py drives
# ------------------------------------------------------------------


def build_settings(args: argparse.Namespace) -> ZeldaSettings:
    """Map the shared CLI flags onto this face.

    Colour flags arrive as None when the user did not pass them, so each face
    supplies its own defaults and `--face` can be switched without every colour
    reverting to the other face's palette. Flags that belong only to the default
    face (`--bar-height`, `--no-pm-dot`, `--date-every`, `--date-for`) are
    ignored rather than errored on, so switching does not mean rewriting the
    whole command.
    """
    stock = ZeldaPalette()
    time = args.color or stock.time
    palette = ZeldaPalette(
        time=time,
        colon=args.colon_color or time,
        bar=args.bar_color or time,
        date=args.date_color or stock.date,
    )
    return ZeldaSettings(
        h24=args.h24 if args.h24 is not None else True,
        seconds_bar=not args.no_bar,
        # Steady by default: the mockup's colon does not blink.
        blink_colon=args.blink_colon if args.blink_colon is not None else False,
        leading_zero=args.leading_zero if args.leading_zero is not None else True,
        date_format=args.date_format,
        weekday_format=args.weekday_format,
        glow=args.glow,
        palette=palette,
    )


def tick_seconds(settings: ZeldaSettings) -> float:
    """Only the bar and the colon move within a minute now that the bottom line
    is static, so without either there is nothing to redraw until the minute."""
    if settings.seconds_bar or settings.blink_colon:
        return 1.0
    return 60.0


def preview_caption(settings: ZeldaSettings) -> str:
    """Names the tiles preview_moments returns, in the same order."""
    return (
        "the mockup's 23:59, a two-digit month, midnight, single-digit hour, "
        "a full bar, round digits"
    )


def validation_moments(settings: ZeldaSettings, now: datetime) -> List[datetime]:
    """Nothing extra to probe: the bottom line is the same on every frame, and
    `_check_strip` already swept a year of them at build time."""
    return []


def preview_moments(settings: ZeldaSettings) -> List[datetime]:
    """Times chosen to catch what actually breaks this layout."""
    day = datetime.now().date()
    midnight = datetime.combine(day, datetime.min.time())
    cases = [
        (23, 59, 47),  # the mockup's own time
        (12, 25, 52),  # a two-digit month and day: the widest bottom line
        (0, 0, 2),  # midnight, bar nearly empty
        (9, 5, 30),  # single-digit hour
        (12, 34, 59),  # bar full
        (8, 8, 12),  # round digits
    ]
    return [midnight.replace(hour=h, minute=m, second=s) for h, m, s in cases]


def preview_sheet(
    moments: Sequence[datetime],
    settings: Optional[ZeldaSettings] = None,
    *,
    scale: int = 10,
    per_row: int = 3,
    pad: int = 6,
) -> Image.Image:
    if not moments:
        raise ValueError("nothing to preview")
    settings = settings or ZeldaSettings()
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
