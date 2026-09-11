Byte math checks out, and Python's isoweekday() happens to map exactly onto the protocol's day-of-week convention. Here's everything.

Why it survives the app closing

Same architecture as the GIF. The clock is a firmware feature — the panel keeps its own time and renders the face itself. The app's entire contribution is two commands and then it disconnects. This is documented behavior, not a guess: the ESPHome component author's stated goal for his whole project was a clock visualization provided by the display firmware itself, plus a way to sync the time without having to use the app.

So "implement my own clock" splits into two very different projects, and you should pick deliberately. I'll cover both.

Path A — drive the built-in clock yourself

Two commands. Both are fully documented from BLE sniffing.

Set time — opcode 0x8001, 8 bytes

[08 00] [01 80] [hh] [mm] [ss] [lang]

Hour 0–23, minute and second 0–59, language byte 0 for English. This is the first command the app sends after connecting, and its ACK is an 11-byte notification whose fifth byte encodes the display model. One command doubles as your device-size probe.

Clock mode — opcode 0x0106, 11 bytes

[0B 00] [06 01] [style] [format24] [show_date] [yy] [mm] [dd] [dow]

Style 0–8 (nine faces; which ones exist depends on the panel). format24 is 0 for 12-hour, 1 for 24-hour. show_date 0 is off, 1 alternates time and date. yy is the year minus 2000, and dow runs 1–7 with 7 meaning Sunday. Returns a 5-byte ACK with state 1.

For 2026-09-10 14:37:05, analog style, 12-hour, date on, that's 0b 00 06 01 02 00 01 1a 09 0a 04.

python
import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner

WRITE  = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000fa03-0000-1000-8000-00805f9b34fb"

def set_time_cmd(now, language=0):
    return bytes([0x08, 0x00, 0x01, 0x80,
                  now.hour, now.minute, now.second, language])

def clock_mode_cmd(now, style=0, h24=True, show_date=False):
    return bytes([0x0B, 0x00, 0x06, 0x01,
                  style, int(h24), int(show_date),
                  now.year - 2000, now.month, now.day,
                  now.isoweekday()])          # 1=Mon .. 7=Sun, matches protocol

async def sync(address, style=0, h24=True, show_date=True):
    async with BleakClient(address, timeout=15) as c:
        acks = asyncio.Queue()
        await c.start_notify(NOTIFY, lambda _, d: acks.put_nowait(bytes(d)))

        now = datetime.now()                  # local wall clock, see below
        await c.write_gatt_char(WRITE, set_time_cmd(now), response=False)
        info = await asyncio.wait_for(acks.get(), 5)
        print("device byte:", hex(info[4]))   # display model / size

        await c.write_gatt_char(WRITE, clock_mode_cmd(now, style, h24, show_date),
                                response=False)
        await asyncio.wait_for(acks.get(), 5)

asyncio.run(sync("XX:XX:XX:XX:XX:XX"))

Use isoweekday(), not weekday() — the latter is Monday=0 and would be off by one every day.

pypixelcolor and the Home Assistant integration both wrap this if you'd rather not touch bytes. The HA integration exposes clock style 0–8, a 24-hour switch, and a show-date switch, with time syncing automatically.

Running it as a daemon. Three things determine how well this holds up.

The panel almost certainly has no battery-backed RTC. Nothing in the protocol suggests one, these are bare USB-C-powered boards, and the app resyncs on every connect. Test it: unplug for a minute, plug back in, and see whether the time is right or reset. If it resets, your syncer needs to fire on a schedule, not just once.

Drift is slow. A typical MCU crystal at 20–50 ppm is a couple of seconds a day. A daily resync is plenty; hourly costs nothing and covers you against a worse oscillator.

The device is timezone-blind. You send local wall-clock time and it just counts. Nothing handles DST, which matters in Eastern time — you'll jump an hour twice a year until the next sync. The ESPHome author hit exactly this bug and had to fix a one-hour DST offset. Schedule an extra resync right after the March and November transitions, or just resync hourly and forget it.

Also send brightness (0x8004, 1–100) on a schedule if this lives in a bedroom. Note that 0% is not actually dark on these panels.

Path B — a custom clock face

Here's the constraint you need to know before you start: nothing in the protocol lets you upload a clock face. The firmware knows its nine styles and that's it. A custom face means you render every minute yourself and push a frame, which trades away the exact property you liked. Your clock is only alive while your sender is running. Close it and the panel freezes on whatever minute it last received.

If you accept that, the mechanics are straightforward and cheap:

Render the face with PIL at the panel's exact resolution, once a minute.
Push it to slot 0. This matters. Slot numbers 0 and above 100 are applied immediately rather than stored, and they halt program-list execution. Writing a numbered slot every 60 seconds would burn EEPROM write cycles for no reason.
A 32×32 PNG is roughly 0.5–1 KB, so each update is well under a second even at these transfer rates. Once a minute is nothing.
Anti-alias the glyphs. Same principle as the GIF answer — a soft edge on a 32×32 panel reads far better than hard pixels, and it's what makes the built-in faces look good.

For a sender that's genuinely always on, you need something in BLE range permanently: a Pi or mini PC, Home Assistant with a Bluetooth proxy, or an ESP32 running the ESPHome component, which is precisely the "no phone required" architecture that project was built for.

The hybrid worth considering

Run the built-in clock as your baseline so the panel is always showing correct time on its own, and have your custom renderer push to slot 0 only while it's running. When your sender dies or you shut the laptop, a watchdog re-sends the clock-mode command and the firmware clock takes back over. You get a custom face when you're around and a self-sufficient clock when you're not.

I want the hours to be 0-12

It's one byte. Byte 6 of the clock-mode command — format24 — where 0 means 12-hour and 1 means 24-hour. In the code from before, that's just h24=False:

python
await c.write_gatt_char(WRITE, clock_mode_cmd(now, style=0, h24=False, show_date=True),
                        response=False)

The two frames differ only in that byte:

12h:  0b 00 06 01 00 00 01 1a 09 0a 04
24h:  0b 00 06 01 00 01 01 1a 09 0a 04
                    ^^

The trap: don't convert the hour you send in set_time. That command always takes 0–23 and the panel counts in 24-hour internally. format24 is purely a rendering flag on the clock-mode command. Send 0x0d for 1 PM, not 0x01:

wall 13:05  ->  08 00 01 80 0d 05 00 00
wall 23:05  ->  08 00 01 80 17 05 00 00

If you convert to 12-hour before sending, the panel will be wrong for half of every day and you'll spend an hour hunting a bug that isn't in your rendering.

Two things to eyeball once it's running. A 12-hour face is conventionally 1–12 rather than 0–12, so midnight will most likely render as 12 rather than 0 — which of the two you get is firmware behavior and there's no byte to change it. And not every style necessarily honors the flag; the style list varies by panel, so if style 0 ignores it, walk through 0–8 and see which ones respect it.

If none of the built-in faces render it the way you want, that's exactly the wall where Path B becomes the answer, since a self-rendered face gives you complete control over the hour formatting.

If you're driving it through the Home Assistant integration instead, it's the switch.{device}_clock_24h_format entity — turn it off.