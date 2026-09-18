#include "PngImage.h"

using Config::DISPLAY_WIDTH;
using Config::DISPLAY_HEIGHT;


bool PngImage::encode(const Framebuffer& framebuffer) {

  length = 0;

  // Tell PNGenc to write directly into our RAM buffer.
  int result = encoder.open(buffer, Config::PNG_BUFFER_SIZE);

  if (result != PNG_SUCCESS) {
    Serial.printf("PNG ERROR: open() failed: %d\n", result);
    return false;
  }


  // Match the Python version:
  //
  // 32 x 16
  // RGB888
  // compression level 6
  //
  // NOTE: PNGenc's 4th argument is bits per PIXEL,
  // not bits per channel. It uses it to size each
  // row ((width * bpp) / 8), so truecolor must be 24.
  // Passing 8 makes it encode only the first third
  // of every row, producing a PNG the panel cannot
  // decode (it still ACKs the transfer).
  result = encoder.encodeBegin(
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
    PNG_PIXEL_TRUECOLOR,
    24,
    nullptr,
    6
  );

  if (result != PNG_SUCCESS) {
    Serial.printf("PNG ERROR: encodeBegin() failed: %d\n", result);
    encoder.close();
    return false;
  }


  // PNGenc accepts one row at a time.
  uint8_t row[DISPLAY_WIDTH * 3];

  for (int y = 0; y < DISPLAY_HEIGHT; y++) {

    int index = 0;

    for (int x = 0; x < DISPLAY_WIDTH; x++) {

      RGB pixel = framebuffer.getPixel(x, y);

      row[index++] = pixel.r;
      row[index++] = pixel.g;
      row[index++] = pixel.b;
    }

    result = encoder.addLine(row);

    if (result != PNG_SUCCESS) {
      Serial.printf("PNG ERROR: addLine() failed on row %d: %d\n", y, result);
      encoder.close();
      return false;
    }
  }


  // close() finalizes the PNG and returns
  // the number of bytes written.
  int finalSize = encoder.close();

  if (finalSize <= 0) {
    Serial.printf("PNG ERROR: close() returned %d\n", finalSize);
    return false;
  }

  length = (size_t)finalSize;

  return true;
}


void PngImage::printInfo() const {

  Serial.printf(
    "PNG encoded successfully: %u bytes\n",
    (unsigned int)length
  );

  Serial.print("PNG signature: ");

  size_t count = min(length, (size_t)8);

  for (size_t i = 0; i < count; i++) {

    if (buffer[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(buffer[i], HEX);

    if (i < count - 1) {
      Serial.print(" ");
    }
  }

  Serial.println();

  Serial.printf(
    "Projected LED packet size: %u bytes\n",
    (unsigned int)(length + Config::LED_HEADER_SIZE)
  );
}
