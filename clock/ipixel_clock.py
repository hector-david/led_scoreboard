"""Clock commands for the 32x16 iPixel panel (`LED_BLE_CD9B89CA`).

The point of this module is the property the GIF tools do not have: once these
two commands land, the panel keeps the clock running by itself. The firmware
owns the time and renders the face. Nothing needs to stay connected, so the
sender connects, says two things, and drops the link for good.

The dialect trap
    Two unrelated LED-panel families share the `fa02`/`fa03` characteristics and
    share brightness, power, DIY-mode and set-pixel *byte for byte*. They differ
    on exactly the two commands this module cares about, and the lengths are
    swapped between them:

        iPixel   (`LED_BLE_...`, this panel)   iDotMatrix (`IDM-...`, not this panel)
        set time    08 00 01 80 hh mm ss lang    0B 00 01 80 yy mm dd dow hh mm ss
        clock mode  0B 00 06 01 style ...        08 00 06 01 flags r g b

    Nearly every "iDotMatrix" project on GitHub is the other dialect. Feeding
    its frames to this panel sends the wrong length for the opcode, and the
    command is ignored -- a silent no-op, not a NAK. This unit is the iPixel
    family: its proven 15-byte upload header ending in kind+slot, its
    `05 00 02 00 03` ack, its `07 00 08 80 01 00 <n>` show-slot and its
    `0x0105` set-pixel all match the iPixel builders and none of the others.

Consistent with the rest of the repo, the framing here is the one already proven
on this unit: `[total_len u16 LE][cmd_lo][cmd_hi][args...]`, where the length
counts itself. `05 00 04 80 <level>` -- the brightness command
`../gif/ipixel.py` has always used -- is that shape, and it is the anchor every
command below is built to match.

Proven on this panel
    0x8004  brightness   05 00 04 80 <0-100>            ack 05 00 04 80 01
Documented by four independent iPixel implementations, not yet run on this unit
    0x8001  set time     08 00 01 80 hh mm ss <lang>    reply: 11-byte device info
    0x0106  clock mode   0B 00 06 01 <style> <24h> <date> <yy> <mm> <dd> <dow>
    0x8006  rotation     05 00 06 80 <0-3>
    0x0107  power        05 00 07 01 <0|1>
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# The transport is shared with the GIF tools rather than copied. This directory
# is a sibling of theirs, and the repo is flat scripts, not a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gif"))

from ipixel import (  # noqa: E402  (the path shim has to come first)
    HEIGHT,
    LED_NAME,
    WIDTH,
    Ack,
    Panel,
    PanelError,
)

__all__ = [
    "ACK_ACCEPTED",
    "CLOCK_STYLES",
    "DEVICE_TYPE_SIZES",
    "DOCUMENTED_STYLE_MAX",
    "STYLE_MAX",
    "ClockPanel",
    "ClockSettings",
    "DeviceInfo",
    "HEIGHT",
    "LED_NAME",
    "Panel",
    "PanelError",
    "WIDTH",
    "brightness_cmd",
    "clock_mode_cmd",
    "power_cmd",
    "rotation_cmd",
    "set_time_cmd",
]

CMD_SET_TIME = 0x8001
CMD_CLOCK_MODE = 0x0106
CMD_BRIGHTNESS = 0x8004
CMD_ROTATION = 0x8006
CMD_POWER = 0x0107

LANGUAGE_ENGLISH = 0

# Status byte of a short-command acknowledgement. State 1 is "accepted"; state 0 is
# a refusal. Shared so the two entry points cannot drift into judging the same
# five bytes differently.
ACK_ACCEPTED = 0x01

# How far the style byte may be pushed. The four implementations that speak this
# dialect disagree -- one validates 0-8, one 1-9, one 1-8, one 0-7 -- and every
# one of them says the real answer depends on the panel. So 0-8 is what we offer,
# 9 is reachable, and which of them this unit actually renders is a question only
# the panel can answer. `send_clock.py --walk-styles` asks it.
DOCUMENTED_STYLE_MAX = 8
STYLE_MAX = 9

# The faces are ROM assets and differ between panels, so there is no honest name
# table to print. Walk them and trust your eyes.
CLOCK_STYLES: Dict[int, str] = {n: f"style {n}" for n in range(STYLE_MAX + 1)}

# Device-type byte from the set-time reply -> panel size. An unknown value is
# reported as unknown and never guessed: ../gif/README.md records that the vendor
# parser silently defaults an unrecognised byte to 64x64, which is how you end up
# uploading correctly-encoded content at the wrong geometry.
DEVICE_TYPE_SIZES: Dict[int, Tuple[int, int]] = {
    0x80: (64, 64),
    0x81: (32, 32),
    0x82: (32, 16),
    0x83: (64, 16),
    0x84: (96, 16),
    0x85: (64, 20),
    0x86: (128, 32),
    0x87: (144, 16),
    0x88: (192, 16),
    0x89: (48, 24),
    0x8A: (64, 32),
    0x8B: (96, 32),
    0x8C: (128, 32),
    0x8D: (96, 32),
    0x8E: (160, 32),
    0x8F: (192, 32),
    0x90: (256, 32),
    0x91: (320, 32),
    0x92: (384, 32),
    0x93: (448, 32),
}


# ------------------------------------------------------------------
# Command builders -- pure, no radio, unit-testable
# ------------------------------------------------------------------


def _short(command: int, *args: int) -> bytes:
    """Frame a short command: `[len u16 LE][cmd_lo][cmd_hi][args...]`.

    The length counts itself, which is why it is `len(body) + 2`.
    """
    for value in args:
        if not 0 <= value <= 255:
            raise ValueError(f"argument {value} does not fit in a byte")
    body = bytes([command & 0xFF, (command >> 8) & 0xFF, *args])
    return bytes([len(body) + 2, 0x00]) + body


def set_time_cmd(when: datetime, language: int = LANGUAGE_ENGLISH) -> bytes:
    """`08 00 01 80 hh mm ss lang` -- set the panel's wall clock.

    The hour is always 0-23, even when the face is showing 12-hour time. The
    panel counts in 24-hour internally and `format24` on the clock-mode command
    is purely a rendering flag, so converting here would leave the panel wrong
    for half of every day -- and the bug would look like a rendering bug.

    This frame doubles as the device-info query (the reply carries the panel
    size), so it cannot be skipped even when all you want is to probe.
    """
    if not 0 <= language <= 255:
        raise ValueError(f"language byte {language} does not fit in a byte")
    return _short(CMD_SET_TIME, when.hour, when.minute, when.second, language)


def clock_mode_cmd(
    when: datetime,
    *,
    style: int = 0,
    h24: bool = False,
    show_date: bool = False,
) -> bytes:
    """`0B 00 06 01 <style> <24h> <date> <yy> <mm> <dd> <dow>` -- pick the face.

    This command carries the *date* and selects the face; `set_time_cmd` carries
    the *time of day*. They are genuinely separate, and sending only this one is
    the most common way to end up with a panel showing a confidently wrong time:
    it keeps counting from whatever it had.

    `style`, `h24` and `show_date` are three plain bytes here. The other dialect
    packs them as bit flags into a single byte with an RGB colour after it. There
    is no colour argument in this one, so the face colour is not settable.
    """
    if not 0 <= style <= STYLE_MAX:
        raise ValueError(f"style must be 0-{STYLE_MAX}, got {style}")
    if not 2000 <= when.year <= 2099:
        raise ValueError(
            f"year {when.year} is outside 2000-2099; the panel carries two digits"
        )
    return _short(
        CMD_CLOCK_MODE,
        style,
        int(bool(h24)),
        int(bool(show_date)),
        when.year % 100,
        when.month,
        when.day,
        when.isoweekday(),  # 1=Mon .. 7=Sun, exactly the protocol's convention
    )


def brightness_cmd(level: int) -> bytes:
    """`05 00 04 80 <0-100>`. The one command already proven on this unit."""
    if not 0 <= level <= 100:
        raise ValueError(f"brightness must be 0-100, got {level}")
    return _short(CMD_BRIGHTNESS, level)


def rotation_cmd(quarter_turns: int) -> bytes:
    """`05 00 06 80 <0-3>` -- 0, 90, 180 or 270 degrees."""
    if not 0 <= quarter_turns <= 3:
        raise ValueError(f"rotation must be 0-3, got {quarter_turns}")
    return _short(CMD_ROTATION, quarter_turns)


def power_cmd(on: bool) -> bytes:
    """`05 00 07 01 <0|1>` -- blank or unblank the panel."""
    return _short(CMD_POWER, int(bool(on)))


# ------------------------------------------------------------------
# The set-time reply
# ------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceInfo:
    """Parsed reply to `set_time_cmd`.

        0B 00 01 80 <type> <mm echo> <ss echo> <lang echo> .. .. <password>
    """

    raw: bytes

    @property
    def device_byte(self) -> Optional[int]:
        return self.raw[4] if len(self.raw) >= 5 else None

    @property
    def size(self) -> Optional[Tuple[int, int]]:
        """`(width, height)`, or None when the type byte is not in the table.

        None means *unknown*, never a default. Guessing here is how you upload
        correctly-encoded content at the wrong geometry and see nothing.
        """
        return DEVICE_TYPE_SIZES.get(self.device_byte)

    @property
    def matches_this_panel(self) -> bool:
        return self.size == (WIDTH, HEIGHT)

    @staticmethod
    def looks_like_reply(ack: Ack) -> bool:
        return len(ack.raw) >= 5 and ack.raw[2:4] == b"\x01\x80"

    def __str__(self) -> str:
        if self.device_byte is None:
            return f"{self.raw.hex(' ')}  (too short to parse)"
        size = self.size
        where = f"{size[0]}x{size[1]}" if size else "unknown panel size"
        return f"{self.raw.hex(' ')}  (device byte {self.device_byte:#04x} -> {where})"


@dataclass(frozen=True)
class ClockSettings:
    """Everything the panel needs in order to run the clock on its own."""

    style: int = 0
    h24: bool = False
    show_date: bool = False

    def summary(self) -> str:
        return (
            f"style {self.style}, {'24-hour' if self.h24 else '12-hour'}, "
            f"date {'alternating with the time' if self.show_date else 'off'}"
        )


# ------------------------------------------------------------------
# Transport
# ------------------------------------------------------------------


class ClockPanel(Panel):
    """`Panel` plus the clock commands.

    Subclassing rather than copying keeps the connection pattern -- resolve by
    advertised name, hand the `BLEDevice` straight to `BleakClient` -- identical
    to the path that already works on this unit under Windows and bleak.
    """

    def _drop_stale_acks(self) -> None:
        while not self._acks.empty():
            self._acks.get_nowait()

    async def _send_short(self, packet: bytes, *, timeout: float = 5.0) -> Ack:
        self._drop_stale_acks()
        await self.write_raw(packet)
        return await self._await_ack(timeout=timeout)

    async def set_time(
        self, when: Optional[datetime] = None, *, language: int = LANGUAGE_ENGLISH
    ) -> DeviceInfo:
        """Push the wall clock, and read back what kind of panel answered."""
        when = when or datetime.now()
        ack = await self._send_short(set_time_cmd(when, language))
        if not DeviceInfo.looks_like_reply(ack):
            raise PanelError(
                f"unexpected answer to set-time: {ack.raw.hex(' ')} "
                "(expected a frame starting 0B 00 01 80)"
            )
        return DeviceInfo(ack.raw)

    async def set_clock_mode(
        self, when: Optional[datetime] = None, *, settings: ClockSettings
    ) -> Ack:
        when = when or datetime.now()
        return await self._send_short(
            clock_mode_cmd(
                when,
                style=settings.style,
                h24=settings.h24,
                show_date=settings.show_date,
            )
        )

    async def show_clock(
        self, settings: ClockSettings, when: Optional[datetime] = None
    ) -> Tuple[DeviceInfo, Ack]:
        """Both commands, in the order the vendor app uses.

        Time first: it doubles as the device probe, so a panel that is going to
        refuse anything refuses it here, before the display mode has changed.
        """
        when = when or datetime.now()
        info = await self.set_time(when)
        ack = await self.set_clock_mode(when, settings=settings)
        return info, ack

    async def set_rotation(self, quarter_turns: int) -> Ack:
        return await self._send_short(rotation_cmd(quarter_turns))

    async def set_power(self, on: bool) -> Ack:
        return await self._send_short(power_cmd(on))
