import asyncio
from bleak import BleakScanner, BleakClient

PHONE_NAME = "Galaxy S26 Ultra"

async def main():
    print("Searching for phone...")

    device = await BleakScanner.find_device_by_name(
        PHONE_NAME,
        timeout=15
    )

    if device is None:
        print("Phone not found.")
        return

    print(f"Found: {device.name} | {device.address}")
    print("Connecting...")

    async with BleakClient(device) as client:
        print("Connected:", client.is_connected)

        print("\nServices and characteristics:")
        for service in client.services:
            print(f"\nSERVICE: {service.uuid}")

            for char in service.characteristics:
                print(f"  CHAR: {char.uuid}")
                print(f"  Properties: {char.properties}")

asyncio.run(main())