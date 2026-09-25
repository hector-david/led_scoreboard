#include "LedImagePacket.h"

using Config::LED_HEADER_SIZE;

// Which of the panel's image slots to write into.
static const uint8_t BUFFER_NUMBER = 1;


bool LedImagePacket::build(const uint8_t* png, size_t pngSize, bool quiet) {

  if (pngSize == 0) {
    Serial.println("PACKET ERROR: PNG size is zero.");
    return false;
  }

  length = LED_HEADER_SIZE + pngSize;

  if (length > sizeof(buffer)) {
    Serial.println("PACKET ERROR: packet buffer too small.");
    length = 0;
    return false;
  }

  uint32_t crc = crc32(png, pngSize);


  // Bytes 0-1: total packet length
  writeLe16(&buffer[0], (uint16_t)length);

  // Bytes 2-3: command 0x0002
  buffer[2] = 0x02;
  buffer[3] = 0x00;

  // Byte 4
  buffer[4] = 0x00;

  // Bytes 5-8: PNG byte length
  writeLe32(&buffer[5], (uint32_t)pngSize);

  // Bytes 9-12: PNG CRC32
  writeLe32(&buffer[9], crc);

  // Byte 13
  buffer[13] = 0x00;

  // Byte 14
  buffer[14] = BUFFER_NUMBER;

  // Bytes 15...: actual PNG
  memcpy(&buffer[LED_HEADER_SIZE], png, pngSize);


  if (!quiet) {
    Serial.printf(
      "LED packet built | PNG: %u | CRC32: %08lX | total: %u\n",
      (unsigned int)pngSize,
      (unsigned long)crc,
      (unsigned int)length
    );

    printHeader();
  }

  return true;
}


void LedImagePacket::printHeader() const {

  Serial.print("Header: ");

  for (size_t i = 0; i < LED_HEADER_SIZE; i++) {

    if (buffer[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(buffer[i], HEX);

    if (i < LED_HEADER_SIZE - 1) {
      Serial.print(" ");
    }
  }

  Serial.println();
}


uint32_t LedImagePacket::crc32(const uint8_t* data, size_t length) {

  uint32_t crc = 0xFFFFFFFF;

  for (size_t i = 0; i < length; i++) {

    crc ^= data[i];

    for (int bit = 0; bit < 8; bit++) {

      if (crc & 1) {
        crc = (crc >> 1) ^ 0xEDB88320;
      }
      else {
        crc >>= 1;
      }
    }
  }

  return crc ^ 0xFFFFFFFF;
}


void LedImagePacket::writeLe16(uint8_t* destination, uint16_t value) {
  destination[0] = value & 0xFF;
  destination[1] = (value >> 8) & 0xFF;
}


void LedImagePacket::writeLe32(uint8_t* destination, uint32_t value) {
  destination[0] = value & 0xFF;
  destination[1] = (value >> 8) & 0xFF;
  destination[2] = (value >> 16) & 0xFF;
  destination[3] = (value >> 24) & 0xFF;
}
