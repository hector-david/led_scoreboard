import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for BLE devices for 10 seconds...\n")

    devices = await BleakScanner.discover(
        timeout=10,
        return_adv=True
    )

    for address, (device, adv) in devices.items():
        print("=" * 60)
        print(f"Address:      {address}")
        print(f"Device name:  {device.name}")
        print(f"Local name:   {adv.local_name}")
        print(f"RSSI:         {adv.rssi}")
        print(f"Services:     {adv.service_uuids}")

asyncio.run(main())