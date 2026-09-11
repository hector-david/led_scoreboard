# A clock on the 32×16 iPixel panel

```powershell
py send_clock.py --walk-styles     # try the faces, keep the one you like
py send_clock.py --style 3 --date  # send it and walk away
```

`send_clock.py` connects, says two things, and disconnects. The panel keeps the
clock running on its own after that — no phone, no PC, nothing in BLE range.
That is the whole point, and it is a firmware feature, not a trick.

| File | What it does |
| --- | --- |
| `ipixel_clock.py` | The two clock commands, the device-info reply, `ClockPanel`. |
| `send_clock.py` | **Send once, forget.** Sets the time and picks the face. |
| `clockface.py` | Renders a custom face to a 32×16 image. No BLE. |
| `custom_clock.py` | Pushes that custom face live, and hands the panel back on exit. |
| `test_clock.py` | Offline checks — packet vectors, layout, fonts. `py test_clock.py` |

Transport, framing and the BLE connection pattern are reused from `../gif/ipixel.py`
rather than copied.

## The thing to decide first

The panel will do **either** of these, and it cannot do both at once:

| | Built-in face (`send_clock.py`) | Custom face (`custom_clock.py`) |
| --- | --- | --- |
| Keeps correct time with nothing connected | **Yes, forever** | No |
| You design how it looks | 9 fixed faces, no colour control | Every pixel, any colour |
| Needs something running | No | Yes, permanently |
| What happens when the sender stops | n/a | Freezes on the last minute sent |

There is no third option, and it is worth being blunt about why: **nothing in
this protocol uploads a clock face.** Five independent reverse-engineerings of
it — two ESPHome/C++ ports, `pypixelcolor`, and two Python libraries for the
sibling family — describe the same closed set of opcodes. There is no font
command, no glyph table, no clock-face command. The nine faces are ROM assets
addressed by a single index byte. A face we draw ourselves is a *picture*, and a
picture does not tick.

So `custom_clock.py` hands the panel back. Unless you pass `--no-handback`, then
whenever it exits — cleanly, on Ctrl-C, or on an error — it re-sends the built-in
clock commands and the panel returns to keeping its own time. It checks the
panel's reply and exits non-zero if the hand-back did not take, so a wrapper or
scheduled task can tell the difference. Custom design while it runs, a
self-sufficient clock the rest of the time.

## The two commands

```
set time    08 00 01 80 <hh> <mm> <ss> <lang>
clock mode  0B 00 06 01 <style> <format24> <show_date> <yy> <mm> <dd> <dow>
```

Same framing as everything else on this panel: `[total_len u16 LE][cmd_lo][cmd_hi][args…]`,
where the length counts itself. `05 00 04 80 <level>` — the brightness command
`../gif/ipixel.py` has always used — is that shape, which is what anchors the rest.

Three traps, each of which costs an evening:

**The two commands are not one command.** `set time` carries the time of day and
no date; `clock mode` carries the date and no time. Send only the second and the
panel keeps counting from whatever it had, showing a confidently wrong time. Both
tools always send both.

**The hour is always 0–23**, even on a 12-hour face. `format24` is purely a
rendering flag. Convert before sending and the panel is wrong every afternoon,
and the bug looks like a rendering bug.

**Day of week is 1–7 with Monday=1** — exactly Python's `isoweekday()`.
`weekday()` is Monday=0 and would be off by one every single day.

### The dialect trap

Two unrelated panel families share the `fa02`/`fa03` characteristics and share
brightness, power, DIY-mode and set-pixel *byte for byte*. They disagree on
exactly these two commands, and the lengths are swapped:

| | iPixel (`LED_BLE_…`, this panel) | iDotMatrix (`IDM-…`, not this panel) |
| --- | --- | --- |
| set time | `08 00 01 80 hh mm ss lang` | `0B 00 01 80 yy mm dd dow hh mm ss` |
| clock mode | `0B 00 06 01 style fmt date yy mm dd dow` | `08 00 06 01 flags r g b` |
| clock colour | not settable | RGB in the command |

Nearly every "iDotMatrix" project on GitHub is the right-hand column. Feeding one
of its frames to this panel sends the wrong length for the opcode, and the
command is ignored — a silent no-op, not a rejection, which is the worst way to
be wrong. This unit is the left-hand column: its proven 15-byte upload header,
its `05 00 02 00 03` ack, its `07 00 08 80 01 00 <n>` show-slot and its `0x0105`
set-pixel all match the iPixel builders and none of the others.

The consequence you may not like: **the built-in clock's colour is not
settable on this dialect.** The RGB bytes exist only in the other family.

## Two things nobody can fix

**It is timezone-blind.** The frame carries hour, minute, second and a language
byte. There is no UTC offset, no timezone, no DST flag anywhere in the protocol.
The panel is handed raw local wall-clock time and counts from there, so it will
be an hour wrong from each DST change until something re-sends the time.

**There is probably no battery-backed clock.** No teardown shows a cell, the board
is USB-powered, and the vendor app re-syncs on every single connect — which is
what you do when you do not trust the hardware. Expect the time to be wrong after
a power cut.

Both have the same answer: run `send_clock.py` again. It is idempotent and takes
a few seconds. A daily scheduled task covers drift, power cuts and DST together:

