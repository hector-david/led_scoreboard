"""Draw your own clock face on the panel, and hand the panel back when you stop.

    py custom_clock.py --preview sheet.png        # design it, no radio
    py custom_clock.py                            # push the face, live
    py custom_clock.py --color amber --no-bar --glow 0.25
    py custom_clock.py --duration 60              # run for a minute, then hand back
    py custom_clock.py --retry 10                 # wait 10s between reconnects
    py custom_clock.py --v 2.0                    # the version 2.0 face

Two faces ship: `default` (clockface.py) and `2.0` (the version 2.0 face in
zelda_clockface.py). Pick one with --v; each applies its own colours and clock
format, and the shared design flags override either. Each also sets its own
repaint rate -- the version 2.0 bar steps every 1.875s, so that face is redrawn
on a 1.875s grid rather than once a second.

It survives the panel going away. Unplug it, walk out of range, or let the phone
app steal the link, and this drops into a reconnect loop -- every 5 seconds,
forever, until the panel answers again -- then picks the face straight back up.
Only Ctrl-C, `--duration`, or a design that cannot render will end the run.

Read this before you rely on it
    A custom face cannot keep time on its own. There is no command in this
    protocol -- in any of the five independent reverse-engineerings of it -- to
    upload a clock face, a font, or a digit bitmap. The nine built-in faces are
    ROM assets picked by one index byte. So a face we draw ourselves is a
    picture, and a picture does not tick: whatever minute was last sent stays on
    screen forever once this script stops.

    That is why this tool hands the panel back. When it exits -- cleanly, on
    Ctrl-C, or on an error -- it re-sends the built-in clock commands, so the
    panel returns to a face that keeps correct time on its own. Custom design
    while this runs, a self-sufficient clock the rest of the time.

    If you want the panel right without anything running, that is `send_clock.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import math
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from bleak.exc import BleakError
from PIL import Image

import clockface
import zelda_clockface as v2_clockface
from clockface import HEIGHT, WIDTH, parse_color
from ipixel_clock import (
    ACK_ACCEPTED,
    DOCUMENTED_STYLE_MAX,
    STYLE_MAX,
    ClockPanel,
    ClockSettings,
    PanelError,
)

# Each face is a module exposing the same seam: build_settings, render,
# tick_seconds, preview_moments, validation_moments, preview_sheet. Adding a
# face means adding a module here, not editing the driver.
FACES = {"default": clockface, "2.0": v2_clockface}

# Slot 0 is "show now, do not store". It costs no EEPROM write cycles, cannot
# leave a half-written slot behind, and cannot brick the panel with bad content
# on the next boot. Repainting a numbered slot once a second would do all three.
LIVE_SLOT = 0

# Above this a frame stops fitting the single BLE window the rest of the repo
# is careful to stay inside. A 32x16 PNG is a few hundred bytes, so this only
# ever fires if something is badly wrong.
FRAME_WARN_BYTES = 4096

# A dropped frame is survivable on its own; three in a row means the link went
# away and the answer is to rebuild it, not to give up.
MAX_CONSECUTIVE_FAILURES = 3

# How long to wait between reconnection attempts. The panel gets unplugged,
# carried out of range, or taken by the phone app; all three come back.
RECONNECT_SECONDS = 5.0


def encode_png(img: Image.Image) -> bytes:
    """Same encoding the scoreboard has always used on this panel."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=9, optimize=True, icc_profile=None)
    return buf.getvalue()


async def hand_back(panel: ClockPanel, settings: ClockSettings) -> bool:
    """Return the panel to a clock that runs without us. True if it took.

    The reply is checked, not assumed. A style the panel's ROM does not have is
    refused with a normal notification carrying status 0, not an exception, and
    announcing a successful hand-back in that case would tell the user the exact
    opposite of what happened -- the panel would be left frozen on the last
    custom frame, which is the one failure this tool exists to prevent.
    """
    try:
        panel.verbose = True  # two frames, not a stream: let their acks show
        _info, ack = await panel.show_clock(settings)
        if ack.status != ACK_ACCEPTED:
            print(
                f"warning: the panel answered the clock-mode frame with {ack}, not state "
                f"{ACK_ACCEPTED}. It may still be showing the last custom frame, frozen "
                f"at {datetime.now():%H:%M}. Try --handback-style 0.",
                file=sys.stderr,
            )
            return False
        print(f"Handed back to the built-in clock ({settings.summary()}).")
        return True
    except (PanelError, BleakError, asyncio.TimeoutError) as exc:
        # Never let cleanup replace the error that actually stopped the run.
        print(f"warning: could not hand back to the built-in clock: {exc}", file=sys.stderr)
        return False


