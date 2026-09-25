#pragma once

#include <Arduino.h>

#include "Config.h"

// ============================================================
// LED IMAGE PACKET
//
// Wraps a PNG in the panel's proprietary 0x0002 "show image"
// packet:
//
//   Bytes 0-1   Total packet length (LE16)
//   Bytes 2-3   Command 0x0002 (LE16)
//   Byte  4     0x00
//   Bytes 5-8   PNG byte length (LE32)
//   Bytes 9-12  PNG CRC32 (LE32)
//   Byte  13    0x00
//   Byte  14    Buffer number
//   Bytes 15... PNG bytes
// ============================================================

class LedImagePacket {

public:

  // PNG -> packet. Returns false and logs on failure.
  // quiet drops the per-packet dump, for the flash that
  // signals a missing remote: it builds frames several times
  // a second and would bury everything else in the log.
  bool build(const uint8_t* png, size_t pngSize, bool quiet = false);

  const uint8_t* data() const { return buffer; }

  size_t size() const { return length; }


private:

  static uint32_t crc32(const uint8_t* data, size_t length);

  static void writeLe16(uint8_t* destination, uint16_t value);

  static void writeLe32(uint8_t* destination, uint32_t value);

  void printHeader() const;


  uint8_t buffer[Config::LED_HEADER_SIZE + Config::PNG_BUFFER_SIZE];

  size_t length = 0;
};
