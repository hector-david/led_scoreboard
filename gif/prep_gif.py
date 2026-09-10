"""Turn any GIF into one the panel can actually display, using only Pillow.

This replaces the ffmpeg recipe in instructions.md, which cannot run here --
ffmpeg is not installed, and the `convert` on PATH is Windows' filesystem
converter, not ImageMagick. Everything below is the Pillow equivalent of
`fps=N,scale=W:H:flags=lanczos,palettegen,paletteuse=dither=none`.

Three things matter more than the resampling filter, and none are in the
original recipe:

1. Source frames are usually partial deltas. Decimating before compositing
   shreds the animation, so every frame is decoded fully composited first.
2. A per-frame adaptive palette makes static pixels shimmer between frames,
   which is very visible on LEDs. One global palette shared by all frames
   fixes it, and shrinks the file by dropping the local colour tables.
3. On a 2:1 panel a square source has no good aspect answer. `fit` letterboxes
   it into the middle 16x16 and wastes half the panel; the default here crops a
   band centred on wherever the animation actually is.

Usage
    py prep_gif.py pacman.gif                        # -> pacman_32x16.gif
    py prep_gif.py in.gif -o out.gif --fps 10 --colors 32
    py prep_gif.py in.gif --mode crop --preview sheet.png
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

try:  # allow both `py prep_gif.py` and `from gif import prep_gif`
    from ipixel import HEIGHT, ONE_WINDOW_MAX, WIDTH
except ImportError:  # pragma: no cover
    WIDTH, HEIGHT, ONE_WINDOW_MAX = 32, 16, 12 * 1024

QUANT_METHODS = {
    "fastoctree": Image.Quantize.FASTOCTREE,
    "mediancut": Image.Quantize.MEDIANCUT,
    "maxcoverage": Image.Quantize.MAXCOVERAGE,
}


# ------------------------------------------------------------------
# Decode / retime
# ------------------------------------------------------------------


def decode_frames(src) -> Tuple[List[Image.Image], List[int], int]:
    """Every frame, fully composited, as RGB.

    Pillow's sequential seek() applies each frame's disposal method and pastes
    the delta onto the running canvas, so this must not be combined with
    skipping frames.
    """
    im = Image.open(src)
    frames, durations = [], []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        rgb = im.convert("RGB")
        # A P-mode source drags info['transparency'] into the RGB copy as a
        # tuple, which later blows up GifImagePlugin's local header writer.
        rgb.info.pop("transparency", None)
        rgb.info.pop("background", None)
        frames.append(rgb)
        durations.append(int(im.info.get("duration") or 100))
    return frames, durations, int(im.info.get("loop", 0) or 0)


def resample_timeline(durations: Sequence[int], fps: float) -> Tuple[List[int], List[int]]:
    """Resample on the wall clock, then merge runs.

    Sampling by timestamp rather than by frame index is what keeps a source with
    uneven delays honest. Merging consecutive picks of the same source frame
    collapses a hold back into one long frame instead of several duplicates, so
    both the frame count and the total runtime stay right.
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    step = max(10, int(round(1000.0 / fps / 10.0)) * 10)  # GIF delays are 10ms units
    starts = np.cumsum([0] + list(durations[:-1]))
    total = int(sum(durations))
    if total <= 0:
        return [0], [step]

    picks: List[int] = []
    t = 0
    while t < total:
        picks.append(int(np.searchsorted(starts, t, side="right") - 1))
        t += step

    out_idx: List[int] = []
    out_dur: List[int] = []
    for j in picks:
        if out_idx and out_idx[-1] == j:
            out_dur[-1] += step
        else:
            out_idx.append(j)
            out_dur.append(step)

    # The last sample always claims a whole step, which can run the animation
    # past the source's own length. Give the overshoot back so the loop keeps
    # the original wall-clock.
    overshoot = t - total
    if overshoot > 0:
        out_dur[-1] = max(10, ((out_dur[-1] - overshoot) // 10) * 10)
    return out_idx, out_dur


# ------------------------------------------------------------------
# Geometry
# ------------------------------------------------------------------


def content_rows(frames: Sequence[Image.Image], threshold: int = 8) -> Tuple[int, int]:
    """Rows that are ever non-black across the whole animation."""
    mask = None
    for f in frames:
        row = (np.asarray(f).max(axis=2) > threshold).any(axis=1)
        mask = row if mask is None else (mask | row)
    ys = np.nonzero(mask)[0]
    if not len(ys):
        return 0, frames[0].height
    return int(ys[0]), int(ys[-1]) + 1


def fit_frame(img, w, h, mode, band_px, band_cy, resample=Image.LANCZOS):
    if mode == "fit":
        s = min(w / img.width, h / img.height)
        nw, nh = max(1, round(img.width * s)), max(1, round(img.height * s))
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        canvas.paste(img.resize((nw, nh), resample), ((w - nw) // 2, (h - nh) // 2))
        return canvas
    if mode == "crop":
        s = max(w / img.width, h / img.height)
        nw, nh = max(w, round(img.width * s)), max(h, round(img.height * s))
        r = img.resize((nw, nh), resample)
        left, top = (nw - w) // 2, (nh - h) // 2
        return r.crop((left, top, left + w, top + h))
    if mode == "band":
        bh = max(1, min(img.height, int(band_px)))
        y0 = max(0, min(img.height - bh, int(round(band_cy - bh / 2.0))))
        return img.crop((0, y0, img.width, y0 + bh)).resize((w, h), resample)
    if mode == "stretch":
        return img.resize((w, h), resample)
    raise ValueError(f"unknown mode {mode!r}")


# ------------------------------------------------------------------
# Palette
# ------------------------------------------------------------------


def global_palette(frames: Sequence[Image.Image], colors: int, quant: str) -> List[int]:
    """One palette for the whole animation, with pure black pinned to index 0.

    Black at index 0 matters: it becomes the GIF background index, so the LEDs
    behind it are genuinely off rather than showing the nearest dark colour.
    """
    pixels = np.concatenate([np.asarray(f).reshape(-1, 3) for f in frames])
    strip = Image.fromarray(pixels.reshape(-1, 1, 3).astype(np.uint8))
    quantized = strip.quantize(colors=colors, method=QUANT_METHODS[quant], dither=Image.Dither.NONE)

    flat = list(quantized.getpalette())[: colors * 3]
    triples = [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)]

    # A GIF colour table must have a power-of-two entry count. Pad to the next
    # power of two only -- padding to 256 writes a 768-byte table we don't need.
    entries = max(2, 1 << (max(1, colors - 1)).bit_length())

    if (0, 0, 0) in triples:
        k = triples.index((0, 0, 0))
        triples[0], triples[k] = triples[k], triples[0]
    elif len(triples) < entries:
        triples = [(0, 0, 0)] + triples  # free slot in the padding, drop nothing
    else:
        triples = [(0, 0, 0)] + triples[:-1]

    flat = [c for t in triples for c in t]
    return flat + [0] * (entries * 3 - len(flat))


# ------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------


def prep_gif(
    src,
    dst=None,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    fps: float = 12.5,
    colors: int = 64,
    mode: str = "band",
    band_scale: float = 1.5,
    quant: str = "fastoctree",
    palette_mode: str = "global",
    black_floor: int = 6,
    trim_blank_ms: Optional[int] = 200,
    resample=Image.LANCZOS,
) -> dict:
    """Downscale a GIF to a panel-ready GIF. Returns a report dict."""
    if not 2 <= colors <= 256:
        raise ValueError(f"colors must be between 2 and 256, got {colors}")
    frames, durations, loop = decode_frames(src)
    picks, out_durations = resample_timeline(durations, fps)

    y0, y1 = content_rows(frames)
    band_cy = (y0 + y1) / 2.0
    band_px = max(height, min(frames[0].height, int(round((y1 - y0) * band_scale))))

    small: List[Image.Image] = []
    for j in picks:
        im = fit_frame(frames[j], width, height, mode, band_px, band_cy, resample)
        arr = np.asarray(im).copy()
        if black_floor:
            # Resampling bleeds a little light into pixels that should be off.
            # On an LED panel that reads as grey haze, so floor it to true black.
            arr[arr < black_floor] = 0
        small.append(Image.fromarray(arr))

    if trim_blank_ms is not None and len(small) > 2:
        small, out_durations = _trim_blank_ends(small, out_durations, trim_blank_ms)

    save_kwargs = {}
    if palette_mode == "global":
        palette = global_palette(small, colors, quant)
        palette_img = Image.new("P", (1, 1))
        palette_img.putpalette(palette)
        pframes = [f.quantize(palette=palette_img, dither=Image.Dither.NONE) for f in small]
        # One global colour table, no per-frame local tables: smaller, and static
        # pixels cannot shift colour between frames.
        save_kwargs["palette"] = bytes(palette)
    elif palette_mode == "per-frame":
        # What the vendor library emits. Bigger and prone to shimmer, but it is
        # the shape a picky firmware decoder is most likely to have been tested
        # against, so it is worth having as a fallback.
        pframes = [
            f.convert("P", palette=Image.Palette.ADAPTIVE, colors=colors, dither=Image.Dither.NONE)
            for f in small
        ]
    else:
        raise ValueError(f"unknown palette_mode {palette_mode!r}")

    for f in pframes:
        f.info.pop("transparency", None)

    buf = io.BytesIO()
    pframes[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=pframes[1:],
        duration=out_durations,
        loop=loop,
        disposal=2,  # full frames; simplest thing for a small firmware decoder
        optimize=False,
        background=0,
        **save_kwargs,
    )
    data = buf.getvalue()
    if dst:
        Path(dst).write_bytes(data)

    # Pillow can merge identical adjacent frames on save, so read the file back
    # and report what it actually contains. Frames and durations must come from
    # the same place: play_frames zips them, and a mismatch silently truncates
    # the animation.
    written = Image.open(io.BytesIO(data))
    written_durations: List[int] = []
    written_frames: List[Image.Image] = []
    for i in range(getattr(written, "n_frames", 1)):
        written.seek(i)
        written_durations.append(int(written.info.get("duration") or 0))
        written_frames.append(written.convert("RGB"))

    # Error metrics compare the pre-save pair, which is aligned by construction.
    ref = np.stack([np.asarray(f).astype(np.int16) for f in small])
    got = np.stack([np.asarray(f.convert("RGB")).astype(np.int16) for f in pframes])
    visible = (ref * [0.299, 0.587, 0.114]).sum(3) > 16

    return {
        "data": data,
        "bytes": len(data),
        "frames": len(written_durations),
        "duration_ms": int(sum(written_durations)),
        "avg_ms": int(round(sum(written_durations) / max(1, len(written_durations)))),
        "durations": written_durations,
        "colors": colors,
        "mode": mode,
        "palette_mode": palette_mode,
        "band_px": band_px,
        "content_rows": (y0, y1),
        "loop": loop,
        "mean_err": float(np.abs(got - ref).mean()),
        "visible_err": float(np.abs(got - ref)[visible].mean()) if visible.any() else 0.0,
        "rgb_frames": written_frames,  # aligned with "durations" above
    }


def _trim_blank_ends(frames, durations, cap_ms):
    """Cap time spent on all-black lead-in / lead-out frames."""
    blank = [bool(np.asarray(f).max() == 0) for f in frames]
    lo, hi = 0, len(frames) - 1
    while hi - lo > 1 and blank[lo] and blank[lo + 1]:
        durations[lo + 1] += durations[lo]
        lo += 1
    if blank[lo]:
        durations[lo] = min(durations[lo], cap_ms)
    while hi - lo > 1 and blank[hi] and blank[hi - 1]:
        durations[hi - 1] += durations[hi]
        hi -= 1
    if blank[hi]:
        durations[hi] = min(durations[hi], cap_ms)
    return frames[lo : hi + 1], durations[lo : hi + 1]


# ------------------------------------------------------------------
# Preview
# ------------------------------------------------------------------


def write_preview(report: dict, path, scale: int = 10, per_row: int = 8) -> None:
    """Contact sheet of every frame, nearest-neighbour upscaled."""
    frames = report["rgb_frames"]
    w, h = frames[0].size
    cw, ch = w * scale + 6, h * scale + 6
    rows = (len(frames) + per_row - 1) // per_row
    sheet = Image.new("RGB", (per_row * cw, rows * ch), (24, 24, 28))
    for i, f in enumerate(frames):
        big = f.resize((w * scale, h * scale), Image.NEAREST)
        sheet.paste(big, ((i % per_row) * cw + 3, (i // per_row) * ch + 3))
    sheet.save(path)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def positive_float(value: str) -> float:
    f = float(value)
    if f <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0, got {value}")
    return f


def colour_count(value: str) -> int:
    n = int(value)
    if not 2 <= n <= 256:
        raise argparse.ArgumentTypeError(f"must be between 2 and 256, got {value}")
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Prepare a GIF for the 32x16 iPixel LED panel (no ffmpeg required).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("source", type=Path, help="input GIF")
    p.add_argument("-o", "--output", type=Path, help="output GIF (default: <name>_32x16.gif)")
    p.add_argument("--width", type=int, default=WIDTH)
    p.add_argument("--height", type=int, default=HEIGHT)
    p.add_argument("--fps", type=positive_float, default=12.5, help="target frame rate")
    p.add_argument("--colors", type=colour_count, default=64,
                   help="size of the shared palette (2-256)")
    p.add_argument(
        "--mode",
        choices=["band", "crop", "fit", "stretch"],
        default="band",
        help="band = crop a band centred on the animation; crop = centre crop; "
        "fit = letterbox the whole frame",
    )
    p.add_argument("--band-scale", type=float, default=1.5, help="band height / content height")
    p.add_argument("--quant", choices=sorted(QUANT_METHODS), default="fastoctree")
    p.add_argument(
        "--palette",
        choices=["global", "per-frame"],
        default="global",
        help="global = one shared colour table (smaller, no shimmer); per-frame = "
        "what the vendor library emits, try it if the panel renders nothing",
    )
    p.add_argument("--preview", type=Path, help="also write a contact sheet PNG")
    p.add_argument(
        "--max-bytes",
        type=int,
        default=ONE_WINDOW_MAX,
        help="warn above this; the default keeps the upload to a single 12KB window",
    )
    args = p.parse_args(argv)

    if not args.source.exists():
        print(f"error: no such file: {args.source}", file=sys.stderr)
        return 1

    out = args.output or args.source.with_name(f"{args.source.stem}_{args.width}x{args.height}.gif")
    report = prep_gif(
        args.source,
        out,
        width=args.width,
        height=args.height,
        fps=args.fps,
        colors=args.colors,
        mode=args.mode,
        band_scale=args.band_scale,
        quant=args.quant,
        palette_mode=args.palette,
    )

    print(f"{args.source}  ->  {out}")
    print(f"  {args.width}x{args.height}, {report['frames']} frames, "
          f"{report['duration_ms']} ms, {report['avg_ms']} ms/frame avg, loop={report['loop']}")
    print(f"  {report['colors']} colours, {report['palette_mode']} palette, mode={report['mode']} "
          f"(content rows {report['content_rows'][0]}-{report['content_rows'][1]}, "
          f"band {report['band_px']}px)")
    print(f"  quantisation error {report['visible_err']:.2f}/255 on lit pixels")
    print(f"  {report['bytes']} bytes", end="")
    if report["bytes"] <= args.max_bytes:
        print(f"  (fits one BLE window, limit {args.max_bytes})")
    else:
        windows = -(-report["bytes"] // (12 * 1024))
        print(f"  -- OVER the {args.max_bytes} byte single-window budget, needs {windows} windows.")
        print("     Lower --fps or --colors to get back under it; multi-window transfers are")
        print("     slower and have more ways to fail mid-upload.")

    if args.preview:
        write_preview(report, args.preview)
        print(f"  preview: {args.preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
