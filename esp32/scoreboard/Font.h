#pragma once

// ============================================================
// DISPLAY FONT
//
// 7x14 digit glyphs. '1' = lit pixel, '.' = off.
// Same layout as the working Python scoreboard.
// ============================================================

namespace Font {

  static const int DIGIT_W = 7;
  static const int DIGIT_H = 14;

  extern const char* const DIGITS[10][DIGIT_H];

  // Same size as a digit, used by the battery screen.
  extern const char* const PERCENT[DIGIT_H];
}
