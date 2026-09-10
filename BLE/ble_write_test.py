import asyncio
from bleak import BleakScanner, BleakClient

PHONE_NAME = "Galaxy S26 Ultra"
CHAR_UUID = "87654321-4321-4321-4321-cba987654321"

async def main():
    print("Finding phone...")

    device = await BleakScanner.find_device_by_name(
        PHONE_NAME,
        timeout=15
    )

    if device is None:
        print("Phone not found")
        return

    async with BleakClient(device) as client:
        print("Connected:", client.is_connected)

        message = b"Hello from Python"

        print("Writing...")
        await client.write_gatt_char(
            CHAR_UUID,
            message,
            response=True
        )

        print("Write successful!")

asyncio.run(main())