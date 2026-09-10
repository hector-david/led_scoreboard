"""Animate by streaming PNG frames, using only the command this panel is known to accept.

The GIF command (0x0003) has never been exercised on this unit -- every packet it
has actually acknowledged used the PNG command (0x0002). If send_gif.py gets a
clean acknowledgement but the panel stays dark, that firmware most likely has no
GIF support, and this is the way to get the animation on screen anyway.

The trade-off: the animation lives on the host, so it stops when this script
stops, and it holds the BLE link for as long as it runs. A real GIF upload plays
from the panel's own storage. But every byte here travels a path this panel has
already ACKed with `05 00 02 00 03`.

    py play_frames.py pacman.gif
    py play_frames.py pacman.gif --loops 3 --fps 10
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path
from typing import List, Tuple

from PIL import Image

from bleak.exc import BleakError

from ipixel import ACK_FAIL, DEFAULT_SLOT, HEIGHT, WIDTH, Panel, PanelError, build_windows
from prep_gif import colour_count, global_palette, positive_float, prep_gif

# Largest single write proven on this panel. Frames are palettised until they fit.
PROVEN_PACKET_MAX = 472


def encode_frames(report: dict, colors: int) -> Tuple[List[bytes], List[int]]:
    """Palettise every frame and encode as PNG, small enough for one write each.

    A shared palette keeps colours stable frame to frame; per-frame palettes
    shimmer. Colour count drops until every frame's packet fits the proven size.
    """
    frames = report["rgb_frames"]
    durations = report["durations"]

    while True:
        palette_img = Image.new("P", (1, 1))
        palette_img.putpalette(global_palette(frames, colors, "fastoctree"))

        packets: List[bytes] = []
        for f in frames:
            buf = io.BytesIO()
            f.quantize(palette=palette_img, dither=Image.Dither.NONE).save(
                buf, format="PNG", compress_level=9, optimize=True
            )
            packets.append(buf.getvalue())

        biggest = 15 + max(len(p) for p in packets)
        if biggest <= PROVEN_PACKET_MAX or colors <= 8:
            if biggest > PROVEN_PACKET_MAX:
                print(
                    f"  note: largest packet is {biggest} bytes, above the {PROVEN_PACKET_MAX} "
                    "byte size proven on this panel; it will be chunked."
                )
            return packets, durations
        colors = max(8, colors // 2)


async def play(packets: List[bytes], durations: List[int], *, slot: int, loops: int, name) -> int:
    kwargs = {"name": name} if name else {}
    frame_windows = [build_windows(p, is_gif=False, slot=slot)[0] for p in packets]

    try:
        async with Panel(verbose=True, **kwargs) as panel:
            panel.verbose = False  # per-frame ACK logging would drown the console
            print(
                f"Playing {len(packets)} frames"
                f"{f', {loops} loop(s)' if loops > 0 else ', until Ctrl-C'}..."
            )
            count = 0
            # One absolute deadline, so a slow write is caught up on rather than
            # added to the start of every following frame.
            deadline = time.perf_counter()
            while loops <= 0 or count < loops:
                for window, delay in zip(frame_windows, durations):
                    await panel.write_raw(window)
                    for ack in panel.drain_acks():
                        if ack.status == ACK_FAIL:
                            raise PanelError(f"panel rejected a frame: {ack}")
                    deadline += delay / 1000.0
                    slack = deadline - time.perf_counter()
                    if slack > 0:
                        await asyncio.sleep(slack)
                    else:
                        deadline = time.perf_counter()  # falling behind; resynchronise
                count += 1
    except asyncio.CancelledError:
        print("\nStopped.")
    except (PanelError, BleakError) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    return 0


def slot_byte(value: str) -> int:
    n = int(value)
    if not 0 <= n <= 255:
        raise argparse.ArgumentTypeError(f"slot must be 0-255, got {value}")
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Animate a GIF by streaming PNG frames over the proven 0x0002 command.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("source", type=Path)
    p.add_argument("--loops", type=int, default=0, help="0 or less = forever, until Ctrl-C")
    p.add_argument("--slot", type=slot_byte, default=DEFAULT_SLOT)
    p.add_argument("--fps", type=positive_float, default=12.5)
    p.add_argument("--colors", type=colour_count, default=32, help="starting palette size")
    p.add_argument("--mode", choices=["band", "crop", "fit", "stretch"], default="band")
    p.add_argument("--band-scale", type=float, default=1.5)
    p.add_argument("--name", help="override the BLE name to scan for")
    args = p.parse_args(argv)

    if not args.source.exists():
        print(f"error: no such file: {args.source}", file=sys.stderr)
        return 1

    report = prep_gif(
        args.source,
        None,
        width=WIDTH,
        height=HEIGHT,
        fps=args.fps,
        colors=max(args.colors, 8),
        mode=args.mode,
        band_scale=args.band_scale,
    )
    packets, durations = encode_frames(report, args.colors)
    print(
        f"{args.source.name}: {len(packets)} frames, {sum(durations)} ms per loop, "
        f"packets {15 + min(map(len, packets))}-{15 + max(map(len, packets))} bytes"
    )
    print("Close the iPixel phone app first -- only one BLE central can hold the link.")

    try:
        return asyncio.run(
            play(packets, durations, slot=args.slot, loops=args.loops, name=args.name)
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
