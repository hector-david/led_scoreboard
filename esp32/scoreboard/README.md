# ESP32 LED Scoreboard

Standalone Arduino firmware for an ESP32-S3 that turns a D18 BLE remote and a
32×16 iPixel BLE LED matrix into a two-team scoreboard.
No phone or PC is needed once the board is flashed: the ESP32 acts as a BLE
central for both devices at the same time, reads gestures from the remote,
renders the scores in RAM, encodes the frame as a PNG, and pushes it to the
panel in a single GATT write.

This is the ESP32 port of the Python scoreboard in the repo root
(`led_scoreboard_v1.py`); it uses the same panel protocol and a similar layout.

```
+--------------------------------+
|                                |
|   1 2            0 7           |   Team 1 = red, x = 0..14
|                                |   Team 2 = blue, x = 17..31
+--------------------------------+
        32 x 16 pixels
```

## Hardware

- ESP32-S3 N16R8 dev board (16 MB flash, 8 MB OPI PSRAM)
- D18 BLE HID remote (touchpad + consumer-control buttons)
- iPixel 32×16 BLE LED panel advertising as `LED_BLE_CD9B89CA`

## Controls

<img src="../control_layout.png" alt="D18 remote control layout" width="50%">



| D18 gesture / key | Button | Action |
| --- | --- | --- |
| Swipe down | `button_1` | Team 1 +1 |
| Swipe up | `button_5` | Team 1 −1 |
| Swipe left | `button_4` | Team 2 +1 |
| Swipe right | `button_2` | Team 2 −1 |
| Consumer key `40 00` | `button_10` | Double press: reset both scores to `00` |
| Single center tap | `button_3` | Show the D18 battery level for 3 s, then return to the scores |

Scores are clamped to `0–99`. The remaining D18 inputs are decoded but not yet
mapped to an action:

| D18 gesture / key | Button |
| --- | --- |
| Double center tap | `button_9` |
| Consumer key `04 00` | `button_6` |
| Consumer key `00 80` | `button_7` |
| Consumer key `00 40` | `button_8` |

## Building and flashing

Open `scoreboard.ino` in the Arduino IDE with the ESP32 core installed.

**Board settings** (`Tools` menu):

| Setting | Value |
| --- | --- |
| Board | ESP32S3 Dev Module |
| Upload Speed | 921600 |
| USB CDC On Boot | Disabled |
| CPU Frequency | 240 MHz (WiFi) |
| Flash Mode | QIO 80 MHz |
| Flash Size | 16 MB (128 Mb) |
| PSRAM | OPI PSRAM |
| Port | whichever COM port the board enumerates on (has been `COM7`) |

**Libraries:**

