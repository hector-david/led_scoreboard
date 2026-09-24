"""Put the clock on the 32x16 iPixel panel and walk away.

    py send_clock.py                      # 12-hour clock, style 0, date off
    py send_clock.py --walk-styles        # try every face, keep the one you like
    py send_clock.py --style 3 --date --brightness 40
    py send_clock.py --dry-run            # build and print the packets, no radio

This is a send-it-once tool. It connects, sets the time, picks the face, and
disconnects. The panel renders the clock in its own firmware from its own
counter, so it keeps ticking with nothing connected -- that is the whole reason
to use the built-in clock instead of drawing one ourselves.

Two things it cannot fix, both structural:

  * The panel is timezone-blind. It is handed raw local wall-clock time and
    counts from there. Nothing in the protocol carries a UTC offset or a DST
    flag, so it will be an hour wrong from each DST transition until something
    re-runs this script.
  * There is no evidence of a battery-backed RTC, and good reason to think
    there isn't one (USB-powered board, no cell in any teardown, the vendor app
    re-syncs on every connect). Expect the time to be wrong after a power cut.

Both are answered the same way: run this again. It is idempotent and takes a few
seconds, so a daily scheduled task is the honest fix -- see README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from typing import List, Optional, Tuple

from bleak.exc import BleakError

import device_settings
from ipixel_clock import (
    ACK_ACCEPTED,
    DOCUMENTED_STYLE_MAX,
    HEIGHT,
    STYLE_MAX,
    WIDTH,
    ClockPanel,
    ClockSettings,
    DeviceInfo,
    PanelError,
    brightness_cmd,
    clock_mode_cmd,
    rotation_cmd,
    set_time_cmd,
)



def style_number(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"style must be a number, got {value!r}") from None
    if not 0 <= n <= STYLE_MAX:
        raise argparse.ArgumentTypeError(f"style must be 0-{STYLE_MAX}, got {n}")
    return n


def brightness_level(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"brightness must be a number, got {value!r}") from None
    if not 0 <= n <= 100:
        raise argparse.ArgumentTypeError(f"brightness must be 0-100, got {n}")
    return n


def parse_when(value: str) -> datetime:
    """`--at` exists so the packet builders can be exercised at a known time."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"could not read {value!r} as a date and time (try 2026-09-10T14:30:00)"
    )


