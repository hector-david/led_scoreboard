import sys
import asyncio
from pathlib import Path
from io import BytesIO
import struct
import zlib
import argparse

from PIL import Image, ImageOps
from bleak import BleakScanner, BleakClient


WIDTH = 32
HEIGHT = 16
BUFFER_NUMBER = 1

LED_NAME = "LED_BLE_CD9B89CA"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"


def prepare_image(image_path: Path, mode: str) -> Image.Image:
    img = Image.open(image_path).convert("RGBA")

    if mode == "crop":
        # Fill the entire 32x16 display.
        # Preserve aspect ratio and crop excess.
        img = ImageOps.fit(
            img,
            (WIDTH, HEIGHT),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5)
        )

        # Composite transparency over black
        canvas = Image.new(
            "RGBA",
            (WIDTH, HEIGHT),
            (0, 0, 0, 255)
        )

        canvas.alpha_composite(img)

    else:
        # FIT mode:
        # Keep the entire image visible without distortion.
        img.thumbnail(
            (WIDTH, HEIGHT),
            Image.Resampling.LANCZOS
        )

        canvas = Image.new(
            "RGBA",
            (WIDTH, HEIGHT),
            (0, 0, 0, 255)
        )

        x = (WIDTH - img.width) // 2
        y = (HEIGHT - img.height) // 2

        canvas.alpha_composite(img, (x, y))

    return canvas.convert("RGB")

def build_png_packet(image_path: Path, mode: str) -> bytes:
    img = prepare_image(image_path, mode)

    bio = BytesIO()
    img.save(
        bio,
        format="PNG",
        compress_level=6,
        icc_profile=None
    )

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

    print(f"Image resized to: {WIDTH}x{HEIGHT}")
    print(f"PNG payload: {len(png_data)} bytes")
    print(f"Total packet: {len(packet)} bytes")

    return bytes(packet)


def notification_handler(sender, data):
    print("LED response:", data.hex(" "))


async def send_image(packet: bytes):
    print(f"Searching for {LED_NAME}...")

    device = await BleakScanner.find_device_by_name(
        LED_NAME,
        timeout=15
    )

    if device is None:
        print("Error: LED screen not found.")
        return

    print(f"Found: {device.name}")
    print("Connecting...")

    async with BleakClient(device) as client:
        print("Connected.")

        await client.start_notify(
            NOTIFY_UUID,
            notification_handler
        )

        print("Sending image...")

        await client.write_gatt_char(
            WRITE_UUID,
            packet,
            response=True
        )

        await asyncio.sleep(2)

        await client.stop_notify(NOTIFY_UUID)

        print("Done.")


async def main():
    parser = argparse.ArgumentParser(
        description="Send an image to the 32x16 iPixel LED display."
    )

    parser.add_argument(
        "image",
        type=Path,
        help="Image file to display"
    )

    mode_group = parser.add_mutually_exclusive_group()

    mode_group.add_argument(
        "--fit",
        action="store_true",
        help="Fit entire image inside display with black bars if necessary"
    )

    mode_group.add_argument(
        "--crop",
        action="store_true",
        help="Fill entire display and crop excess image"
    )

    args = parser.parse_args()

    image_path = args.image

    if not image_path.exists():
        print(f"Error: file not found: {image_path}")
        return

    # FIT is the default
    mode = "crop" if args.crop else "fit"

    print(f"Loading: {image_path}")
    print(f"Resize mode: {mode.upper()}")

    packet = build_png_packet(image_path, mode)

    await send_image(packet)


if __name__ == "__main__":
    asyncio.run(main())