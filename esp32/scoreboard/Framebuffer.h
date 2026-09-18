#pragma once

#include <Arduino.h>

#include "Config.h"

// ============================================================
// FRAMEBUFFER
//
// 32 x 16 RGB888 pixel buffer (1536 bytes) plus the primitive
// drawing operations the scoreboard needs.
// ============================================================

struct RGB {
  uint8_t r;
  uint8_t g;
  uint8_t b;
};

namespace Colors {
  static const RGB BLACK = { 0, 0, 0 };
  static const RGB RED = { 255, 0, 0 };
  static const RGB BLUE = { 0, 0, 255 };
}


class Framebuffer {

public:

  Framebuffer();

  void clear();

  void fill(RGB color);

  // Ignores out-of-range coordinates.
  void setPixel(int x, int y, RGB color);

  RGB getPixel(int x, int y) const;

  // Draws one 7x14 glyph with its top-left corner at (startX, startY).
  void drawDigit(int digit, int startX, int startY, RGB color);

  // Dumps the buffer to Serial as R / B / . characters.
  void print() const;


private:

  RGB pixels[Config::DISPLAY_HEIGHT][Config::DISPLAY_WIDTH];
};
