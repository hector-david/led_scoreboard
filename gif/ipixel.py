"""iPixel BLE LED matrix: device facts, packet framing, and transport.

Everything device-specific for `LED_BLE_CD9B89CA` lives here. The framing and
transport are lifted from the paths that are already proven on this exact unit
(`../src/led_scoreboard.py`, `../src/send_image.py`, and the capture recorded in
`ipixel_16x32_led_protocol_notes.md`), with the GIF command added.

Proven on this panel
    0x0002  PNG upload, tail byte 0x00 + buffer/slot number, ACKed `05 00 02 00 03`
    0x8004  brightness,                                      ACKed `05 00 04 80 01`
    0x0105  set pixel
Not yet proven on this panel
    0x0003  GIF upload, tail byte 0x02 + slot. Same envelope, different command.
            If this firmware lacks it, expect a silent black panel rather than a
            NAK -- see play_frames.py for a fallback that uses only 0x0002.
"""

from __future__ import annotations

import asyncio
import struct
import zlib
from dataclasses import dataclass
from typing import Iterator, List, Optional

from bleak import BleakClient, BleakScanner

# ------------------------------------------------------------------
# Device facts (confirmed by working code, not assumed)
# ------------------------------------------------------------------

LED_NAME = "LED_BLE_CD9B89CA"
LED_ADDRESS = "96:84:CD:9B:89:CA"  # observed once; scan by name in preference
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"

WIDTH = 32
HEIGHT = 16

# The last header byte. led_scoreboard.py has written 1 here hundreds of times
# with no ill effect, so 1 is the only value with hardware evidence behind it.
DEFAULT_SLOT = 1

CMD_PNG = 0x0002
CMD_GIF = 0x0003

# The device splits large payloads into 12 KB windows and ACKs each one.
WINDOW_SIZE = 12 * 1024
HEADER_LEN = 13  # cmd(2) + option(1) + size(4) + crc(4) + kind(1) + slot(1)
# Largest payload that still fits in a single window (12303 bytes on the wire).
# Staying under this is the cheapest safety win available: it means the untested
# continuation option byte 0x02 is never sent, multi-window ACK behaviour never
# matters, and there is no window boundary to be interrupted at.
ONE_WINDOW_MAX = WINDOW_SIZE  # 12288

# Largest single GATT write proven on this unit is 472 bytes; 244 is what the
# vendor library uses and is comfortably below both that and bleak's 512 cap.
CHUNK_SIZE = 244

# ACK status byte, per the captured transfer in the protocol notes.
ACK_FAIL = 0x00  # failure / CRC problem
ACK_PROGRESS = 0x01  # intermediate, more windows expected
ACK_SUCCESS = 0x03  # transfer complete


class PanelError(RuntimeError):
    """The panel refused a transfer, or never answered."""


# ------------------------------------------------------------------
# Framing
# ------------------------------------------------------------------


@dataclass(frozen=True)
class Ack:
    raw: bytes

    @property
    def command(self) -> Optional[int]:
        if len(self.raw) < 4:
            return None
        return struct.unpack_from("<H", self.raw, 2)[0]

    @property
    def status(self) -> Optional[int]:
        return self.raw[4] if len(self.raw) >= 5 else None

    def __str__(self) -> str:
        names = {ACK_FAIL: "FAIL/CRC", ACK_PROGRESS: "in-progress", ACK_SUCCESS: "success"}
        st = self.status
        return f"{self.raw.hex(' ')}  (cmd 0x{(self.command or 0):04x}, {names.get(st, f'unknown {st}')})"


