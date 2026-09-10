# GIFs on the 32×16 iPixel panel

Prepare any GIF for `LED_BLE_CD9B89CA` and push it over BLE.

```powershell
py send_gif.py pacman.gif --dry-run   # build and check the packets, no radio
py send_gif.py pacman.gif             # prep + send
```

| File | What it does |
| --- | --- |
| `ipixel.py` | Device facts, packet framing, BLE transport. Everything panel-specific. |
| `prep_gif.py` | Any GIF → a 32×16 GIF the panel can decode. Pillow only, no ffmpeg. |
| `send_gif.py` | Validates, then uploads with the GIF command (`0x0003`). |
| `play_frames.py` | Fallback: animates by streaming PNG frames over the proven `0x0002`. |

Requirements are what you already have: `bleak`, `pillow`, `numpy`.

## Step 1 — resolution

32×16. Confirmed by `../src/led_scoreboard.py` and the protocol notes, not guessed.
The GIF's logical screen must match exactly; `send_gif.py` refuses otherwise.

Do **not** ask the vendor library for the resolution. Its device-info parser latches
the first notification that arrives, and every acknowledgement byte this panel is
known to send (`05 00 02 00 03`, `05 00 04 80 01`) parses to an unknown device type,
which it silently defaults to **64×64**. That would resize your GIF to the wrong
geometry and upload it without complaint.

## Step 2 — prepare the GIF

`instructions.md` gives an ffmpeg recipe. ffmpeg is not installed here, and the
`convert` on `PATH` is Windows' filesystem converter, not ImageMagick. `prep_gif.py`
is the Pillow equivalent:

```powershell
py prep_gif.py pacman.gif                       # -> pacman_32x16.gif
py prep_gif.py in.gif --fps 10 --colors 32 --preview sheet.png
```

```
pacman.gif  ->  pacman_32x16.gif
  32x16, 40 frames, 3440 ms, 86 ms/frame avg, loop=0
  64 colours, global palette, mode=band (content rows 197-292, band 142px)
  quantisation error 7.52/255 on lit pixels
  7995 bytes  (fits one BLE window, limit 12288)
```

Three things matter more here than the resampling filter, and none are in the
original recipe.

**Composite before decimating.** Most GIF frames are partial deltas — in `pacman.gif`
only frame 0 is a full 480×480 image. Dropping frames before compositing shreds the
animation. Every frame is decoded fully composited first, then the timeline is
resampled on the wall clock so uneven source delays stay honest.

**One palette for the whole animation.** A per-frame adaptive palette makes static
pixels drift colour between frames, which on LEDs reads as a constant shimmer. A
single global table fixes it and drops the per-frame local tables, cutting the file
by roughly half. Pure black is pinned to index 0 so unlit pixels are genuinely off.
Dithering is off — on a 32×16 grid it just looks like noise.

**Aspect ratio is a real decision on a 2:1 panel.** For a square source:

| `--mode` | Result on `pacman.gif` | Lit rows | Size |
| --- | --- | --- | --- |
| `fit` | Whole frame letterboxed into the middle 16×16. Sprites ~3 px tall; half the panel black. | 6–9 of 16 | 3965 B |
| `crop` | Centre crop. Correct geometry, but the action only occupies rows 197–292 of 480, so it still lands small. | 5–11 of 16 | 5980 B |
| `band` *(default)* | Crops a band centred on wherever the animation actually is, then scales to fill. | 2–12 of 16 | 7995 B |

`--band-scale` sets the band height as a multiple of the content height. On this
source the content is 95 px tall, so `1.5` takes a 142 px band — it fills the panel
while keeping the ghosts' eyes readable. `1.15` starts to look stretched. Around
`2.5` the band is 240 px, close to what `crop` takes but centred on the content
rather than on the image; past about `5.0` the band covers the whole frame and
`band` becomes `stretch`. Use `--preview` and judge for yourself.