- ESP32 Arduino core BLE (`BLEDevice.h`, bundled with the core)
- [PNGenc](https://github.com/bitbank2/PNGenc) by Larry Bank (Library Manager)

Serial monitor runs at **115200** baud.

## Startup sequence

Connection order matters. The D18 only advertises for a short window after a
button press, so it is connected first; the LED panel is scanned for while the
D18 link stays up.

1. Open the serial monitor, then reset the board.
2. When you see `Scanning for D18...`, press a button on the remote to make it
   advertise. The board connects and secures the link (Just Works pairing).
3. The board subscribes to the D18 HID input reports.
4. The board scans for `LED_BLE_CD9B89CA` and connects (MTU 517 requested).
   The panel must be powered on and **not** connected to the iPixel phone app.
5. Brightness is explicitly set to 50 % and the initial `00 – 00` frame is sent.

On success you will see:

```
============================================
BOTH BLE DEVICES CONNECTED
button_1 = Team 1 +1
button_5 = Team 1 -1
button_4 = Team 2 +1
button_2 = Team 2 -1
button_10 x2 = reset both to 00 (double press)
button_8 = brightness up
button_7 = brightness down
button_3 = show D18 battery level
============================================
```

Every 5 seconds the loop prints a status line:

```
STATUS | D18: CONNECTED | LED: CONNECTED | T1: 3 | T2: 1
```

## Automatic reconnection

Both links are checked on every pass of `loop()`. If either one is down the
board scans for it (`Config::BLE_SCAN_SECONDS`, 5 s per attempt) and tries to
connect; a failed attempt simply retries on the next pass, forever, so the
board never needs a reset:

- **D18 drops** — the board prints `D18 DISCONNECTED. Press a button on the
  remote to reconnect.` and keeps scanning. Press any button on the remote so
  it advertises again; the link is re-secured from the stored bond and the HID
  reports are re-subscribed.
- **LED drops** — the board prints `LED DISCONNECTED. Reconnecting...` and
  keeps scanning. As soon as the panel is back it re-sends the brightness and
  the current scores, which are kept in RAM the whole time.
- **Both down** — each round scans for the D18 first (it only advertises
  briefly after a button press), then for the LED.

Scores are never lost by a disconnect; button presses that arrive while the
LED is being reconnected are queued and applied once the loop resumes.

### Blinking while the remote is missing

Whenever the panel is connected but the D18 is not — at startup and after the
remote drops — the scores blink on and off so it is obvious from across the
room that the board is not taking button presses yet. `Scoreboard::tick()`
alternates the score frame with an empty one (`BLINK_MS`, top of
`Scoreboard.cpp`), and `Scoreboard::setBlinking(false)` puts the scores back
the moment the remote is connected.

A BLE scan blocks the loop, so while the panel is blinking the D18 is scanned
for in short slices (`Config::BLE_SCAN_SECONDS_SHORT`, 1 s) instead of the
usual 5 s; the blink can only advance between scans, so that slice, not
`BLINK_MS`, sets the visible rate.

## Module layout

The sketch is split into one class per file:

| File | Responsibility |
| --- | --- |
| `scoreboard.ino` | Wires the modules together; `setup()` connection sequence and `loop()` |
| `Config.h` | Shared constants: device names, panel geometry, brightness range, buffer sizes |
| `Font.h/.cpp` | 7×14 bitmap glyphs for digits `0`–`9` and `%` |
| `Framebuffer.h/.cpp` | 32×16 RGB888 pixel buffer with `clear`, `fill`, `setPixel`, `drawDigit`, and a serial dump |
| `PngImage.h/.cpp` | Encodes a `Framebuffer` to an in-RAM PNG with PNGenc |
| `LedImagePacket.h/.cpp` | Wraps a PNG in the panel's proprietary `0x0002` "show image" packet (length, CRC32, buffer number) |
| `LedDisplay.h/.cpp` | BLE client for the LED panel: scan, connect, MTU, brightness, single-write image send, ACK notifications |
| `D18Remote.h/.cpp` | BLE HID client for the D18: scan, connect, secure, subscribe to input reports, decode touchpad gestures and consumer keys into button numbers |
| `RemoteBattery.h/.cpp` | Reads the D18 charge level over the standard BLE Battery Service (`0x180F` / `0x2A19`) on the existing D18 link |
| `BatteryScreen.h/.cpp` | Draws a battery percentage (digits + `%`) centered on a `Framebuffer`, green / yellow / red by charge; sets how long it stays up (`SHOW_MS`) |
| `Scoreboard.h/.cpp` | Owns the two scores and the display pipeline; maps button numbers to score changes; hosts temporary screens (battery) and restores the scores when they expire; blinks the scores while the remote is missing |

### Display pipeline

```
scores -> Framebuffer -> PngImage -> LedImagePacket -> LedDisplay (one GATT write)
```

`Scoreboard::update()` runs the whole chain. The 32×16 frame compresses to a
few hundred bytes, so it fits inside the negotiated MTU and the panel redraws
instantly. `LedDisplay::sendImagePacket()` refuses any packet larger than the
MTU payload rather than letting the BLE stack split it into a prepared/long
write, which the panel does not accept.

### Image packet format

| Bytes | Field |
| --- | --- |
| 0–1 | Total packet length, LE16 |
| 2–3 | Command `0x0002`, LE16 |
| 4 | `0x00` |
| 5–8 | PNG byte length, LE32 |
| 9–12 | CRC32 of the PNG bytes, LE32 |
| 13 | `0x00` |
| 14 | Buffer number |
| 15… | PNG data |

Brightness uses a separate 5-byte command: `05 00 04 80 XX`, where `XX` is the
percentage (`0x0A`–`0x64` for 10–100 %).

### D18 input handling

HID notifications arrive on the BLE host task. `D18Remote` copies each report
into a FreeRTOS queue and returns immediately; `D18Remote::update()` drains the
queue from `loop()`, so button handlers (and the LED GATT writes they trigger)
always run on the main loop, never inside a BLE callback.

- **Report ID 1 (consumer control):** 2-byte key codes mapped directly to
  `button_6/7/8/10`.
- **Report ID 2 (touchpad):** absolute X/Y plus a touch bit. A swipe is
  ≥ 250 units along the dominant axis; a tap is ≤ 120 units of travel starting
  in the center region (X 400–600, Y 300–500). Two center taps within 450 ms
  are a double tap (`button_9`); otherwise a single tap (`button_3`) fires once
  the window expires.

Gesture thresholds live at the top of `D18Remote.cpp`.

### Battery screen

`button_3` reads the D18's Battery Level characteristic (one blocking GATT
read on the main loop, a few tens of ms) and `Scoreboard::showBattery()` pushes
the percentage through the same framebuffer → PNG → packet pipeline. The
number is followed by a `%` glyph, centered with no leading zeros, and colored green (≥ 50 %), yellow
(20–49 %) or red (< 20 %). `Scoreboard::tick()`, called from `loop()`, re-sends
the scores after `BatteryScreen::SHOW_MS` (3 s); any score change in the
meantime restores them immediately. If the remote is disconnected or does not
expose the Battery Service the read is logged and the scores stay on the panel.