def build_windows(payload: bytes, *, is_gif: bool, slot: int = DEFAULT_SLOT) -> List[bytes]:
    """Split a PNG or GIF payload into ready-to-write window messages.

    Every window repeats the size and CRC32 of the *whole* payload; only the
    option byte distinguishes the first window (0x00, "start") from the rest
    (0x02, "append"). Layout, matching README.md and the protocol notes:

        [total_len u16] [cmd u16] [option] [size u32] [crc32 u32] [kind] [slot] [chunk]

    where total_len is the length of the whole message, i.e. 15 + len(chunk).
    """
    if not 0 <= slot <= 255:
        raise ValueError(f"slot must fit in a byte, got {slot}")
    if not payload:
        raise ValueError("empty payload")

    command = CMD_GIF if is_gif else CMD_PNG
    kind = 0x02 if is_gif else 0x00
    size = struct.pack("<I", len(payload))
    crc = struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)

    windows: List[bytes] = []
    for index, start in enumerate(range(0, len(payload), WINDOW_SIZE)):
        chunk = payload[start : start + WINDOW_SIZE]
        option = 0x00 if index == 0 else 0x02
        header = struct.pack("<H", command) + bytes([option]) + size + crc + bytes([kind, slot])
        windows.append(struct.pack("<H", HEADER_LEN + 2 + len(chunk)) + header + chunk)
    return windows


def describe_windows(windows: List[bytes]) -> str:
    lines = []
    for i, w in enumerate(windows):
        lines.append(f"  window {i}: {len(w):>6} bytes on the wire, header {w[:15].hex(' ')}")
    return "\n".join(lines)


def chunked(data: bytes, size: int = CHUNK_SIZE) -> Iterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


# ------------------------------------------------------------------
# Transport
# ------------------------------------------------------------------