**Size.** Stay at or under **12288 bytes** and the whole upload is a single window.
That is the cheapest safety win available — the continuation option byte `0x02` is
never sent, multi-window acknowledgement behaviour never matters, and there is no
window boundary for a dropped link to interrupt. Lower `--fps` or `--colors` to get
back under it.

## Step 3 — send it

```powershell
py send_gif.py pacman.gif --dry-run     # packets only, no BLE
py send_gif.py pacman.gif               # prompts before writing
py send_gif.py pacman.gif --slot 2 --brightness 40 --yes
```

Close the iPixel phone app first — only one BLE central can hold the link.

`send_gif.py` refuses to touch the radio until the payload decodes as a complete GIF
(trailer present, every frame actually decodable), matches 32×16 exactly, has no
zero-length frame delays, sits under a 64 KB ceiling, and targets a slot that fits in
a byte. A slot outside the documented 1–100 range is a warning, not a refusal. It
prints every window header so you can compare against the capture in the protocol
notes.

### The packet

Same envelope as the PNG upload `../src/led_scoreboard.py` already uses — only the
command and one tail byte change:

```
[total_len u16] [cmd u16] [option] [size u32] [crc32 u32] [kind] [slot] [chunk]
```

| Field | PNG (proven) | GIF |
| --- | --- | --- |
| `cmd` | `02 00` | `03 00` |
| `kind` | `00` | `02` |
| `option` | `00` first window, `02` after | same |
| `size`, `crc32` | of the **whole** payload, repeated in every window | same |

`build_windows()` is byte-for-byte identical to the 472-byte packet this panel
acknowledged with `05 00 02 00 03`, and to the vendor library's builder across every
size, slot and command tested.

### Acknowledgements

Read from the notify characteristic as `[len u16][cmd u16][status]`:

| Status | Meaning |
| --- | --- |
| `03` | success |
| `01` | intermediate, more windows expected |
| `00` | **failure / CRC problem** |

The vendor library treats `00` as a *successful* window acknowledgement, so a CRC
failure there is reported as success. `ipixel.py` aborts on `00` instead.

### Slots

`--slot` defaults to **1**. That is the value `led_scoreboard.py` has written
hundreds of times without incident, and the only one with hardware evidence behind
it. `instructions.md` says slot 0 means "display now without persisting" — there is
no code path or observation supporting that on this unit, so treat it as untested
rather than as the safe option.

There is **no program-list command** in the library, despite what Step 4 of
`instructions.md` says. Cycling several GIFs means uploading each to its own slot and
looping `show_slot(n)` from Python, which holds the BLE link for the whole show.
`show_slot` itself is untested here.

## If the panel acknowledges but stays dark

That is the most likely failure, and it is not a bootloop — it means this firmware
has no GIF command. Every packet this unit has actually accepted used `0x0002`; the
GIF command `0x0003` is inferred from the vendor library, and `instructions.md` warns
outright that these panels branch on firmware version and that implementations
working on one panel show nothing on another.

Work through this in order rather than tuning the palette:

1. `py play_frames.py pacman.gif` — animates over the proven PNG command. Each frame
   is 194–388 bytes, inside the 472-byte write this panel has already ACKed. If this
   works and `send_gif.py` doesn't, the firmware lacks GIF support and this is your
   answer. The animation runs from the host, so it stops when the script does.
2. `py send_gif.py pacman.gif --palette per-frame --colors 32` — matches the shape
   the vendor library emits, in case the decoder wants local colour tables.
3. `py send_gif.py pacman.gif --slot 0` — only after the above, and knowing it is
   untested here.

## Recovering a panel that misbehaves

Power-cycle first. If it still connects, `pypixelcolor -a <addr> -c delete <slot>`
clears one slot and `-c clear` wipes every slot and setting. A panel that bootloops
before its radio comes up cannot be fixed from Python.

The single-window rule in Step 2 is what keeps you away from that territory: an
interrupted multi-window transfer is the plausible route to a half-written slot, and
a payload under 12288 bytes has no window boundary to be interrupted at.
