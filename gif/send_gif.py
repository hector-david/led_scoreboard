"""Send a GIF to the 32x16 iPixel panel.

    py send_gif.py pacman.gif              # prep + send in one step
    py send_gif.py pacman_32x16.gif --raw  # send an already-prepared GIF
    py send_gif.py pacman.gif --dry-run    # build and check the packets, no BLE

Anything not already 32x16 is run through prep_gif first, so the usual call is
just `py send_gif.py <any gif>`.

Every check that can be done without the panel is done before the radio is
touched, because the failure that costs an evening is a half-written slot, not
a rejected file.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from bleak.exc import BleakError
from PIL import Image

from ipixel import (
    ACK_SUCCESS,
    DEFAULT_SLOT,
    HEIGHT,
    ONE_WINDOW_MAX,
    WIDTH,
    Panel,
    PanelError,
    build_windows,
    describe_windows,
)
from prep_gif import colour_count, positive_float, prep_gif

# Refuse outright above this. instructions.md reports ~500KB transfers taking
# minutes, and every extra window is another chance for the link to drop
# mid-upload with a partly-written slot behind it.
HARD_MAX_BYTES = 64 * 1024


def preflight(data: bytes, *, width: int, height: int, slot: int) -> Tuple[List[str], List[str]]:
    """Validate a GIF payload. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    if not data.startswith((b"GIF87a", b"GIF89a")):
        errors.append("not a GIF (bad magic)")
        return errors, warnings
    if not data.endswith(b"\x3b"):
        errors.append("missing GIF trailer byte -- the file is truncated")
        return errors, warnings

    try:
        im = Image.open(io.BytesIO(data))
        size = im.size
        # info['loop'] belongs to the first frame; read it before seeking away.
        loop = im.info.get("loop", None)
        frames = getattr(im, "n_frames", 1)
        durations = []
        for i in range(frames):
            im.seek(i)
            im.load()  # actually decode, so a truncated frame is caught here
            durations.append(int(im.info.get("duration") or 0))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"GIF will not decode: {exc}")
        return errors, warnings

    if size != (width, height):
        errors.append(
            f"GIF is {size[0]}x{size[1]}, panel is {width}x{height}. "
            "The panel needs an exact match -- run prep_gif.py."
        )
    if frames < 1:
        errors.append("no frames")
    if any(d <= 0 for d in durations):
        errors.append(
            f"{sum(1 for d in durations if d <= 0)} frame(s) have a zero delay, "
            "which can spin a simple firmware decoder"
        )
    if loop not in (0, None) and loop < 1:
        warnings.append(f"unusual loop count {loop}")
    if loop is None:
        warnings.append("no NETSCAPE loop block -- the panel may play the animation once")

    if len(data) > HARD_MAX_BYTES:
        errors.append(f"{len(data)} bytes exceeds the {HARD_MAX_BYTES} byte ceiling")
    elif len(data) > ONE_WINDOW_MAX:
        warnings.append(
            f"{len(data)} bytes needs more than one 12KB window. Continuation windows "
            "(option byte 0x02) have not been exercised on this panel."
        )

    if not 0 <= slot <= 255:
        errors.append(f"slot {slot} does not fit in a byte -- it cannot be sent")
    elif slot == 0:
        warnings.append(
            "slot 0 is undocumented for this unit; slot 1 is the value your working "
            "scoreboard has always used"
        )
    elif slot > 100:
        warnings.append(f"slot {slot} is outside the documented 1-100 range")
    return errors, warnings


async def send(data: bytes, *, slot: int, name: Optional[str], brightness: Optional[int]) -> int:
    kwargs = {"name": name} if name else {}
    try:
        async with Panel(**kwargs) as panel:
            if brightness is not None:
                print(f"Setting brightness to {brightness} (proven command, confirms the link)...")
                await panel.set_brightness(brightness)
            ack = await panel.send_gif_bytes(data, slot=slot)
    except (PanelError, BleakError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    if ack.status != ACK_SUCCESS:
        print(
            f"\nerror: transfer ended on status {ack.status:#04x}, not 0x03 (success)",
            file=sys.stderr,
        )
        return 1

    print(f"\nPanel acknowledged: {ack}")
    print(
        "If the panel acknowledged but stayed dark, this firmware probably does not "
        "implement the GIF command (0x0003).\nFall back to: py play_frames.py <gif>"
    )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Send a GIF to the 32x16 iPixel LED panel.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("source", type=Path, help="GIF to send (any size; prepped automatically)")
    p.add_argument("--slot", type=int, default=DEFAULT_SLOT, help="destination slot/buffer byte (0-255)")
    p.add_argument("--raw", action="store_true", help="send as-is, skip prep_gif")
    p.add_argument("--dry-run", action="store_true", help="build and validate packets, no BLE")
    p.add_argument("--brightness", type=int, help="set brightness first (0-100)")
    p.add_argument("--name", help="override the BLE name to scan for")
    p.add_argument("--fps", type=positive_float, default=12.5)
    p.add_argument("--colors", type=colour_count, default=64)
    p.add_argument("--mode", choices=["band", "crop", "fit", "stretch"], default="band")
    p.add_argument("--band-scale", type=float, default=1.5)
    p.add_argument("--palette", choices=["global", "per-frame"], default="global",
                   help="try per-frame if the panel acknowledges but renders nothing")
    p.add_argument("--save-prepped", type=Path, help="also write the prepared GIF here")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = p.parse_args(argv)

    if not args.source.exists():
        print(f"error: no such file: {args.source}", file=sys.stderr)
        return 1

    if args.raw:
        data = args.source.read_bytes()
        print(f"Sending {args.source} unmodified ({len(data)} bytes).")
    else:
        report = prep_gif(
            args.source,
            args.save_prepped,
            width=WIDTH,
            height=HEIGHT,
            fps=args.fps,
            colors=args.colors,
            mode=args.mode,
            band_scale=args.band_scale,
            palette_mode=args.palette,
        )
        data = report["data"]
        print(
            f"Prepared {args.source.name}: {report['frames']} frames, "
            f"{report['duration_ms']} ms, {report['colors']} colours, {report['bytes']} bytes"
        )
        if args.save_prepped:
            print(f"  written to {args.save_prepped}")

    errors, warnings = preflight(data, width=WIDTH, height=HEIGHT, slot=args.slot)
    for w in warnings:
        print(f"  warning: {w}")
    if errors:
        for e in errors:
            print(f"  error: {e}", file=sys.stderr)
        print("\nRefusing to send.", file=sys.stderr)
        return 1

    windows = build_windows(data, is_gif=True, slot=args.slot)
    print(f"\n{len(data)} byte payload -> {len(windows)} window(s), slot {args.slot}:")
    print(describe_windows(windows))

    if args.dry_run:
        print("\nDry run: nothing was sent.")
        return 0

    if not args.yes:
        print(
            "\nClose the iPixel phone app first -- only one BLE central can hold the link."
        )
        reply = input(f"Send to slot {args.slot}? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    return asyncio.run(
        send(data, slot=args.slot, name=args.name, brightness=args.brightness)
    )


if __name__ == "__main__":
    raise SystemExit(main())
