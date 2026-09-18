#pragma once

#include <Arduino.h>
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
// Encodes a Framebuffer into an in-RAM PNG using PNGenc.
// Keep instances global/static: PNGENC carries a large
// internal state that should not live on the stack.
// ============================================================

class PngImage {

public:

  // Framebuffer -> PNG. Returns false and logs on failure.
  bool encode(const Framebuffer& framebuffer);

  const uint8_t* data() const { return buffer; }

  size_t size() const { return length; }

  // Logs size, signature bytes, and projected packet size.
  void printInfo() const;


private:

  PNGENC encoder;

  uint8_t buffer[Config::PNG_BUFFER_SIZE];

  size_t length = 0;
};