```powershell
schtasks /create /tn "LED clock sync" /tr "py C:\Users\hecto\OneDrive\Documents\repos\led_scoreboard\clock\send_clock.py --yes --style 3" /sc daily /st 04:00
```

Check it first with `py send_clock.py --yes --style 3` — the task inherits
whatever that does, including the confirmation prompt if you leave off `--yes`.

## Picking a face

No two implementations of this protocol agree on how many styles exist: one
validates 0–8, one 1–9, one 1–8, one 0–7, and every one of them says it depends
on the panel. Rather than pick a side, ask the hardware:

```powershell
py send_clock.py --walk-styles
```

It shows each face in turn and waits. `y` keeps the one on screen and Enter
moves on. `q` **abandons** the walk — it does not keep what is showing; the
`--style` value (0 unless you passed one) is what gets sent on the way out, as it
also is if you run off the end without picking. Whatever settles is sent with a
fresh timestamp, so a walk that took minutes still leaves the clock correct.

## The custom face

```powershell
py custom_clock.py --preview sheet.png       # design it without the radio
py custom_clock.py --color amber --glow 0.25 # push it live
py custom_clock.py --duration 60             # run a minute, then hand back
py custom_clock.py --retry 10                # wait 10s between reconnects
```

### It survives the panel going away

Unplug the panel, carry it out of range, or let the phone app steal the link, and
`custom_clock.py` does not exit. It drops into a reconnect loop — every 5 seconds
(`--retry`), forever — and picks the face straight back up when the panel
answers. It also waits like this at startup, so you can launch it before the
panel is switched on.

Only three things end the run: Ctrl-C, `--duration`, or a design that cannot
render. A render failure is deterministic, so retrying it would just spin.

A few details that matter over a long run:

- **One dropped frame is a hiccup, three in a row is the link.** A single failed
  write is logged and skipped; three consecutive failures tear the connection
  down and rebuild it.
- **Brightness is re-applied on every reconnect.** A panel that vanished has
  quite likely been power-cycled, so nothing that was set on it is assumed to
  have survived.
- **Retry logging is throttled** — the first three attempts, then roughly once a
  minute. A panel that is off overnight leaves a readable log, not 17,000 lines.
- **If you stop it while the panel is still unreachable**, there is nothing to
  hand back to. It says so and exits non-zero, because the panel is then frozen
  on its last custom frame — run `send_clock.py` once it is back.

`--preview` renders a contact sheet of the cases that actually break a layout —
midnight, a single-digit hour, 11:59, noon, an ordinary afternoon and the last
minute of the day, plus the date line when you add `--date` — so the design loop
never touches the panel. An over-wide or unrenderable `--date-format` is refused
here rather than mid-run: the 3×5 font fits 8 characters, so `%Y-%m-%d` and `%A`
are rejected up front instead of silently clipping into a *different* date.

```
+--------------------------------+
|                                |  rows 0-1   margin
|   HH : MM   (6x10 glyphs)     #|  rows 2-11, PM marker in column 31
|                                |  rows 12-13 margin
|################----------------|  rows 14-15 seconds bar
+--------------------------------+
```

The PM marker is anchored to the top of the digit block rather than to the panel
corner, so a taller `--bar-height` moves the digits up without the marker landing
on one of them. The widest layout is 30px drawn from x=1, which is why columns 0
and 31 are free at every size.

The 6×10 digits are the ones `../src/led_scoreboard.py` already puts on this
panel, so they are known to read from across a room rather than freshly invented.
`--glow` bleeds a fraction of each lit pixel into its dark neighbours, which is
most of why the firmware faces look softer than a plain bitmap blit.

Frames go to **slot 0**, which means "show now, do not store". It costs no EEPROM
write cycles, leaves nothing behind, and cannot brick the panel with bad content
on the next boot — all three of which a numbered slot repainted once a second
would risk. Sending invalid content to a numbered slot is a documented way to put
these panels into a boot loop.

## Troubleshooting

- **Not found** — the panel is asleep, out of range, or still held by the iPixel
  phone app. Only one BLE central can hold the link; close the app.
- **Acknowledged but the face did not change** — try another style. Which of 0–9
  a given panel renders is not fixed; `--walk-styles` will tell you.
- **Time is right, date is wrong (or vice versa)** — they travel in different
  commands. Both tools send both, so this means one of the two was refused; the
  packet hex is printed for each.
- **An hour out twice a year** — DST. Re-run `send_clock.py`.
- **Wrong after unplugging** — no battery-backed clock. Re-run `send_clock.py`.
- **Midnight shows 12, not 0** — 12-hour faces conventionally run 1–12, and there
  is no byte to change it on the built-in faces. `custom_clock.py --24h` renders
  it as `00:00` if you want the zero.

## Provenance

The two clock commands have **not** been exercised on this unit yet — only
brightness (`05 00 04 80`) has, via `../gif/ipixel.py`. Everything else here is
what four independent implementations of this exact dialect agree on, checked
byte-for-byte against their published frames in `test_clock.py`, with the framing
anchored to the packets this panel has actually acknowledged. `info.md` in this
directory turned out to be right about both layouts.
