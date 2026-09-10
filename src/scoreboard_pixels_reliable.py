import asyncio
from typing import List, Tuple

from bleak import BleakClient, BleakScanner

LED_NAME = "LED_BLE_CD9B89CA"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"

WIDTH = 32
HEIGHT = 16

BLACK = (0, 0, 0)
TEAM1_COLOR = (0, 180, 255)
TEAM2_COLOR = (255, 90, 50)
DIVIDER_COLOR = (255, 255, 255)
SCORE_COLOR = (255, 255, 255)

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

DIGITS = {
    "0": [
        "01110",
        "10001",
        "10001",
        "10001",
        "10001",
        "10001",
        "01110",
    ],
    "1": [
        "00100",
        "01100",
        "00100",
        "00100",
        "00100",
        "00100",
        "01110",
    ],
    "2": [
        "01110",
        "10001",
        "00001",
        "00010",
        "00100",
        "01000",
        "11111",
    ],
    "3": [
        "11110",
        "00001",
        "00001",
        "01110",
        "00001",
        "00001",
        "11110",
    ],
    "4": [
        "00010",
        "00110",
        "01010",
        "10010",
        "11111",
        "00010",
        "00010",
    ],
    "5": [
        "11111",
        "10000",
        "10000",
        "11110",
        "00001",
        "00001",
        "11110",
    ],
    "6": [
        "01110",
        "10000",
        "10000",
        "11110",
        "10001",
        "10001",
        "01110",
    ],
    "7": [
        "11111",
        "00001",
        "00010",
        "00100",
        "01000",
        "01000",
        "01000",
    ],
    "8": [
        "01110",
        "10001",
        "10001",
        "01110",
        "10001",
        "10001",
        "01110",
    ],
    "9": [
        "01110",
        "10001",
        "10001",
        "01111",
        "00001",
        "00001",
        "01110",
    ],
}


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
    digit_w = 5
    gap = 1
    total_w = len(text) * digit_w + (len(text) - 1) * gap
    x = area_x + (area_w - total_w) // 2
    for ch in text:
        draw_bitmap(frame, DIGITS[ch], x, y, color)
        x += digit_w + gap


def build_scoreboard_frame(t1: int, t2: int):
    frame = blank_frame()

    draw_small_text(frame, "T1", 4, 0, TEAM1_COLOR)
    draw_small_text(frame, "T2", 21, 0, TEAM2_COLOR)

    for y in range(0, HEIGHT):
        frame[y][15] = DIVIDER_COLOR

    draw_number(frame, t1, 2, 11, 8, SCORE_COLOR)
    draw_number(frame, t2, 19, 11, 8, SCORE_COLOR)

    return frame


def pixel_packet(x: int, y: int, rgb: Tuple[int, int, int]) -> bytes:
    r, g, b = rgb
    return bytes([
        0x0A, 0x00,
        0x05, 0x01,
        0x00,
        r, g, b,
        x, y
    ])


async def enable_diy_mode(client: BleakClient):
    packet = bytes([0x05, 0x00, 0x04, 0x01, 0x01])
    await client.write_gatt_char(WRITE_UUID, packet, response=True)
    await asyncio.sleep(0.05)


async def write_pixel_reliable(client: BleakClient, x: int, y: int, rgb: Tuple[int, int, int]):
    # response=True is slower, but this is exactly the point:
    # reliability matters more than speed for now.
    await client.write_gatt_char(WRITE_UUID, pixel_packet(x, y, rgb), response=True)


async def send_full_frame_reliable(client: BleakClient, frame: List[List[Tuple[int, int, int]]]):
    # Write every pixel, not just non-black ones.
    # That avoids stale pixels and gives us a deterministic baseline.
    count = 0
    for y in range(HEIGHT):
        for x in range(WIDTH):
            await write_pixel_reliable(client, x, y, frame[y][x])
            count += 1
        await asyncio.sleep(0.01)
    print(f"Full frame written reliably: {count} pixels")


async def send_diff_reliable(client: BleakClient, old_frame, new_frame):
    changed = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if old_frame[y][x] != new_frame[y][x]:
                changed.append((x, y, new_frame[y][x]))

    # First pass
    for x, y, rgb in changed:
        await write_pixel_reliable(client, x, y, rgb)

    # Tiny pause, then second pass to heal any occasional misses.
    # Overkill for normal BLE, but this device has already shown it drops pixels
    # when we push it aggressively.
    if changed:
        await asyncio.sleep(0.02)
        for x, y, rgb in changed:
            await write_pixel_reliable(client, x, y, rgb)

    print(f"Reliable diff update: {len(changed)} changed pixels")


async def main():
    print(f"Searching for {LED_NAME}...")
    device = await BleakScanner.find_device_by_name(LED_NAME, timeout=15)
    if device is None:
        print("LED screen not found.")
        return

    async with BleakClient(device) as client:
        print("Connected:", client.is_connected)
        await enable_diy_mode(client)

        team1 = 0
        team2 = 0

        current_frame = blank_frame()
        first_frame = build_scoreboard_frame(team1, team2)

        print("Drawing full baseline frame reliably...")
        await send_full_frame_reliable(client, first_frame)
        current_frame = first_frame

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

            new_frame = build_scoreboard_frame(team1, team2)
            await send_diff_reliable(client, current_frame, new_frame)
            current_frame = new_frame


if __name__ == "__main__":
    asyncio.run(main())
