"""Offline checks. No panel, no radio, no pytest.

    py test_clock.py

The packet vectors below are not self-generated: they are the frames four
independent implementations of this dialect emit for the same inputs, plus the
worked examples in info.md. That is the only thing standing between a correct
clock and one that is confidently an hour wrong, so it is worth pinning.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta
from typing import Callable, List, Tuple

from clockface import (
    DIGITS,
    HEIGHT,
    SMALL,
    WIDTH,
    FaceSettings,
    Palette,
    apply_glow,
    clock_text,
    parse_color,
    render,
    showing_date,
    time_layout_width,
)
from ipixel_clock import (
    STYLE_MAX,
    PanelError,
    ClockSettings,
    DeviceInfo,
    brightness_cmd,
    clock_mode_cmd,
    power_cmd,
    rotation_cmd,
    set_time_cmd,
)


class Failure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def check_hex(actual: bytes, expected: str, label: str) -> None:
    want = bytes.fromhex(expected)
    if actual != want:
        raise Failure(f"{label}\n    got      {actual.hex(' ')}\n    expected {want.hex(' ')}")


# ------------------------------------------------------------------
# Protocol
# ------------------------------------------------------------------


def test_set_time_matches_published_frames() -> None:
    check_hex(
        set_time_cmd(datetime(2026, 9, 10, 14, 30, 5)),
        "08 00 01 80 0e 1e 05 00",
        "set_time 14:30:05",
    )
    # From info.md: the hour is sent 0-23 even on a 12-hour face. Converting
    # here is the classic bug -- the panel would be wrong every afternoon.
    check_hex(set_time_cmd(datetime(2026, 9, 10, 13, 5, 0)), "08 00 01 80 0d 05 00 00", "13:05")
    check_hex(set_time_cmd(datetime(2026, 9, 10, 23, 5, 0)), "08 00 01 80 17 05 00 00", "23:05")
    check_hex(set_time_cmd(datetime(2026, 9, 10, 0, 0, 0)), "08 00 01 80 00 00 00 00", "midnight")


def test_clock_mode_matches_published_frames() -> None:
    when = datetime(2026, 9, 10, 14, 30, 5)  # a Thursday
    check_hex(
        clock_mode_cmd(when, style=1, h24=True, show_date=True),
        "0b 00 06 01 01 01 01 1a 09 0a 04",
        "style 1, 24h, date",
    )
    check_hex(
        clock_mode_cmd(when, style=0, h24=False, show_date=True),
        "0b 00 06 01 00 00 01 1a 09 0a 04",
        "style 0, 12h, date (info.md)",
    )
    check_hex(
        clock_mode_cmd(when, style=0, h24=True, show_date=True),
        "0b 00 06 01 00 01 01 1a 09 0a 04",
        "style 0, 24h, date (info.md)",
    )
    check_hex(
        clock_mode_cmd(when, style=7, h24=True, show_date=True),
        "0b 00 06 01 07 01 01 1a 09 0a 04",
        "style 7",
    )


def test_flags_are_separate_bytes_not_a_bitfield() -> None:
    """The other dialect packs these into one byte. Catch a regression to it."""
    when = datetime(2026, 9, 10, 14, 30, 5)
    packet = clock_mode_cmd(when, style=2, h24=True, show_date=True)
    check(packet[4] == 2, f"style must stand alone in byte 4, got {packet[4]:#04x}")
    check(packet[5] == 1, "format24 must be its own byte")
    check(packet[6] == 1, "show_date must be its own byte")
    check(len(packet) == 11, "iPixel clock mode is 11 bytes; 8 would be the iDotMatrix dialect")
    check(len(set_time_cmd(when)) == 8, "iPixel set_time is 8 bytes; 11 would be the other one")


def test_day_of_week_is_iso() -> None:
    """Monday=1 .. Sunday=7. `weekday()` would be off by one every single day."""
    monday = datetime(2026, 9, 7, 12, 0, 0)
    for offset, expected in enumerate([1, 2, 3, 4, 5, 6, 7]):
        day = monday + timedelta(days=offset)
        packet = clock_mode_cmd(day, style=0, h24=True, show_date=False)
        check(
            packet[10] == expected,
            f"{day:%A} should send dow {expected}, sent {packet[10]}",
        )
    check(monday.isoweekday() == 1, "sanity: 2026-09-07 is a Monday")


def test_length_prefix_counts_itself() -> None:
    when = datetime(2026, 9, 10, 14, 30, 5)
    packets = [
        ("set_time", set_time_cmd(when)),
        ("clock_mode", clock_mode_cmd(when, style=0, h24=False, show_date=False)),
        ("brightness", brightness_cmd(55)),
        ("rotation", rotation_cmd(2)),
        ("power", power_cmd(True)),
    ]
    for name, packet in packets:
        declared = packet[0] | (packet[1] << 8)
        check(
            declared == len(packet),
            f"{name} declares length {declared} but is {len(packet)} bytes",
        )


def test_brightness_matches_the_proven_command() -> None:
    # 05 00 04 80 <level> is the one command this panel has actually acked.
    check_hex(brightness_cmd(40), "05 00 04 80 28", "brightness 40")
    check_hex(brightness_cmd(100), "05 00 04 80 64", "brightness 100")
    check_hex(brightness_cmd(0), "05 00 04 80 00", "brightness 0")


def test_opcode_byte_order_is_pinned_everywhere() -> None:
    """A swapped lo/hi still has the right length, so length checks miss it."""
    check_hex(rotation_cmd(0), "05 00 06 80 00", "rotation 0 degrees")
    check_hex(rotation_cmd(2), "05 00 06 80 02", "rotation 180 degrees")
    check_hex(power_cmd(True), "05 00 07 01 01", "power on")
    check_hex(power_cmd(False), "05 00 07 01 00", "power off")
    # 0x8006 and 0x0107 differ only in which half is which; getting these two
    # right at the same time as set_time (0x8001) and clock mode (0x0106) is
    # what proves _short() is not quietly transposing the opcode.
    when = datetime(2026, 9, 10, 14, 30, 5)
    check(set_time_cmd(when)[2:4] == b"\x01\x80", "set_time opcode is 01 80")
    check(clock_mode_cmd(when)[2:4] == b"\x06\x01", "clock mode opcode is 06 01")
    check(brightness_cmd(1)[2:4] == b"\x04\x80", "brightness opcode is 04 80")
    check(rotation_cmd(1)[2:4] == b"\x06\x80", "rotation opcode is 06 80")
    check(power_cmd(True)[2:4] == b"\x07\x01", "power opcode is 07 01")


def test_builders_refuse_bad_input() -> None:
    when = datetime(2026, 9, 10, 14, 30, 5)
    cases: List[Tuple[str, Callable[[], object]]] = [
        ("style above the range", lambda: clock_mode_cmd(when, style=STYLE_MAX + 1)),
        ("negative style", lambda: clock_mode_cmd(when, style=-1)),
        ("year before 2000", lambda: clock_mode_cmd(datetime(1999, 1, 1), style=0)),
        ("year after 2099", lambda: clock_mode_cmd(datetime(2100, 1, 1), style=0)),
        ("brightness over 100", lambda: brightness_cmd(101)),
        ("brightness under 0", lambda: brightness_cmd(-1)),
        ("rotation over 3", lambda: rotation_cmd(4)),
    ]
    for label, call in cases:
        try:
            call()
        except ValueError:
            continue
        raise Failure(f"{label} should have raised ValueError")


def test_device_info_never_guesses() -> None:
    info = DeviceInfo(bytes.fromhex("0b 00 01 80 82 1e 05 00 00 01 00"))
    check(info.size == (32, 16), f"0x82 is a 32x16 panel, got {info.size}")
    check(info.matches_this_panel, "0x82 should match this repo's panel")

    # The vendor parser silently calls an unknown byte 64x64. This one must not.
    unknown = DeviceInfo(bytes.fromhex("0b 00 01 80 ff 00 00 00 00 01 00"))
    check(unknown.size is None, f"unknown device byte must be None, got {unknown.size}")
    check(not unknown.matches_this_panel, "unknown must not claim to match")

    short = DeviceInfo(b"\x05\x00\x01\x80")
    check(short.device_byte is None, "a truncated reply has no device byte")
    check(short.size is None, "a truncated reply has no size")

    check(DeviceInfo.looks_like_reply(_ack("0b 00 01 80 82")), "should recognise a set-time reply")
    check(
        not DeviceInfo.looks_like_reply(_ack("05 00 06 01 01")),
        "a clock-mode ack is not a set-time reply",
    )


def _ack(hexed: str):
    from ipixel import Ack

    return Ack(bytes.fromhex(hexed))


def test_clock_settings_summary_is_honest() -> None:
    check("12-hour" in ClockSettings(h24=False).summary(), "12-hour should be named")
    check("24-hour" in ClockSettings(h24=True).summary(), "24-hour should be named")


# ------------------------------------------------------------------
# The custom face
# ------------------------------------------------------------------


def test_twelve_hour_text_never_shows_zero() -> None:
    twelve = FaceSettings(h24=False)
    check(clock_text(datetime(2026, 9, 10, 0, 0), twelve) == "12:00", "midnight is 12, not 0")
    check(clock_text(datetime(2026, 9, 10, 12, 0), twelve) == "12:00", "noon is 12")
    check(clock_text(datetime(2026, 9, 10, 13, 5), twelve) == "1:05", "13:05 is 1:05")
    check(clock_text(datetime(2026, 9, 10, 23, 59), twelve) == "11:59", "23:59 is 11:59")

    twentyfour = FaceSettings(h24=True)
    check(clock_text(datetime(2026, 9, 10, 0, 0), twentyfour) == "00:00", "24h midnight is 00:00")
    check(clock_text(datetime(2026, 9, 10, 13, 5), twentyfour) == "13:05", "24h keeps 13")

    padded = FaceSettings(h24=False, leading_zero=True)
    check(clock_text(datetime(2026, 9, 10, 9, 5), padded) == "09:05", "leading zero requested")


def test_every_minute_of_the_day_fits_the_panel() -> None:
    """The widest face must still fit 32 columns, or glyphs clip silently."""
    for settings in (
        FaceSettings(h24=True),
        FaceSettings(h24=False),
        FaceSettings(h24=False, leading_zero=True),
    ):
        for hour in range(24):
            for minute in range(60):
                text = clock_text(datetime(2026, 9, 10, hour, minute), settings)
                width = time_layout_width(text)
                check(
                    width <= WIDTH,
                    f"{text!r} needs {width}px, panel is {WIDTH}px wide",
                )


def test_render_stays_inside_the_panel() -> None:
    settings = FaceSettings(h24=True, show_date=True, glow=0.3)
    for hour in (0, 9, 12, 23):
        for second in (0, 3, 30, 59):
            img = render(datetime(2026, 9, 10, hour, 37, second), settings)
            check(img.size == (WIDTH, HEIGHT), f"render produced {img.size}")


def test_nothing_is_clipped_at_the_edges() -> None:
    """A glyph pushed off-canvas would be dropped by `put` without complaint."""
    settings = FaceSettings(h24=True, seconds_bar=False, blink_colon=False)
    img = render(datetime(2026, 9, 10, 23, 58), settings)
    pixels = img.load()
    lit_columns = [x for x in range(WIDTH) for y in range(HEIGHT) if pixels[x, y] != (0, 0, 0)]
    check(bool(lit_columns), "23:58 should light something")
    text = clock_text(datetime(2026, 9, 10, 23, 58), settings)
    expected_left = (WIDTH - time_layout_width(text)) // 2
    check(
        min(lit_columns) >= expected_left,
        f"content starts at {min(lit_columns)}, left of the computed {expected_left}",
    )
    check(max(lit_columns) <= WIDTH - 1, "content runs past the right edge")


def test_seconds_bar_fills_over_a_minute() -> None:
    settings = FaceSettings(seconds_bar=True, bar_height=2, blink_colon=False)
    palette = settings.palette
    widths = []
    for second in (0, 15, 30, 45, 59):
        img = render(datetime(2026, 9, 10, 14, 37, second), settings)
        pixels = img.load()
        widths.append(sum(1 for x in range(WIDTH) if pixels[x, HEIGHT - 1] == palette.bar))
    check(widths == sorted(widths), f"bar should grow monotonically, got {widths}")
    check(widths[0] == 0, f"the bar starts empty, got {widths[0]}")
    check(widths[-1] >= WIDTH - 2, f"the bar should be nearly full at :59, got {widths[-1]}")


def _pm_pixels(hour: int, **kwargs) -> List[Tuple[int, int]]:
    """Pixels the PM marker adds, found by differencing against pm_dot=False.

    Position-independent on purpose: the marker is anchored to the digit block,
    which moves with `bar_height`, so pinning it to a fixed corner would be
    testing the test.
    """
    when = datetime(2026, 9, 10, hour, 5, 30)
    with_dot = render(when, FaceSettings(pm_dot=True, **kwargs)).load()
    without = render(when, FaceSettings(pm_dot=False, **kwargs)).load()
    return [
        (x, y)
        for x in range(WIDTH)
        for y in range(HEIGHT)
        if with_dot[x, y] != without[x, y]
    ]


def test_pm_dot_only_in_the_afternoon_and_only_on_12h() -> None:
    base = dict(h24=False, seconds_bar=False, blink_colon=False)
    check(not _pm_pixels(11, **base), "11am must not show the PM marker")
    check(bool(_pm_pixels(12, **base)), "noon is PM")
    check(bool(_pm_pixels(23, **base)), "11pm is PM")
    check(not _pm_pixels(0, **base), "midnight is AM")
    check(
        not _pm_pixels(23, h24=True, seconds_bar=False, blink_colon=False),
        "a 24-hour face has no AM/PM to mark",
    )


def test_pm_dot_never_overwrites_a_digit() -> None:
    """It used to sit in the corner, which a tall seconds bar pushes digits into."""
    for bar_height in range(0, 7):
        when = datetime(2026, 9, 10, 12, 5, 30)
        kwargs = dict(
            h24=False, seconds_bar=True, bar_height=bar_height,
            leading_zero=True, blink_colon=False,
        )
        without = render(when, FaceSettings(pm_dot=False, **kwargs)).load()
        changed = _pm_pixels_at(when, kwargs)
        check(bool(changed), f"bar_height {bar_height}: the PM marker vanished")
        for x, y in changed:
            check(
                without[x, y] == (0, 0, 0),
                f"bar_height {bar_height}: PM marker overwrote a lit pixel at {x},{y}",
            )


def _pm_pixels_at(when: datetime, kwargs: dict) -> List[Tuple[int, int]]:
    with_dot = render(when, FaceSettings(pm_dot=True, **kwargs)).load()
    without = render(when, FaceSettings(pm_dot=False, **kwargs)).load()
    return [
        (x, y)
        for x in range(WIDTH)
        for y in range(HEIGHT)
        if with_dot[x, y] != without[x, y]
    ]


def test_date_window_is_a_slice_of_each_cycle() -> None:
    settings = FaceSettings(show_date=True, date_every=20, date_for=5)
    shown = [s for s in range(60) if showing_date(datetime(2026, 9, 10, 14, 37, s), settings)]
    check(shown == [0, 1, 2, 3, 4, 20, 21, 22, 23, 24, 40, 41, 42, 43, 44], f"got {shown}")
    check(
        not showing_date(datetime(2026, 9, 10, 14, 37, 0), FaceSettings(show_date=False)),
        "date must stay off when it was not asked for",
    )


def test_glow_never_dulls_a_lit_pixel() -> None:
    settings = FaceSettings(glow=0.0, seconds_bar=False, blink_colon=False)
    plain = render(datetime(2026, 9, 10, 14, 37), settings).load()
    glowing = render(
        datetime(2026, 9, 10, 14, 37),
        FaceSettings(glow=0.5, seconds_bar=False, blink_colon=False),
    ).load()
    for x in range(WIDTH):
        for y in range(HEIGHT):
            if plain[x, y] != (0, 0, 0):
                check(
                    glowing[x, y] == plain[x, y],
                    f"glow changed a lit pixel at {x},{y}: {plain[x, y]} -> {glowing[x, y]}",
                )


def test_glow_lights_neighbours() -> None:
    frame = [[(0, 0, 0) for _ in range(WIDTH)] for _ in range(HEIGHT)]
    frame[8][16] = (200, 100, 50)
    out = apply_glow(frame, 0.5, (0, 0, 0))
    check(out[8][16] == (200, 100, 50), "the source pixel is untouched")
    check(out[8][15] == (100, 50, 25), f"neighbour should be half-lit, got {out[8][15]}")
    check(out[7][16] == (100, 50, 25), "the pixel above should be half-lit")
    check(out[6][16] == (0, 0, 0), "glow reaches one pixel, not two")


def test_colour_parsing() -> None:
    check(parse_color("#00d4ff") == (0, 212, 255), "hex with hash")
    check(parse_color("00d4ff") == (0, 212, 255), "bare hex")
    check(parse_color("#0df") == (0, 221, 255), "three-digit hex expands")
    check(parse_color("0,212,255") == (0, 212, 255), "comma triple")
    check(parse_color("CYAN") == parse_color("cyan"), "names are case-insensitive")
    for bad in ("nope", "#12345", "1,2", "300,0,0", "1,2,x"):
        try:
            parse_color(bad)
        except ValueError:
            continue
        raise Failure(f"parse_color({bad!r}) should have raised")


def test_face_settings_reject_nonsense() -> None:
    for label, call in (
        ("glow over 1", lambda: FaceSettings(glow=1.5)),
        ("negative glow", lambda: FaceSettings(glow=-0.1)),
        ("bar taller than the panel", lambda: FaceSettings(bar_height=HEIGHT + 1)),
        ("date_for >= date_every", lambda: FaceSettings(date_for=20, date_every=20)),
        ("zero date_every", lambda: FaceSettings(date_every=0)),
        # A cycle that does not tile a minute fuses two windows at :59/:00 and
        # leaves the date up for twice as long as asked.
        ("date_every not dividing 60", lambda: FaceSettings(show_date=True, date_every=11)),
    ):
        try:
            call()
        except ValueError:
            continue
        raise Failure(f"{label} should have raised ValueError")


def test_over_wide_date_formats_are_refused_up_front() -> None:
    """Clipping a date renders a different, plausible date. Refuse instead."""
    for fmt in ("%Y-%m-%d", "%A", "%d %B %Y"):
        try:
            FaceSettings(show_date=True, date_format=fmt)
        except ValueError:
            continue
        raise Failure(f"date_format {fmt!r} does not fit 32px and should have raised")
    for fmt in ("%m/%d", "%b %d", "%H:%M"):
        FaceSettings(show_date=True, date_format=fmt)  # must not raise


def test_bad_date_glyphs_are_refused_up_front() -> None:
    """A comma has no 3x5 glyph, and the date path only runs a few seconds a cycle."""
    try:
        FaceSettings(show_date=True, date_format="%m/%d, %y")
    except ValueError as exc:
        check("','" in str(exc) or "," in str(exc), f"the message should name the comma: {exc}")
        return
    raise Failure("a date format with no glyph should have raised at construction")


def test_date_validation_probes_every_month_and_weekday() -> None:
    """`%b` is fine in some months and not others; validating only 'now' misses it."""
    try:
        FaceSettings(show_date=True, date_format="%A %d")
    except ValueError:
        return
    raise Failure("'%A %d' overflows for the longer weekday names and should have raised")


def test_fonts_are_well_formed() -> None:
    for name, table, width, height in (("DIGITS", DIGITS, 6, 10), ("SMALL", SMALL, 3, 5)):
        for ch, rows in table.items():
            check(
                len(rows) == height,
                f"{name}[{ch!r}] has {len(rows)} rows, expected {height}",
            )
            for index, row in enumerate(rows):
                check(
                    len(row) == width,
                    f"{name}[{ch!r}] row {index} is {len(row)} wide, expected {width}",
                )
                check(
                    set(row) <= {"0", "1"},
                    f"{name}[{ch!r}] row {index} has something other than 0/1",
                )
    for digit in "0123456789":
        check(digit in DIGITS, f"DIGITS is missing {digit}")
        check(digit in SMALL, f"SMALL is missing {digit}")


def test_date_formats_render() -> None:
    settings = FaceSettings(show_date=True, date_format="%b %d")
    img = render(datetime(2026, 9, 10, 14, 37, 0), settings)
    check(img.size == (WIDTH, HEIGHT), "a month-name date should still render")
    try:
        render(datetime(2026, 9, 10, 14, 37, 0), FaceSettings(show_date=True, date_format="%c"))
    except ValueError:
        return  # a full locale date has characters the 3x5 font does not carry
    # If it did render, that is fine too -- the point is that it must not draw
    # garbage silently, and draw_small_text raises on an unknown glyph.


def test_palette_is_configurable() -> None:
    hot = Palette(time=(255, 0, 0), colon=(255, 0, 0), bar=(0, 255, 0), bar_track=(0, 0, 0))
    img = render(
        datetime(2026, 9, 10, 14, 37, 30),
        FaceSettings(palette=hot, seconds_bar=True, blink_colon=False, pm_dot=False),
    )
    colors = {c for _, c in img.getcolors(maxcolors=4096)}
    check((255, 0, 0) in colors, "the digit colour should appear")
    check((0, 255, 0) in colors, "the bar colour should appear")


# ------------------------------------------------------------------
# The Zelda face
# ------------------------------------------------------------------


def test_zelda_layout_fills_the_panel_exactly() -> None:
    """The row budget is the whole design; a bad edit must not go unnoticed."""
    import zelda_clockface as z

    check(z.STRIP_TOP + z.STRIP_H == z.HEIGHT, "the strip must end at the last row")
    check(z.BAR_ROW == z.DIGIT_H + 1, "one gap row between the digits and the bar")
    check(z.STRIP_H >= 5, "the 3x5 date font needs five rows")
    widest = 4 * z.DIGIT_W + z.COLON_W + 4 * 1
    check(widest <= z.WIDTH, f"HH:MM needs {widest}px, panel is {z.WIDTH}")


def test_zelda_fonts_are_well_formed() -> None:
    import zelda_clockface as z

    for ch, rows in z.BOLD_DIGITS.items():
        check(len(rows) == z.DIGIT_H, f"digit {ch!r} has {len(rows)} rows")
        for i, row in enumerate(rows):
            check(len(row) == z.DIGIT_W, f"digit {ch!r} row {i} is {len(row)} wide")
            check(
                set(row) <= {"0", "1", ".", "#"},
                f"digit {ch!r} row {i} uses something other than 0/1/./#",
            )
    for digit in "0123456789":
        check(digit in z.BOLD_DIGITS, f"missing digit {digit}")
    lit = lambda rows: sum(1 for r in rows for c in r if c not in z.DARK)
    for ch, rows in z.BOLD_DIGITS.items():
        check(lit(rows) > 0, f"digit {ch!r} renders nothing -- wrong lit/dark alphabet?")
    # The 3x5 font is shared from clockface, and the bottom line's 32px budget
    # assumes every glyph in it is exactly SMALL_W wide.
    for ch, rows in SMALL.items():
        check(
            all(len(r) == z.SMALL_W for r in rows),
            f"SMALL[{ch!r}] is not {z.SMALL_W} wide -- the strip budget assumes it is",
        )


def test_zelda_bottom_line_shows_date_and_weekday_together() -> None:
    """One line, both halves, every second -- no alternation any more."""
    import zelda_clockface as z

    settings = z.ZeldaSettings()
    when = datetime(2026, 9, 11, 23, 59)
    for second in range(60):
        left, right = z.bottom_text(when.replace(second=second), settings)
        check(left == "09/11", f"second {second}: date should always show, got {left!r}")
        check(right == "FRI", f"second {second}: weekday should always show, got {right!r}")


def test_zelda_bottom_line_fits_every_day_of_the_year() -> None:
    """It comes to 32px exactly at the widest, so measure rather than assume."""
    import zelda_clockface as z

    settings = z.ZeldaSettings()
    widest = 0
    base = datetime(2026, 1, 1, 13, 37)
    for day in range(366):
        when = base + timedelta(days=day)
        left, right = z.bottom_text(when, settings)
        width = z.strip_width(left, right)
        widest = max(widest, width)
        check(width <= z.TEXT_SLOT, f"{left} {right} needs {width}px, panel is {z.TEXT_SLOT}")
        pixels = z.render(when, settings).load()
        lit = [x for x in range(z.WIDTH) for y in range(z.STRIP_TOP, z.HEIGHT)
               if pixels[x, y] != (0, 0, 0)]
        check(bool(lit), f"{when:%m/%d} drew no bottom line")
        check(max(lit) < z.WIDTH, f"{when:%m/%d} ran past the right edge")
    check(widest == z.TEXT_SLOT, f"the widest line should fill the panel, got {widest}px")


def test_zelda_draws_no_emblems() -> None:
    """The Triforces are gone; only the date should light the bottom rows."""
    import zelda_clockface as z

    check(not hasattr(z, "TRIFORCE"), "the Triforce sprite should be gone")
    check(not hasattr(z, "CREST_W"), "the crest constants should be gone")
    settings = z.ZeldaSettings()
    pixels = z.render(datetime(2026, 9, 11, 23, 59, 47), settings).load()
    for x in range(z.WIDTH):
        for y in range(z.STRIP_TOP, z.HEIGHT):
            colour = pixels[x, y]
            check(
                colour in ((0, 0, 0), settings.palette.date),
                f"unexpected colour {colour} at {x},{y} -- only the date belongs here",
            )


def test_zelda_rejects_a_bottom_line_too_wide_for_the_panel() -> None:
    """Date plus weekday is 32px exactly, so anything wider must fail up front."""
    import zelda_clockface as z

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d"):
        try:
            z.ZeldaSettings(date_format=fmt)
        except ValueError:
            continue
        raise Failure(f"date_format {fmt!r} plus a weekday does not fit and should have raised")
    try:
        z.ZeldaSettings(weekday_format="%A")  # MONDAY .. WEDNESDAY
    except ValueError:
        pass
    else:
        raise Failure("weekday_format '%A' should not fit alongside the date")
    for label, kwargs in (("empty date", {"date_format": ""}),
                          ("empty weekday", {"weekday_format": "  "}),
                          ("bad directive", {"date_format": "%Q"})):
        try:
            z.ZeldaSettings(**kwargs)
        except ValueError:
            continue
        raise Failure(f"{label} should have raised")
    z.ZeldaSettings(date_format="%m/%d", weekday_format="%a")  # the default must fit


def test_zelda_strip_refuses_rather_than_running_off_the_edge() -> None:
    """Defence in depth: a format past the probe set must raise, not overflow."""
    import zelda_clockface as z

    settings = z.ZeldaSettings()
    object.__setattr__(settings, "date_format", "%m/%d/%Y")
    try:
        z.render(datetime(2026, 9, 11, 12, 0, 0), settings)
    except ValueError as exc:
        check("px" in str(exc), f"the message should give the width: {exc}")
        return
    raise Failure("an over-wide bottom line must raise from the renderer")


def test_zelda_glow_is_the_shared_implementation() -> None:
    """It used to be a local copy justified by a difference that did not exist."""
    import clockface
    import zelda_clockface as z

    check(z.apply_glow is clockface.apply_glow, "the glow should be the shared one")
    plain = z.render(datetime(2026, 9, 11, 23, 59, 47), z.ZeldaSettings(glow=0.0)).load()
    lit = z.render(datetime(2026, 9, 11, 23, 59, 47), z.ZeldaSettings(glow=0.4)).load()
    for x in range(z.WIDTH):
        for y in range(z.HEIGHT):
            if plain[x, y] != (0, 0, 0):
                check(lit[x, y] == plain[x, y], f"glow changed a lit pixel at {x},{y}")


def test_palette_defaults_match_the_named_colours() -> None:
    """The CLI defaults used to be named colours; the dataclass must agree."""
    palette = Palette()
    from clockface import NAMED_COLORS

    for field_name, name in (("time", "cyan"), ("bar", "orange"),
                             ("date", "yellow"), ("pm", "pink")):
        check(
            getattr(palette, field_name) == NAMED_COLORS[name],
            f"Palette.{field_name} is {getattr(palette, field_name)}, "
            f"but --{field_name}-color {name} gives {NAMED_COLORS[name]}",
        )


def test_zelda_twelve_hour_still_never_shows_zero() -> None:
    import zelda_clockface as z

    twelve = z.ZeldaSettings(h24=False, leading_zero=False)
    check(z.clock_text(datetime(2026, 9, 11, 0, 0), twelve) == "12:00", "midnight is 12")
    check(z.clock_text(datetime(2026, 9, 11, 13, 5), twelve) == "1:05", "13:05 is 1:05")
    twentyfour = z.ZeldaSettings(h24=True)
    check(z.clock_text(datetime(2026, 9, 11, 0, 0), twentyfour) == "00:00", "24h midnight")
    check(z.clock_text(datetime(2026, 9, 11, 23, 59), twentyfour) == "23:59", "the mockup's time")


def test_zelda_every_minute_fits_the_panel() -> None:
    import zelda_clockface as z

    for settings in (z.ZeldaSettings(h24=True), z.ZeldaSettings(h24=False, leading_zero=False)):
        for hour in range(24):
            for minute in range(60):
                text = z.clock_text(datetime(2026, 9, 11, hour, minute), settings)
                width = z.time_layout_width(text)
                check(width <= z.WIDTH, f"{text!r} needs {width}px, panel is {z.WIDTH}")


def _bar_pixels(when: datetime, settings) -> int:
    import zelda_clockface as z

    pixels = z.render(when, settings).load()
    return sum(1 for x in range(z.WIDTH) if pixels[x, z.BAR_ROW] == settings.palette.bar)


def test_zelda_bar_has_its_own_colour_independent_of_the_digits() -> None:
    """The bar used to inherit --color. It has its own identity now."""
    import custom_clock
    import zelda_clockface as z

    stock = z.ZeldaPalette()
    check(stock.bar == (0, 255, 0), f"the bar should be green, got {stock.bar}")
    check(stock.bar != stock.time, "the bar must not match the digits")
    check(stock.bar != stock.date, "nor the date line below it")

    parser = custom_clock.build_parser()
    plain = z.build_settings(parser.parse_args(["--face", "zelda"]))
    check(plain.palette.bar == stock.bar, "the default bar should be the stock green")

    recoloured = z.build_settings(parser.parse_args(["--face", "zelda", "--color", "amber"]))
    check(
        recoloured.palette.bar == stock.bar,
        f"--color must not drag the bar with it, got {recoloured.palette.bar}",
    )
    check(recoloured.palette.time != stock.time, "--color should still move the digits")

    asked = z.build_settings(parser.parse_args(["--face", "zelda", "--bar-color", "#00ff88"]))
    check(asked.palette.bar == (0, 255, 136), f"--bar-color should win, got {asked.palette.bar}")

    # And it must actually reach the panel: the bar row is red, the digits are not.
    pixels = z.render(datetime(2026, 9, 11, 14, 37, 30), plain).load()
    check(pixels[0, z.BAR_ROW] == stock.bar, "the lit bar should be green on screen")
    digit_colours = {pixels[x, y] for x in range(z.WIDTH) for y in range(z.DIGIT_H)}
    check(stock.bar not in digit_colours, "the bar colour must not appear among the digits")


def test_zelda_bar_steps_every_1875ms() -> None:
    """One pixel per completed 1.875s step, counting from the minute.

    The pixel must light when its step *finishes*. Rounding rather than
    flooring -- which is what this did originally -- lit the first pixel at
    0.94s, half a step early.
    """
    import zelda_clockface as z

    settings = z.ZeldaSettings()
    check(z.STEP_SECONDS == 1.875, f"the step should be 60/32, got {z.STEP_SECONDS}")
    base = datetime(2026, 9, 11, 14, 37)

    def at(seconds: float) -> int:
        whole = int(seconds)
        micro = int(round((seconds - whole) * 1_000_000))
        return _bar_pixels(base.replace(second=whole, microsecond=micro), settings)

    # Empty for the whole first step, then one pixel exactly on the boundary.
    check(at(0) == 0, "the bar starts empty at the minute")
    check(at(1.0) == 0, "still empty a second in")
    check(at(1.874) == 0, f"still empty just before the first step, got {at(1.874)}")
    check(at(1.875) == 1, f"one pixel exactly at 1.875s, got {at(1.875)}")
    check(at(3.749) == 1, f"still one just before the second step, got {at(3.749)}")
    check(at(3.75) == 2, f"two pixels at 3.75s, got {at(3.75)}")

    # Every boundary, all the way up.
    for step in range(z.WIDTH):
        moment = step * z.STEP_SECONDS
        if moment >= 60:
            break
        check(
            at(moment) == step,
            f"{moment}s into the minute should light {step} pixels, got {at(moment)}",
        )


def test_zelda_bar_tops_out_one_short_and_resets() -> None:
    """The 32nd step would land exactly on the rollover, so 31 is the maximum."""
    import zelda_clockface as z

    settings = z.ZeldaSettings()
    base = datetime(2026, 9, 11, 14, 37)
    check(_bar_pixels(base.replace(second=59, microsecond=999999), settings) == 31,
          "the last step of the minute shows 31 of 32")
    check(_bar_pixels(base.replace(minute=38, second=0), settings) == 0,
          "and the next minute starts empty again")

    counts = [_bar_pixels(base.replace(second=s), settings) for s in range(60)]
    check(counts == sorted(counts), f"the bar must never go backwards: {counts}")
    check(max(counts) == 31, f"it should top out at 31, got {max(counts)}")


def test_zelda_repaints_on_the_step_grid() -> None:
    """1 Hz would show a step up to a second late; the face asks for its own rate."""
    import math

    import zelda_clockface as z

    settings = z.ZeldaSettings()
    interval = z.tick_seconds(settings)
    check(interval == z.STEP_SECONDS, f"the bar's rate should drive repaints, got {interval}")
    check(60 % interval == 0, "a minute must be a whole number of steps")

    # The driver aligns its deadline to multiples of the interval since the
    # epoch; because 60 is a whole number of steps, that grid contains every
    # minute boundary too.
    for connect_at in (1757600000.4, 1757600017.91, 1757600059.999):
        deadline = math.floor(connect_at / interval) * interval + interval
        check(deadline > connect_at, "the first deadline must be in the future")
        for _ in range(40):
            offset = deadline % 60
            check(
                abs(offset / interval - round(offset / interval)) < 1e-9,
                f"repaint at second-of-minute {offset} is off the step grid",
            )
            deadline += interval

    check(z.tick_seconds(z.ZeldaSettings(blink_colon=True)) == 1.0,
          "a blinking colon still needs a repaint every second")
    check(z.tick_seconds(z.ZeldaSettings(seconds_bar=False)) == 60.0,
          "with nothing moving inside the minute, once a minute is enough")


def test_both_faces_expose_the_same_seam() -> None:
    """custom_clock.py drives faces through this contract and nothing else."""
    import custom_clock

    required = (
        "WIDTH", "HEIGHT", "render", "build_settings", "tick_seconds",
        "preview_moments", "preview_sheet", "preview_caption", "validation_moments",
    )
    for name, module in custom_clock.FACES.items():
        for attr in required:
            check(hasattr(module, attr), f"face {name!r} is missing {attr}")
        check(module.WIDTH == WIDTH and module.HEIGHT == HEIGHT,
              f"face {name!r} renders {module.WIDTH}x{module.HEIGHT}")


def test_face_settings_carry_what_the_driver_reads() -> None:
    """`drive` reads face.h24 and face.show_date to build the firmware fallback."""
    import custom_clock

    for name, module in custom_clock.FACES.items():
        settings = module.build_settings(_default_args())
        check(isinstance(settings.h24, bool), f"face {name!r} has no usable h24")
        check(isinstance(settings.show_date, bool), f"face {name!r} has no usable show_date")
        img = module.render(datetime(2026, 9, 11, 23, 59, 47), settings)
        check(img.size == (WIDTH, HEIGHT), f"face {name!r} rendered {img.size}")


def _default_args():
    """Exactly what `custom_clock.py` hands a face when no flags are passed.

    Built by running the real parser rather than hand-listing defaults, so a new
    flag cannot drift out of sync with this test.
    """
    import custom_clock

    return custom_clock.build_parser().parse_args([])


# ------------------------------------------------------------------
# The hand-back, against a stub panel
# ------------------------------------------------------------------


class _StubPanel:
    """Answers the two clock commands the way the real panel documents."""

    def __init__(self, clock_status: int = 0x01) -> None:
        self.clock_status = clock_status
        self.verbose = True
        self.events: List[str] = []

    async def __aenter__(self) -> "_StubPanel":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def send_png_bytes(self, data: bytes, slot: int = 0) -> None:
        self.events.append("frame")

    async def set_time(self, when=None, **kwargs) -> DeviceInfo:
        self.events.append("set_time")
        return DeviceInfo(bytes.fromhex("0b 00 01 80 82 1e 05 00 00 01 00"))

    async def set_clock_mode(self, when=None, *, settings):
        self.events.append("clock_mode")
        return _ack(f"05 00 06 01 {self.clock_status:02x}")

    async def show_clock(self, settings, when=None):
        return await self.set_time(when), await self.set_clock_mode(when, settings=settings)


def _drive(panel: "_StubPanel", **kwargs) -> int:
    """Run custom_clock.drive against a stub, with its console output swallowed."""
    import asyncio
    import contextlib
    import io as _io

    import custom_clock

    original, custom_clock.ClockPanel = custom_clock.ClockPanel, lambda **kw: panel
    try:
        options = dict(
            name=None, slot=0, brightness=None, duration=0.1,
            handback=True, retry_seconds=0.01,
        )
        options.update(kwargs)
        with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
            return asyncio.run(
                custom_clock.drive(FaceSettings(), ClockSettings(), **options)
            )
    finally:
        custom_clock.ClockPanel = original


def test_hand_back_runs_and_reports_success() -> None:
    panel = _StubPanel(clock_status=0x01)
    code = _drive(panel)
    check(panel.events[-2:] == ["set_time", "clock_mode"], f"got {panel.events}")
    check(code == 0, f"an accepted hand-back should exit 0, got {code}")


def test_a_refused_hand_back_is_not_reported_as_success() -> None:
    """The panel refuses with a status byte, not an exception. Exit code must show it."""
    panel = _StubPanel(clock_status=0x00)
    code = _drive(panel)
    check(panel.events[-1] == "clock_mode", "it should still have tried")
    check(code != 0, "a refused hand-back must not exit 0 -- the panel is left frozen")


def test_ctrl_c_still_hands_the_panel_back() -> None:
    """The whole point of taking SIGINT over from asyncio.run.

    Under plain `asyncio.run`, SIGINT cancels the task, and the hand-back in the
    `finally` would then be awaiting inside a cancelled task and never complete.
    """
    import asyncio
    import contextlib
    import io as _io
    import signal as _signal

    import custom_clock

    panel = _StubPanel()
    original, custom_clock.ClockPanel = custom_clock.ClockPanel, lambda **kw: panel
    before = _signal.getsignal(_signal.SIGINT)
    try:

        async def run():
            loop = asyncio.get_running_loop()
            loop.call_later(0.25, lambda: _signal.raise_signal(_signal.SIGINT))
            return await custom_clock.drive(
                FaceSettings(), ClockSettings(style=2),
                name=None, slot=0, brightness=None, duration=3600, handback=True,
            )

        with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
            code = asyncio.run(run())
    finally:
        custom_clock.ClockPanel = original
        _signal.signal(_signal.SIGINT, before)

    check("frame" in panel.events, "it should have drawn at least one frame first")
    check(
        panel.events[-2:] == ["set_time", "clock_mode"],
        f"Ctrl-C must still hand the panel back, got {panel.events}",
    )
    check(code == 0, f"a clean interrupt with a good hand-back exits 0, got {code}")


class _FlakyPanel(_StubPanel):
    """A panel that is absent for a while, or that drops the link mid-stream."""

    def __init__(self, *, fail_connects: int = 0, drop_after: Optional[int] = None) -> None:
        super().__init__()
        self.fail_connects = fail_connects
        self.drop_after = drop_after
        self.connects = 0
        self.sent = 0
        self.healed = False

    async def __aenter__(self) -> "_FlakyPanel":
        self.connects += 1
        self.sent = 0  # a fresh link starts clean
        if self.connects <= self.fail_connects:
            self.events.append("connect-fail")
            raise PanelError(f"LED_BLE not found (attempt {self.connects})")
        if self.connects > 1:
            self.healed = True
        self.events.append("connect")
        return self

    async def set_brightness(self, level: int) -> None:
        self.events.append("brightness")

    async def send_png_bytes(self, data: bytes, slot: int = 0) -> None:
        self.sent += 1
        if not self.healed and self.drop_after is not None and self.sent > self.drop_after:
            raise PanelError("write failed: device disconnected")
        self.events.append("frame")


def test_it_waits_for_a_panel_that_is_not_there_yet() -> None:
    """Nothing to connect to at startup must retry, not exit."""
    panel = _FlakyPanel(fail_connects=3)
    code = _drive(panel, duration=1.5, retry_seconds=0.01, brightness=50)
    check(panel.connects == 4, f"should have retried until it answered, got {panel.connects}")
    check(panel.events.count("connect-fail") == 3, f"got {panel.events}")
    check("frame" in panel.events, "it should have drawn once the panel appeared")
    check(panel.events[-2:] == ["set_time", "clock_mode"], "and still handed back")
    check(code == 0, f"a run that recovered should exit 0, got {code}")


def test_a_dropped_link_is_rebuilt_rather_than_fatal() -> None:
    """The whole point: losing the panel mid-run is a reconnect, not an exit."""
    panel = _FlakyPanel(drop_after=1)
    code = _drive(panel, duration=9.0, retry_seconds=0.01, brightness=50)
    check(panel.connects > 1, f"it should have reconnected, connected {panel.connects}x")
    check(
        panel.events.count("frame") > 1,
        f"it should have resumed drawing after reconnecting, got {panel.events.count('frame')}",
    )
    check(
        panel.events.count("brightness") == panel.connects,
        "brightness must be re-applied on each connect -- the panel may have rebooted",
    )
    check(panel.events[-2:] == ["set_time", "clock_mode"], "and still handed back")
    check(code == 0, f"a run that recovered should exit 0, got {code}")


def test_retry_logging_is_throttled() -> None:
    """A panel that is off for a day must not leave 17,000 lines behind."""
    logged = [n for n in range(1, 200) if custom_clock_should_log(n)]
    check(logged[:3] == [1, 2, 3], f"the first few attempts should be visible, got {logged[:3]}")
    check(len(logged) < 25, f"200 attempts should log far fewer than 200 lines, got {len(logged)}")
    check(24 in logged, "it should still say something roughly once a minute")


def custom_clock_should_log(attempt: int) -> bool:
    import custom_clock

    return custom_clock._should_log(attempt)


def test_duration_does_not_overshoot_a_static_face() -> None:
    """A face with nothing per-second ticks once a minute; the wait must be clamped."""
    import time as _time

    import clockface

    static = FaceSettings(seconds_bar=False, blink_colon=False, show_date=False)
    check(clockface.tick_seconds(static) == 60.0, "a static face should tick once a minute")

    panel = _StubPanel()
    started = _time.monotonic()
    _drive(panel, duration=1.0)
    elapsed = _time.monotonic() - started
    check(elapsed < 15.0, f"--duration 1 ran for {elapsed:.1f}s; the tick was not clamped")


# ------------------------------------------------------------------


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        name = test.__name__.replace("test_", "").replace("_", " ")
        try:
            test()
        except Failure as exc:
            failures += 1
            print(f"FAIL  {name}\n    {exc}")
        except Exception:  # noqa: BLE001 -- a crash is a failure too
            failures += 1
            print(f"ERROR {name}")
            traceback.print_exc()
        else:
            print(f"ok    {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
