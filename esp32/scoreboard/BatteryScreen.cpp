#include "BatteryScreen.h"

#include "Config.h"
#include "Font.h"


// ============================================================
// LAYOUT
// ============================================================

static const int DIGIT_GAP = 1;
static const int DIGIT_Y = 1;

static const uint8_t LEVEL_OK = 50;
static const uint8_t LEVEL_LOW = 20;


static RGB colorForLevel(uint8_t percent) {

  if (percent >= LEVEL_OK) {
    return Colors::GREEN;
  }

  if (percent >= LEVEL_LOW) {
    return Colors::YELLOW;
  }

  return Colors::RED;
}


// ============================================================
// RENDER
// ============================================================

void BatteryScreen::render(Framebuffer& framebuffer, uint8_t percent) {

  if (percent > 100) {
    percent = 100;
  }

  RGB color = colorForLevel(percent);

  // Split into digits, most significant first, without
  // leading zeros: "100", "85", "7".
  int digits[3];
  int count = 0;

  int value = percent;

  do {
    digits[count++] = value % 10;
    value /= 10;
  } while (value > 0);

  int width = count * Font::DIGIT_W + (count - 1) * DIGIT_GAP;

  int x = (Config::DISPLAY_WIDTH - width) / 2;

  framebuffer.clear();

  for (int i = count - 1; i >= 0; i--) {

    framebuffer.drawDigit(digits[i], x, DIGIT_Y, color);

    x += Font::DIGIT_W + DIGIT_GAP;
  }
}