class Panel:
    """A connected panel. Use as an async context manager.

    Connection pattern is the one already proven here: resolve the device by
    advertised name (never by address string -- on Windows bleak resolves a bare
    string via find_device_by_address, which only ever matches a MAC), then hand
    the BLEDevice object straight to BleakClient.
    """

    # Acknowledgements are small and only the most recent ones are ever useful.
    # A bound keeps play_frames.py, which streams frames for hours without
    # consuming acks, from growing this queue without limit.
    MAX_PENDING_ACKS = 16

    def __init__(self, name: str = LED_NAME, *, verbose: bool = True, ack_timeout: float = 15.0):
        self.name = name
        self.verbose = verbose
        self.ack_timeout = ack_timeout
        self._client: Optional[BleakClient] = None
        self._acks: "asyncio.Queue[Ack]" = asyncio.Queue()
        self._awaiting = False

    # -- lifecycle ------------------------------------------------

    async def __aenter__(self) -> "Panel":
        self._log(f"Searching for {self.name}...")
        try:
            device = await BleakScanner.find_device_by_name(self.name, timeout=15)
        except Exception as exc:
            raise PanelError(f"BLE scan failed: {exc}") from exc
        if device is None:
            raise PanelError(
                f"{self.name} not found. The panel is off, out of range, or still held by "
                "the iPixel phone app -- only one BLE central can hold the link."
            )
        self._log(f"Found {device.name} at {device.address}, connecting...")
        self._client = BleakClient(device)
        try:
            await self._client.connect()
        except Exception as exc:
            # bleak's WinRT backend raises TimeoutError and OSError here as well
            # as BleakError -- a connect timeout is the most likely failure of
            # the lot, so don't leave a half-built client behind for any of them.
            self._client = None
            raise PanelError(f"could not connect to {self.name}: {exc}") from exc
        try:
            await self._client.start_notify(NOTIFY_UUID, self._on_notify)
            mtu = getattr(self._client, "mtu_size", None)
        except BaseException as exc:  # don't leave the link open on a partial setup
            try:
                await self._client.disconnect()
            except Exception:
                pass  # a failing cleanup must not mask the real error
            self._client = None
            if isinstance(exc, Exception):
                raise PanelError(f"could not subscribe to notifications: {exc}") from exc
            raise
        self._log(f"Connected. MTU {mtu}." if mtu else "Connected.")
        return self

    async def __aexit__(self, *exc) -> None:
        client, self._client = self._client, None
        if client is not None:
            # Teardown must never replace whatever exception is already in
            # flight, and a dropped link makes any of these raise.
            try:
                if client.is_connected:
                    try:
                        await client.stop_notify(NOTIFY_UUID)
                    except Exception:
                        pass
                    await client.disconnect()
            except Exception:
                pass
        self._log("Disconnected.")

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def _on_notify(self, _sender, data: bytearray) -> None:
        ack = Ack(bytes(data))
        self._log(f"  <- {ack}")
        # Bound the backlog for callers that stream without ever consuming acks,
        # but never drop while someone is waiting: a queued item stays counted
        # until the waiter actually resumes, so evicting here would discard the
        # very ack they were woken for -- including a 0x00 rejection.
        if not self._awaiting:
            while self._acks.qsize() >= self.MAX_PENDING_ACKS:
                try:
                    self._acks.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover
                    break
        self._acks.put_nowait(ack)

    def drain_acks(self) -> List[Ack]:
        """Take everything queued since the last look. Used by callers that
        stream without waiting, so a failure still surfaces."""
        out = []
        while not self._acks.empty():
            out.append(self._acks.get_nowait())
        return out

    # -- sending --------------------------------------------------

    async def write_raw(self, packet: bytes) -> None:
        """One packet, chunked to CHUNK_SIZE, written with response."""
        if self._client is None:
            raise PanelError("not connected -- use Panel as an async context manager")
        try:
            for piece in chunked(packet):
                await self._client.write_gatt_char(WRITE_UUID, piece, response=True)
        except Exception as exc:  # bleak raises OSError here too, not just BleakError
            raise PanelError(f"write failed: {exc}") from exc

    async def _await_ack(self, timeout: Optional[float] = None) -> Ack:
        self._awaiting = True
        try:
            return await asyncio.wait_for(self._acks.get(), timeout or self.ack_timeout)
        except asyncio.TimeoutError:
            raise PanelError(
                f"No acknowledgement within {timeout or self.ack_timeout:.0f}s. The panel may not "
                "support this command, or the link dropped."
            ) from None
        finally:
            self._awaiting = False

    async def send_payload(self, payload: bytes, *, is_gif: bool, slot: int = DEFAULT_SLOT) -> Ack:
        """Upload a full PNG or GIF payload and wait for the panel to accept it."""
        windows = build_windows(payload, is_gif=is_gif, slot=slot)
        kind = "GIF" if is_gif else "PNG"
        self._log(
            f"Sending {len(payload)} byte {kind} as {len(windows)} window(s) "
            f"to slot {slot}:\n{describe_windows(windows)}"
        )
        while not self._acks.empty():  # drop anything stale before we start
            self._acks.get_nowait()

        last: Optional[Ack] = None
        for index, window in enumerate(windows):
            await self.write_raw(window)
            last = await self._await_ack()
            if last.status is None:
                raise PanelError(
                    f"Malformed acknowledgement after window {index + 1}: {last.raw.hex(' ')}"
                )
            if last.status == ACK_FAIL:
                raise PanelError(
                    f"Panel rejected window {index + 1} of {len(windows)} "
                    "(status 00 = failure/CRC). Nothing further was sent."
                )
            # A success ack before the last window means the panel stopped
            # listening early. Continuing would write into an unknown state, and
            # reporting success would hide an unfinished upload.
            if last.status == ACK_SUCCESS and index != len(windows) - 1:
                raise PanelError(
                    f"Panel reported the transfer complete after window {index + 1} of "
                    f"{len(windows)}; {len(windows) - index - 1} window(s) were never sent."
                )

        if last is None or last.status != ACK_SUCCESS:
            raise PanelError(
                f"Panel never confirmed the transfer. Last acknowledgement: "
                f"{last if last else 'none'} (expected status 03)."
            )
        self._log(f"{kind} accepted.")
        return last

    async def send_gif_bytes(self, data: bytes, *, slot: int = DEFAULT_SLOT) -> Ack:
        return await self.send_payload(data, is_gif=True, slot=slot)

    async def send_png_bytes(self, data: bytes, *, slot: int = DEFAULT_SLOT) -> Ack:
        return await self.send_payload(data, is_gif=False, slot=slot)

    async def set_brightness(self, level: int) -> None:
        """0-100. Proven command; handy for confirming the link before a big upload."""
        level = max(0, min(100, int(level)))
        await self.write_raw(bytes([0x05, 0x00, 0x04, 0x80, level]))
        await self._await_ack(timeout=5.0)

    async def show_slot(self, number: int) -> None:
        """Display a stored slot. Untested on this unit -- see README."""
        await self.write_raw(bytes([0x07, 0x00, 0x08, 0x80, 0x01, 0x00, number & 0xFF]))
        await self._await_ack(timeout=5.0)
