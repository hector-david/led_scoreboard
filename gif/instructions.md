Step 1 — get your panel's exact resolution. The device reports it on connect. The library exposes a DeviceInfo with width and height. Don't guess: the device-type byte maps to sizes from 32×16 up to 448×32, and the common ones are 32×32, 64×64, 64×16, 96×16, 64×20.

Step 2 — prep the GIF. This step is where the quality actually gets decided, and it's the step people skip.

The panel decodes GIF natively but the dimensions must match the display exactly. Keep the file small: the ESPHome port author tested GIFs up to 500 KB but warns those can take minutes to transfer, while anything up to ~32 KB loads in reasonable time.

For a 32×32 panel:

bash
ffmpeg -i input.gif -filter_complex \
  "fps=20,scale=32:32:flags=lanczos,split[s0][s1];\
   [s0]palettegen=max_colors=64[p];\
   [s1][p]paletteuse=dither=none" \
  -loop 0 out32.gif

Use flags=lanczos, not neighbor. Lanczos is what produces the soft partial-brightness edges that make motion read as smooth on a 32×32 grid — that's the whole anti-aliasing effect from the earlier answer, and nearest-neighbor throws it away. Try dither=bayer:bayer_scale=3 if you have gradients that band, but on a small LED panel dithering often just looks like noise, so start with dither=none.

If your source isn't square, either crop it in ffmpeg or let the library do it — send_image takes a resize_method of crop (fills the area, crops the excess) or fit (fits the whole image with black padding).

Check the output size with ls -lh. If it's over ~50 KB, drop fps, cut max_colors, or trim frames.

Step 3 — send it.

python
from pypixelcolor import Client

client = Client("XX:XX:XX:XX:XX:XX")   # macOS gives you a CoreBluetooth UUID, not a MAC
client.connect()
client.send_image("out32.gif", resize_method="fit", save_slot=1)
client.disconnect()

send_image signature is (path, resize_method, device_info, save_slot), where device_info gets injected automatically by the session so the auto-resize kicks in. save_slot=0 means display now without persisting; >= 1 writes it to that storage slot. Verify against pypixelcolor --help and the current docs, since the image API was refactored fairly recently (fit_mode was renamed to resize_method).

Under the hood it's building the 0x0003 GIF command, splitting into 12 KB windows, and putting the total payload size and CRC32 in the first window. The device ACKs each chunk and returns 3 on success or 0 if the CRC fails.

Step 4 — loop several of them. Once GIFs are in slots, the program-list command hands the firmware a list of slot numbers and it cycles through them endlessly. Slot numbers run 1–100 on at least some units.

Gotchas that will cost you an evening

Bootloops are real. Both the iPixel-CLI author and the ESPHome author warn that sending invalid content to a slot can crash the display firmware into a boot loop, and that recovering means landing a clear command inside a very tight window before the device reads its EEPROM. So: test with save_slot=0 before you write to a slot, and don't fire unrelated commands while a program list is still uploading.

There is no single protocol across these panels. The iPixel app itself branches on firmware version and display size, and several repos that work fine on one panel show nothing on another. If text and images silently fail while brightness and power work, that's almost certainly what you're hitting — the ESPHome author found his 32×32 only accepted specific monospaced font matrices, which broke every existing implementation.

Kill the phone app before connecting. Only one central can hold the BLE link.

On Linux, bluetoothctl scan on and look for a name starting with LED_BLE_. On macOS you'll get a CoreBluetooth UUID rather than a MAC address, which bleak handles fine but means the identifier isn't portable between machines.