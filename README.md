# LED Scoreboard

A small interactive scoreboard for a 32×16 iPixel BLE LED matrix (device name
`LED_BLE_CD9B89CA`). `led_scoreboard.py` renders a two-team scoreboard in memory,
encodes it as a PNG, and pushes the whole frame to the display over Bluetooth Low
Energy in a single write.

```
+--------------------------------+
|  T1          |          T2     |
|              |                 |
|     1 2      |      7          |
+--------------------------------+
        32 x 16 pixels
```

## Requirements

- Windows / macOS / Linux with a BLE adapter
- Python 3.9+
- The LED screen powered on and **not** connected to the iPixel phone app

```powershell
py -m pip install bleak pillow
```

## Usage

```powershell
py led_scoreboard.py
```

The script scans for the display by name (15 s timeout), connects, subscribes to
the notify characteristic, and draws the initial `0 – 0` frame. It then reads
single-key commands from stdin and redraws after every change:

| Key | Action |
| --- | --- |
| `1` | Team 1 +1 |
| `2` | Team 2 +1 |
| `a` | Team 1 −1 |
| `b` | Team 2 −1 |
| `r` | Reset both to 0 |
| `q` | Quit |

Scores are clamped to `0–99`. Every command prints the raw device
acknowledgement received on the notify characteristic, e.g.
`LED response: 05 00 02 00 ...`.

## Layout

| Element | Position | Color |
| --- | --- | --- |
| `T1` label | x = 4, y = 0 | `(0, 180, 255)` cyan |
| `T2` label | x = 21, y = 0 | `(255, 90, 50)` orange |
| Center divider | column 15, full height | white |
| Team 1 score | centered in x = 2..12, y = 6 | white |
| Team 2 score | centered in x = 19..29, y = 6 | white |

Two bitmap fonts are embedded as string arrays in the source:

- `SMALL_FONT` — 3×5 glyphs, only `T`, `1`, `2` (enough for the labels)
- `DIGITS` — 6×10 glyphs for `0`–`9`, sized to fill the available height under
  the labels (rows 6–15, leaving row 5 as a gap)

To restyle the board, edit the color constants at the top of the file or the
coordinates in `build_scoreboard_frame()`.

## How the frame is sent

This device rejects concatenated per-pixel commands in one write, so the script
uses the same bulk path as `send_image.py`: render → PNG → one GATT write.

1. `frame_to_image()` converts the row-major RGB framebuffer to a 32×16 PIL image.
2. `build_frame_packet()` saves it as PNG (`compress_level=6`, no ICC profile)
   and builds the packet:

   | Bytes | Field |
   | --- | --- |
   | 2 | total length `15 + len(png)`, little-endian u16 |
   | 2 | command `0x02 0x00` |
   | 1 | `0x00` |
   | 4 | PNG length, little-endian u32 |
   | 4 | CRC32 of the PNG bytes, little-endian u32 |
   | 1 | `0x00` |
   | 1 | buffer number (`BUFFER_NUMBER = 1`) |
   | n | PNG data |

3. `send_frame()` writes the packet to `0000fa02-…` with `response=True`.

Because a full 32×16 frame compresses to a few hundred bytes, the whole
scoreboard fits in one write and updates instantly.

## Configuration

Constants at the top of `led_scoreboard.py`:

| Name | Default | Meaning |
| --- | --- | --- |
| `LED_NAME` | `LED_BLE_CD9B89CA` | BLE advertised name to scan for |
| `WRITE_UUID` | `0000fa02-…` | write characteristic |
| `NOTIFY_UUID` | `0000fa03-…` | notify / ack characteristic |
| `WIDTH`, `HEIGHT` | `32`, `16` | panel resolution |
| `BUFFER_NUMBER` | `1` | display buffer to write into |

If your panel advertises a different name, change `LED_NAME` — scanning by name
is preferred over hard-coding the BLE address.

## Troubleshooting

- **"LED screen not found."** — the panel is asleep, out of range, or still
  paired to the phone app. Close the app and retry.
- **Frame sent but nothing changes** — another buffer may be displayed; try a
  different `BUFFER_NUMBER`.
- **Write errors on Windows** — disconnect the device in Windows Bluetooth
  settings and let `bleak` connect directly.

## Related files

- `send_image.py` — send an arbitrary image file to the panel (fit/crop modes)
- `scoreboard_pixels.py`, `scoreboard_pixels_reliable.py` — earlier per-pixel
  drawing experiments
- `compare_png_vs_pixels.py` — comparison of the two transfer strategies
- `../ipixel_16x32_led_protocol_notes.md` — protocol reverse-engineering notes