def preflight(settings: ClockSettings, when: datetime) -> Tuple[List[str], List[str]]:
    """Everything that can be decided without the panel. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    try:
        clock_mode_cmd(
            when, style=settings.style, h24=settings.h24, show_date=settings.show_date
        )
        set_time_cmd(when)
    except ValueError as exc:
        errors.append(str(exc))

    if settings.style > DOCUMENTED_STYLE_MAX:
        warnings.append(
            f"style {settings.style} is past the documented 0-{DOCUMENTED_STYLE_MAX} range; "
            "the panel may ignore the command and keep the face it has"
        )
    if not settings.h24:
        warnings.append(
            "12-hour faces conventionally run 1-12, so midnight will most likely render "
            "as 12 rather than 0. There is no byte to change that."
        )
    return errors, warnings


def report(info: DeviceInfo) -> List[str]:
    """What the panel said about itself, and whether to believe the geometry."""
    lines = [f"Panel replied: {info}"]
    size = info.size
    if size is None:
        lines.append(
            f"  warning: device byte {info.device_byte:#04x} is not in the size table. "
            "Unknown, not assumed -- the clock is unaffected, but do not trust any "
            "auto-resize built on this byte."
        )
    elif not info.matches_this_panel:
        lines.append(
            f"  warning: that byte means a {size[0]}x{size[1]} panel, but this repo is "
            f"built for {WIDTH}x{HEIGHT}. The clock is firmware-rendered so it will still "
            "be correct; image and GIF uploads would be the wrong geometry."
        )
    return lines


async def walk_styles(
    panel: ClockPanel, settings: ClockSettings, when: datetime
) -> Optional[int]:
    """Show each face in turn and let the panel, not the docs, decide what exists.

    No two implementations of this protocol agree on the legal style range, and
    all of them say it depends on the panel. Looking is cheaper than arguing.
    """
    print(
        f"\nWalking styles 0-{STYLE_MAX} with {settings.summary()}.\n"
        "Look at the panel after each one.  y = keep it, Enter = next, "
        "q = abandon the walk and fall back to --style.\n"
    )
    for style in range(STYLE_MAX + 1):
        trial = ClockSettings(style=style, h24=settings.h24, show_date=settings.show_date)
        try:
            ack = await panel.set_clock_mode(when, settings=trial)
        except PanelError as exc:
            print(f"  style {style}: refused ({exc})")
            continue
        accepted = "" if ack.status == ACK_ACCEPTED else f"  (unusual ack: {ack})"
        try:
            answer = (
                await asyncio.to_thread(input, f"  style {style} is showing{accepted}  [y/N/q] ")
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            # No stdin, or the user gave up. Returning rather than raising is
            # load-bearing: the caller still sends a settled clock-mode frame,
            # so the panel is never left on a half-walked trial style.
            print("\n  no answer available -- stopping the walk.")
            return None
        if answer in ("y", "yes"):
            return style
        if answer in ("q", "quit"):
            return None
    print("\nReached the end of the range without a pick.")
    return None


async def run(
    settings: ClockSettings,
    when: Optional[datetime],
    *,
    name: Optional[str],
    brightness: Optional[int],
    rotate: Optional[int],
    walk: bool,
) -> int:
    kwargs = {"name": name} if name else {}
    try:
        async with ClockPanel(**kwargs) as panel:
            # Fresh clock for the real send: the time between argument parsing
            # and a completed BLE connection is easily fifteen seconds.
            stamp = when or datetime.now()

            if brightness is not None:
                print(f"Brightness -> {brightness} ({brightness_cmd(brightness).hex(' ')})")
                await panel.set_brightness(brightness)
            if rotate is not None:
                print(f"Rotation -> {rotate * 90} degrees ({rotation_cmd(rotate).hex(' ')})")
                await panel.set_rotation(rotate)

            print(f"Set time -> {stamp:%H:%M:%S} ({set_time_cmd(stamp).hex(' ')})")
            info = await panel.set_time(stamp)
            for line in report(info):
                print(line)

            if walk:
                picked = await walk_styles(panel, settings, stamp)
                if picked is None:
                    print(f"No pick; falling back to --style {settings.style}.")
                else:
                    settings = ClockSettings(
                        style=picked, h24=settings.h24, show_date=settings.show_date
                    )

            # Re-stamp only after a walk, which can take minutes and would
            # leave the date byte disagreeing with the time. On the ordinary
            # path `stamp` is seconds old, and comparing two `datetime.now()`
            # calls would differ by microseconds and send a pointless second
            # frame every single run.
            final = datetime.now() if (walk and when is None) else stamp
            if final.replace(microsecond=0) != stamp.replace(microsecond=0):
                print(f"Re-stamping -> {final:%H:%M:%S} (the walk took {(final - stamp).seconds}s)")
                await panel.set_time(final)
            else:
                final = stamp  # nothing moved; keep the date byte agreeing with it
            packet = clock_mode_cmd(
                final, style=settings.style, h24=settings.h24, show_date=settings.show_date
            )
            print(f"Clock mode -> {settings.summary()} ({packet.hex(' ')})")
            ack = await panel.set_clock_mode(final, settings=settings)
            if ack.status != ACK_ACCEPTED:
                print(
                    f"\nwarning: clock mode returned {ack}, not state 1. The face may not "
                    "have changed; the time was still set.",
                    file=sys.stderr,
                )
    except (PanelError, BleakError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nDone. The panel is running {settings.summary()} on its own clock.\n"
        "You can close this and unplug the PC -- the panel does not need it.\n"
        "\nRun this again after a power cut (the panel has no battery-backed clock)\n"
        "and after each DST change (the protocol carries no timezone)."
    )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Set the 32x16 iPixel panel's built-in clock, then disconnect.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="The panel keeps rendering the clock itself once this exits.",
    )
    p.add_argument("--style", type=style_number, default=0, help=f"clock face 0-{STYLE_MAX}")
    p.add_argument(
        "--walk-styles",
        action="store_true",
        help="show every face in turn and keep the one you pick",
    )
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument(
        "--24h", dest="h24", action="store_true", help="24-hour face (default is 12-hour)"
    )
    fmt.add_argument("--12h", dest="h24", action="store_false", help="12-hour face")
    p.set_defaults(h24=False)
    p.add_argument("--date", action="store_true", help="alternate the date with the time")
    p.add_argument("--brightness", type=brightness_level, help="set brightness first (0-100)")
    p.add_argument(
        "--rotate",
        type=int,
        choices=[0, 1, 2, 3],
        help="quarter turns: 0, 1=90, 2=180, 3=270 degrees",
    )
    p.add_argument("--at", type=parse_when, help="send this time instead of now (for testing)")
    p.add_argument(
        "--name", help="override the BLE name from settings.json for this run only"
    )
    p.add_argument("--dry-run", action="store_true", help="build and print packets, no BLE")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = p.parse_args(argv)

    # Which panel, decided before anything is built: a settings.json typo should
    # look like a settings.json typo, not like a panel that would not answer.
    try:
        panel_name = device_settings.device_name(args.name)
        panel_line = device_settings.describe(args.name)
    except device_settings.SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    settings = ClockSettings(style=args.style, h24=args.h24, show_date=args.date)
    when = args.at or datetime.now()

    errors, warnings = preflight(settings, when)
    for w in warnings:
        print(f"  note: {w}")
    if errors:
        for e in errors:
            print(f"  error: {e}", file=sys.stderr)
        print("\nRefusing to send.", file=sys.stderr)
        return 1

    print(f"\n{panel_line}")
    print(f"{settings.summary()}, clock set to {when:%Y-%m-%d %H:%M:%S} ({when:%A}):")
    print(f"  set time   {set_time_cmd(when).hex(' ')}")
    print(
        "  clock mode "
        + clock_mode_cmd(
            when, style=settings.style, h24=settings.h24, show_date=settings.show_date
        ).hex(" ")
    )
    if args.brightness is not None:
        print(f"  brightness {brightness_cmd(args.brightness).hex(' ')}")
    if args.rotate is not None:
        print(f"  rotation   {rotation_cmd(args.rotate).hex(' ')}")

    if args.dry_run:
        print("\nDry run: nothing was sent.")
        return 0

    if not args.yes:
        print("\nClose the iPixel phone app first -- only one BLE central can hold the link.")
        try:
            reply = input("Send to the panel? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(
                "\nAborted: no answer on stdin. Pass --yes to skip this prompt "
                "(a scheduled task needs it).",
                file=sys.stderr,
            )
            return 1
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    try:
        return asyncio.run(
            run(
                settings,
                args.at,
                name=panel_name,
                brightness=args.brightness,
                rotate=args.rotate,
                walk=args.walk_styles,
            )
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