## GATT identifiers

| Device | UUID | Purpose |
| --- | --- | --- |
| LED panel | `000000fa-0000-1000-8000-00805f9b34fb` | Service |
| LED panel | `0000fa02-…` | Write (commands and image packets) |
| LED panel | `0000fa03-…` | Notify (ACKs) |
| D18 | `0x1812` | HID service |
| D18 | `0x2A4D` | Report characteristic |
| D18 | `0x2908` | Report Reference descriptor (report ID + type) |
| D18 | `0x180F` | Battery Service |
| D18 | `0x2A19` | Battery Level characteristic (0–100 %) |

## Configuration

`Config.h`:

| Name | Default | Meaning |
| --- | --- | --- |
| `LED_NAME` | `LED_BLE_CD9B89CA` | Panel advertised name |
| `D18_NAME` | `D18` | Remote advertised name |
| `BLE_SCAN_SECONDS` | `5` | Length of one scan attempt (initial connect and every reconnect retry) |
| `BRIGHTNESS_DEFAULT` | `50` | Brightness sent at startup (%) |
| `BRIGHTNESS_STEP` / `MIN` / `MAX` | `10` / `10` / `100` | Brightness adjustment range |
| `DISPLAY_WIDTH` × `DISPLAY_HEIGHT` | `32` × `16` | Panel resolution |
| `PNG_BUFFER_SIZE` | `4096` | Max encoded PNG size |
| `LED_HEADER_SIZE` | `15` | Bytes before the PNG in an image packet |

Layout (digit positions, colors, gap) is at the top of `Scoreboard.cpp`.

## Notes

- **Include order matters.** PNGenc's `zutil.h` does `#define local static`,
  which breaks NimBLE's `ble_sm.h` (it has a struct field named `local`).
  Always include the BLE headers before `PngImage.h`; `PngImage.h` also
  `#undef`s `local` after including PNGenc.
- `Scoreboard`, `PngImage`, and `LedImagePacket` hold roughly 10 KB of buffers
  and PNGenc state. Keep them global, not on the stack.
- `Scoreboard::testSolidRedFrame()` fills the panel solid red; useful for
  checking the send path independently of the font and layout.

## Troubleshooting

- **`D18 not found.`** repeating — the remote isn't advertising during the
  scan. Press a remote button; the board keeps scanning until it sees it.
- **`LED not found.`** repeating — the panel is off, out of range, or still
  connected to the phone app. Close the app; the board keeps scanning.
- **`SEND ERROR: packet exceeds negotiated MTU.`** — MTU negotiation failed
  (check the `LED MTU negotiation` line) or the PNG is unusually large.
- **Frame sent, `LED ACK` received, but nothing changes** — try a different
  buffer number in `LedImagePacket.cpp`.
