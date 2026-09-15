import asyncio
import struct
import zlib
from io import BytesIO
from typing import List, Tuple

from PIL import Image
from bleak import BleakClient, BleakScanner

LED_NAME = "LED_BLE_CD9B89CA"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"

WIDTH = 32
HEIGHT = 16
BUFFER_NUMBER = 1

BLACK = (0, 0, 0)
TEAM1_COLOR = (0, 180, 255)
TEAM2_COLOR = (255, 90, 50)
DIVIDER_COLOR = (255, 255, 255)
SCORE_COLOR = (255, 255, 255)

# ------------------------------
# Fonts
# ------------------------------

SMALL_FONT = {
    "T": [
        "111",
        "010",
        "010",
        "010",
        "010",
    ],
    "1": [
        "010",
        "110",
        "010",
        "010",
        "111",
    ],
    "2": [
        "111",
        "001",
        "111",
        "100",
        "111",
    ],
}

# Tall 6x10 digits. These fill the extra vertical space (two rows above and
# one row below the old 7-row glyphs) so the scores are as large as possible.
DIGITS = {
    "0": [
        "011110",
        "100001",
        "100001",
        "100001",
        "100001",
        "100001",
        "100001",
        "100001",
        "100001",
        "011110",
    ],
    "1": [
        "001100",
        "011100",
        "001100",
        "001100",
        "001100",
        "001100",
        "001100",
        "001100",
        "001100",
        "011110",
    ],
    "2": [
        "011110",
        "100001",
        "000001",
        "000001",
        "000010",
        "000100",
        "001000",
        "010000",
        "100000",
        "111111",
    ],
    "3": [
        "011110",
        "100001",
        "000001",
        "000001",
        "001110",
        "000001",
        "000001",
        "000001",
        "100001",
        "011110",
    ],
    "4": [
        "000110",
        "001010",
        "001010",
        "010010",
        "010010",
        "100010",
        "111111",
        "000010",
        "000010",
        "000010",
    ],
    "5": [
        "111111",
        "100000",
        "100000",
        "100000",
        "111110",
        "000001",
        "000001",
        "000001",
        "100001",
        "011110",
    ],
    "6": [
        "001110",
        "010000",
        "100000",
        "100000",
        "111110",
        "100001",
        "100001",
        "100001",
        "100001",
        "011110",
    ],
    "7": [
        "111111",
        "000001",
        "000010",
        "000010",
        "000100",
        "000100",
        "001000",
        "001000",
        "010000",
        "010000",
    ],
    "8": [
        "011110",
        "100001",
        "100001",
        "100001",
        "011110",
        "100001",
        "100001",
        "100001",
        "100001",
        "011110",
    ],
    "9": [
        "011110",
        "100001",
        "100001",
        "100001",
        "100001",
        "011111",
        "000001",
        "000001",
        "000010",
        "011100",
    ],
}


# ------------------------------
# Framebuffer helpers
# ------------------------------

def blank_frame():
    return [[BLACK for _ in range(WIDTH)] for _ in range(HEIGHT)]


def draw_bitmap(frame, bitmap, x, y, color):
    for row, bits in enumerate(bitmap):
        for col, bit in enumerate(bits):
            if bit == "1":
                px = x + col
                py = y + row
                if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                    frame[py][px] = color


def draw_small_text(frame, text, x, y, color):
    cursor = x
    for ch in text:
        draw_bitmap(frame, SMALL_FONT[ch], cursor, y, color)
        cursor += 4


def draw_number(frame, value, area_x, area_w, y, color):
    value = max(0, min(99, value))
    text = str(value)

    digit_w = 6
    gap = 1
    total_w = len(text) * digit_w + (len(text) - 1) * gap
    x = area_x + (area_w - total_w) // 2

    for ch in text:
        draw_bitmap(frame, DIGITS[ch], x, y, color)
        x += digit_w + gap