class _Interrupt:
    """Turn Ctrl-C into an event instead of a task cancellation.

    This matters more than it looks. `asyncio.run` answers SIGINT by cancelling
    the running task, which fires a `CancelledError` at whatever we are awaiting
    -- and then the hand-back in the `finally` would itself be awaiting inside a
    cancelled task. The one thing that must survive Ctrl-C is precisely the
    hand-back, so we take SIGINT over while the loop runs and hand it back to
    whoever had it on the way out. The first Ctrl-C asks for a clean stop and
    re-arms the default handler, so a second one still kills the process if the
    panel has stopped answering.
    """

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self._previous = None
        self._handler = None
        self._installed = False

    def __enter__(self) -> "_Interrupt":
        loop = asyncio.get_running_loop()

        def handler(_signum, _frame):
            loop.call_soon_threadsafe(self.event.set)
            if self._previous is not None:
                signal.signal(signal.SIGINT, signal.default_int_handler)

        try:
            self._previous = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, handler)
            self._handler = handler
            self._installed = True
        except ValueError:
            # Not the main thread; fall back to the default behaviour.
            self._installed = False
        return self

    def __exit__(self, *exc) -> None:
        # Only give the slot back if we still hold it. After a Ctrl-C the handler
        # has already re-armed the default, and reinstalling asyncio's own
        # handler over that would both outlive the loop it is bound to and let a
        # second Ctrl-C cancel the hand-back that runs next.
        if (
            self._installed
            and self._previous is not None
            and signal.getsignal(signal.SIGINT) is self._handler
        ):
            try:
                signal.signal(signal.SIGINT, self._previous)
            except ValueError:
                pass

    async def sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately on Ctrl-C."""
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self.event.wait(), seconds)
        except asyncio.TimeoutError:
            pass


def _should_log(attempt: int) -> bool:
    """Log the first few retries, then once a minute. A panel that is off for a
    day should not leave 17,000 identical lines in the console."""
    return attempt <= 3 or attempt % 12 == 0


async def _stream(
    panel: ClockPanel,
    faces,
    face,
    interrupt: "_Interrupt",
    *,
    slot: int,
    interval: float,
    started: float,
    duration: Optional[float],
) -> Tuple[str, int]:
    """Push frames over one connection. Returns (why it ended, frames sent).

    "link-lost" is the interesting one: it means hand this connection back to
    the supervisor to be re-established, not that the run is over.
    """
    frames = 0
    failures = 0
    # Align the repaint grid to the wall clock rather than to whenever the
    # connection happened to open. The version 2.0 bar steps every 60/32 seconds, and
    # 60 is a whole number of those steps, so multiples of the interval since
    # the epoch land on both the step boundaries and the minute -- meaning a
    # pixel appears when it is due instead of up to a full interval late.
    deadline = math.floor(time.time() / interval) * interval + interval
    checked_size = False

    while not interrupt.event.is_set():
        if duration is not None and time.monotonic() - started >= duration:
            return "duration", frames

        payload = encode_png(faces.render(datetime.now(), face))
        if not checked_size:
            checked_size = True
            if len(payload) > FRAME_WARN_BYTES:
                print(
                    f"  note: a frame is {len(payload)} bytes, larger than expected "
                    f"for {WIDTH}x{HEIGHT}",
                    file=sys.stderr,
                )
        try:
            await panel.send_png_bytes(payload, slot=slot)
            failures = 0
            frames += 1
        except (PanelError, BleakError) as exc:
            # One lost frame is a hiccup and not worth tearing the link down for.
            # Three in a row is the link, and reconnecting is the way back.
            failures += 1
            print(f"  frame failed: {exc}", file=sys.stderr)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                return "link-lost", frames

        # Absolute deadline, so a slow write is caught up on rather than added to
        # the front of every frame after it.
        deadline += interval
        wait = deadline - time.time()
        if duration is not None:
            # Never sleep past the end of the run. A static face ticks once a
            # minute, so an unclamped wait would turn `--duration 3` into 60s.
            wait = min(wait, started + duration - time.monotonic())
        await interrupt.sleep(wait)
        if deadline < time.time():
            deadline = time.time()  # fell behind; resynchronise

    return "interrupt", frames


async def drive(
    face,
    fallback: ClockSettings,
    *,
    faces=clockface,
    name: Optional[str],
    slot: int,
    brightness: Optional[int],
    duration: Optional[float],
    handback: bool,
    retry_seconds: float = RECONNECT_SECONDS,
) -> int:
    """Keep the custom face on the panel, across however many dropouts it takes.

    Losing the link is not an error here -- the panel gets unplugged, carried out
    of range, or grabbed by the phone app, and all three end the same way. The
    supervisor reconnects every `retry_seconds` forever, so the only things that
    end the run are Ctrl-C, `--duration`, or a design that cannot render.
    """
    kwargs = {"name": name} if name else {}
    interval = faces.tick_seconds(face)
    frames = 0
    started = time.monotonic()
    handed_back = False
    reconnecting = False
    attempt = 0

    with _Interrupt() as interrupt:
        while True:
            # A guard, not an exit announcement -- the two real exits below print.
            if interrupt.event.is_set() or (
                duration is not None and time.monotonic() - started >= duration
            ):
                break

            try:
                async with ClockPanel(**kwargs) as panel:
                    if reconnecting:
                        print(
                            "Reconnected." if not attempt
                            else f"Reconnected after {attempt} attempt(s)."
                        )
                        reconnecting = False
                        attempt = 0
                    # A panel that dropped may well have been power-cycled, so
                    # re-apply anything we set on it rather than assuming it stuck.
                    if brightness is not None:
                        await panel.set_brightness(brightness)

                    panel.verbose = False  # an ack per frame would drown the console
                    if not frames:
                        # Only on the way in. A process that reconnects all week
                        # should not repeat the banner every time.
                        print(
                            f"Drawing the custom face to slot {slot}, one frame every "
                            f"{interval:g}s. Ctrl-C to stop and hand the panel back."
                        )
                    reason, sent = await _stream(
                        panel, faces, face, interrupt,
                        slot=slot, interval=interval, started=started, duration=duration,
                    )
                    frames += sent

                    if reason in ("interrupt", "duration"):
                        if reason == "interrupt":
                            print("\nStopping.")
                        # Hand back while the link is still up -- once we leave
                        # this block the panel is gone.
                        if handback:
                            handed_back = await hand_back(panel, fallback)
                        break

                    reconnecting = True
                    print(
                        f"\nLost the panel after {frames} frame(s). Retrying every "
                        f"{retry_seconds:g}s until it answers -- Ctrl-C to stop.",
                        file=sys.stderr,
                    )
            except ValueError as exc:
                # A render failure is deterministic. Retrying would spin forever.
                print(f"\nerror: {exc}", file=sys.stderr)
                return 1
            except (PanelError, BleakError) as exc:
                attempt += 1
                if not reconnecting:
                    reconnecting = True
                    print(
                        f"\nCould not reach the panel. Retrying every {retry_seconds:g}s "
                        "until it answers -- Ctrl-C to stop.",
                        file=sys.stderr,
                    )
                if _should_log(attempt):
                    print(f"  attempt {attempt}: {exc}", file=sys.stderr)

            if interrupt.event.is_set():
                print("\nStopping.")
                break
            await interrupt.sleep(retry_seconds)

    print(f"{frames} frame(s) sent.")
    if not handback:
        print(
            f"Left the last frame on screen. It is frozen at {datetime.now():%H:%M} "
            "and will not update.",
            file=sys.stderr,
        )
        return 0
    if handed_back:
        return 0
    # Stopped without the link, so the panel is still showing whatever it had.
    print(
        "warning: stopped while disconnected, so the panel was never handed back. "
        "It is either frozen on the last custom frame or showing whatever it booted "
        "into. Run send_clock.py once it is reachable again.",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Split out from main so the defaults can be exercised in tests."""
    p = argparse.ArgumentParser(
        description="Render a custom clock face and push it to the 32x16 iPixel panel.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "The face only updates while this runs. On exit the panel is handed "
            "back to its own clock, which does not need a connection."
        ),
    )
    p.add_argument(
        "--v",
        choices=sorted(FACES),
        default="default",
        help="which face version to draw: 'default' or the version 2.0 face",
    )

    # Colour and tri-state flags default to None so each face can supply its own
    # look. Hard-coding one face's defaults here would mean `--v 2.0`
    # silently inherited the other face's palette and 12-hour clock.
    design = p.add_argument_group("design (shared; each face applies its own defaults)")
    design.add_argument("--color", type=parse_color, help="digit colour [face default]")
    design.add_argument("--colon-color", type=parse_color, help="defaults to the digit colour")
    design.add_argument("--bar-color", type=parse_color, help="seconds bar colour [face default]")
    design.add_argument("--date-color", type=parse_color, help="date line colour [face default]")
    design.add_argument("--pm-color", type=parse_color, help="PM marker colour [default face]")
    design.add_argument("--no-bar", action="store_true", help="drop the seconds bar")
    design.add_argument("--bar-height", type=int, default=2, help="bar rows (default face)")
    design.add_argument("--no-pm-dot", action="store_true", help="drop the PM marker")
    design.add_argument("--glow", type=float, default=0.0, help="LED bleed, 0.0-1.0")

    fmt = design.add_mutually_exclusive_group()
    fmt.add_argument("--24h", dest="h24", action="store_true", default=None, help="24-hour face")
    fmt.add_argument("--12h", dest="h24", action="store_false", default=None, help="12-hour face")
    blink = design.add_mutually_exclusive_group()
    blink.add_argument("--blink", dest="blink_colon", action="store_true", default=None,
                       help="blink the colon once a second")
    blink.add_argument("--no-blink", dest="blink_colon", action="store_false", default=None,
                       help="steady colon")
    zero = design.add_mutually_exclusive_group()
    zero.add_argument("--leading-zero", dest="leading_zero", action="store_true", default=None,
                      help="09:05 rather than 9:05")
    zero.add_argument("--no-leading-zero", dest="leading_zero", action="store_false", default=None,
                      help="9:05 rather than 09:05")

    design.add_argument("--date", action="store_true", help="alternate the date in (default face)")
    design.add_argument("--date-format", default="%m/%d", help="strftime for the date line")
    design.add_argument("--date-every", type=int, default=20, help="date cycle (default face)")
    design.add_argument("--date-for", type=int, default=5, help="date dwell (default face)")
    design.add_argument("--weekday-format", default="%a",
                        help="strftime for the weekday shown beside the date [version 2.0]")

    run = p.add_argument_group("running")
    run.add_argument("--preview", type=Path, help="write a contact sheet and exit")
    run.add_argument("--scale", type=int, default=10, help="preview magnification")
    run.add_argument("--duration", type=float, help="stop after this many seconds")
    run.add_argument(
        "--retry",
        type=float,
        default=RECONNECT_SECONDS,
        help="seconds between reconnection attempts after the link drops",
    )
    run.add_argument("--slot", type=int, default=LIVE_SLOT, help="0 = show now, do not store")
    run.add_argument("--brightness", type=int, help="set brightness first (0-100)")
    run.add_argument("--name", help="override the BLE name to scan for")
    run.add_argument(
        "--no-handback",
        action="store_true",
        help="leave the last frame frozen instead of restoring the built-in clock",
    )
    run.add_argument(
        "--handback-style", type=int, default=0, help=f"built-in face to restore, 0-{STYLE_MAX}"
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    faces = FACES[args.v]

    try:
        face = faces.build_settings(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not 0 <= args.handback_style <= STYLE_MAX:
        print(f"error: --handback-style must be 0-{STYLE_MAX}", file=sys.stderr)
        return 1
    if args.handback_style > DOCUMENTED_STYLE_MAX:
        print(
            f"  note: --handback-style {args.handback_style} is past the documented "
            f"0-{DOCUMENTED_STYLE_MAX} range. If the panel refuses it the face will stay "
            "frozen on the last custom frame instead of returning to the clock.",
            file=sys.stderr,
        )
    if args.brightness is not None and not 0 <= args.brightness <= 100:
        print("error: --brightness must be 0-100", file=sys.stderr)
        return 1
    if not 0 <= args.slot <= 255:
        print("error: --slot must fit in a byte (0-255)", file=sys.stderr)
        return 1

    # Validate the design by rendering before any radio is touched. Second 0 is
    # always inside the date window, so the date path is exercised here rather
    # than twenty seconds into a live run with the panel already connected.
    try:
        now = datetime.now()
        sample = encode_png(faces.render(now, face))
        for moment in faces.validation_moments(face, now):
            encode_png(faces.render(moment, face))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Face {args.v!r} renders to {len(sample)} bytes of PNG at "
        f"{faces.WIDTH}x{faces.HEIGHT}."
    )

    if args.preview:
        cases = faces.preview_caption(face)
        sheet = faces.preview_sheet(
            faces.preview_moments(face), face, scale=max(1, args.scale)
        )
        try:
            if args.preview.parent != Path(""):
                args.preview.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(args.preview)
        except (ValueError, OSError) as exc:
            # PIL picks the format from the extension, so a name it does not
            # recognise raises from deep inside it rather than here.
            print(f"error: could not write {args.preview}: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {args.preview} ({sheet.width}x{sheet.height}) -- {cases}.")
        return 0

    if args.slot != LIVE_SLOT:
        print(
            f"  warning: slot {args.slot} is a stored slot. Repainting it every "
            f"{faces.tick_seconds(face):g}s burns EEPROM write cycles and risks leaving bad "
            "content behind. Slot 0 shows immediately and stores nothing.",
            file=sys.stderr,
        )

    # The firmware fallback should look as much like the face it replaces as
    # the nine built-in styles allow.
    fallback = ClockSettings(
        style=args.handback_style, h24=face.h24, show_date=face.show_date
    )
    print("Close the iPixel phone app first -- only one BLE central can hold the link.")

    try:
        return asyncio.run(
            drive(
                face,
                fallback,
                faces=faces,
                name=args.name,
                slot=args.slot,
                brightness=args.brightness,
                duration=args.duration,
                handback=not args.no_handback,
                retry_seconds=args.retry,
            )
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
