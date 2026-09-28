#pragma once

#include <Arduino.h>

// Only PNGenc's bundled zlib (deflate) is used; the PNG around
// the compressed pixels is written in PngImage.cpp. Including
// PNGenc.h is what makes the Arduino IDE build and link that
// zlib, and it also brings in deflate.h, which sizes the zlib
// memory pool.
#include <PNGenc.h>

// PNGenc's zutil.h leaks "#define local static" into every
// file that includes it. Undo that so headers included after
// this one (NimBLE's ble_sm.h uses "local" as a field name)
// are not broken.
#ifdef local
#undef local
#endif

#include "Config.h"
#include "Framebuffer.h"

// ============================================================
// PNG IMAGE
//
// Encodes a Framebuffer into an in-RAM PNG: 32x16 RGB888,
// adaptive row filters, one zlib stream in one IDAT chunk.
// Keep instances global/static: the output buffer is 4 KB.
// ============================================================

class PngImage {

public:

  // zlib compression level, as in the Python version.
  static const uint8_t DEFAULT_LEVEL = 6;

  // Framebuffer -> PNG. Returns false and logs on failure.
  // Every level 1-9 gives the same pixels. The zlib header
  // records which band the level is in (1, 2-5, 6, 7-9), so
  // levels from different bands never produce the same bytes.
  bool encode(const Framebuffer& framebuffer, uint8_t level = DEFAULT_LEVEL);

  const uint8_t* data() const { return buffer; }

  size_t size() const { return length; }

  // Logs size, signature bytes, and projected packet size.
  void printInfo() const;


private:

  // Filters and compresses every row into out, at most
  // capacity bytes. Returns false and logs on failure.
  bool deflateRows(
    const Framebuffer& framebuffer,
    uint8_t level,
    uint8_t* out,
    size_t capacity,
    size_t& outLength
  );

  // Writes a chunk's length, type and CRC around the
  // dataLength bytes already sitting at start + 8. Returns
  // the offset just past the chunk.
  size_t finishChunk(size_t start, const char* type, size_t dataLength);


  uint8_t buffer[Config::PNG_BUFFER_SIZE];

  size_t length = 0;
};