def build_scoreboard_frame(t1: int, t2: int):
    frame = blank_frame()

    # Static labels
    draw_small_text(frame, "T1", 4, 0, TEAM1_COLOR)
    draw_small_text(frame, "T2", 21, 0, TEAM2_COLOR)

    # Center divider
    for y in range(HEIGHT):
        frame[y][15] = DIVIDER_COLOR

    # Scores (10px tall, rows 6-15: uses the two rows above and one below the
    # old 7px glyphs, leaving row 5 as a gap under the T1/T2 labels)
    draw_number(frame, t1, 2, 11, 6, SCORE_COLOR)
    draw_number(frame, t2, 19, 11, 6, SCORE_COLOR)

    return frame


# ------------------------------
# BLE / protocol helpers
# ------------------------------
#
# This device does NOT accept concatenated per-pixel commands in a single
# write. Its real "bulk" path (see send_image.py) is a full-frame PNG uploaded
# in one write with command 0x02 0x00, a length header covering the whole
# payload, and a CRC32 of the PNG. We render the scoreboard to a 32x16 image
# and push the entire frame in one shot instead of pixel-by-pixel.

def frame_to_image(frame: List[List[Tuple[int, int, int]]]) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    # frame is row-major (y outer, x inner), which matches PIL's putdata order.
    img.putdata([frame[y][x] for y in range(HEIGHT) for x in range(WIDTH)])
    return img


def build_frame_packet(frame: List[List[Tuple[int, int, int]]]) -> bytes:
    img = frame_to_image(frame)

    bio = BytesIO()
    img.save(bio, format="PNG", compress_level=6, icc_profile=None)
    png_data = bio.getvalue()

    crc = zlib.crc32(png_data) & 0xFFFFFFFF
    total_len = 15 + len(png_data)

    packet = bytearray()
    packet.extend(struct.pack("<H", total_len))
    packet.extend(b"\x02\x00")
    packet.append(0x00)
    packet.extend(struct.pack("<I", len(png_data)))
    packet.extend(struct.pack("<I", crc))
    packet.append(0x00)
    packet.append(BUFFER_NUMBER)
    packet.extend(png_data)

    return bytes(packet)


def notification_handler(sender, data):
    print("LED response:", data.hex(" "))


async def send_frame(client: BleakClient, frame):
    packet = build_frame_packet(frame)
    await client.write_gatt_char(WRITE_UUID, packet, response=True)
    print(f"Frame sent: {len(packet)} bytes (single write)")


# ------------------------------
# App
# ------------------------------

async def main():
    print(f"Searching for {LED_NAME}...")
    device = await BleakScanner.find_device_by_name(LED_NAME, timeout=15)
    if device is None:
        print("LED screen not found.")
        return

    async with BleakClient(device) as client:
        print("Connected:", client.is_connected)

        await client.start_notify(NOTIFY_UUID, notification_handler)

        team1 = 0
        team2 = 0

        print("Drawing initial frame...")
        await send_frame(client, build_scoreboard_frame(team1, team2))

        print()
        print("Controls:")
        print("  1 = Team 1 +1")
        print("  2 = Team 2 +1")
        print("  a = Team 1 -1")
        print("  b = Team 2 -1")
        print("  r = reset")
        print("  q = quit")
        print()

        while True:
            command = (await asyncio.to_thread(input, f"T1 {team1} - T2 {team2} > ")).strip().lower()

            if command == "1":
                team1 = min(99, team1 + 1)
            elif command == "2":
                team2 = min(99, team2 + 1)
            elif command == "a":
                team1 = max(0, team1 - 1)
            elif command == "b":
                team2 = max(0, team2 - 1)
            elif command == "r":
                team1 = 0
                team2 = 0
            elif command == "q":
                break
            else:
                print("Unknown command.")
                continue

            await send_frame(client, build_scoreboard_frame(team1, team2))

        await client.stop_notify(NOTIFY_UUID)


if __name__ == "__main__":
    asyncio.run(main())
