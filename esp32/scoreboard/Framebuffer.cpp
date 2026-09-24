#include "Framebuffer.h"

#include "Font.h"

using Config::DISPLAY_WIDTH;
using Config::DISPLAY_HEIGHT;


Framebuffer::Framebuffer() {
  clear();
}


void Framebuffer::clear() {
  fill(Colors::BLACK);
}


void Framebuffer::fill(RGB color) {

  for (int y = 0; y < DISPLAY_HEIGHT; y++) {
    for (int x = 0; x < DISPLAY_WIDTH; x++) {
      pixels[y][x] = color;
    }
  }
}


void Framebuffer::setPixel(int x, int y, RGB color) {

  if (
    x < 0 || x >= DISPLAY_WIDTH ||
    y < 0 || y >= DISPLAY_HEIGHT
  ) {
    return;
  }

  pixels[y][x] = color;
}


RGB Framebuffer::getPixel(int x, int y) const {

  if (
    x < 0 || x >= DISPLAY_WIDTH ||
    y < 0 || y >= DISPLAY_HEIGHT
  ) {
    return Colors::BLACK;
  }

  return pixels[y][x];
}


void Framebuffer::drawDigit(int digit, int startX, int startY, RGB color) {

  if (digit < 0 || digit > 9) {
    return;
  }

  drawGlyph(Font::DIGITS[digit], startX, startY, color);
}


void Framebuffer::drawGlyph(const char* const* rows, int startX, int startY, RGB color) {

  for (int row = 0; row < Font::DIGIT_H; row++) {

    for (int col = 0; col < Font::DIGIT_W; col++) {

      if (rows[row][col] != '1') {
        continue;
      }

      setPixel(startX + col, startY + row, color);
    }
  }
}


void Framebuffer::print() const {

  Serial.println("--------------------------------");

  for (int y = 0; y < DISPLAY_HEIGHT; y++) {

    for (int x = 0; x < DISPLAY_WIDTH; x++) {

      const RGB& pixel = pixels[y][x];

      // Team 1 = Red
      if (pixel.r > 0 && pixel.g == 0 && pixel.b == 0) {
        Serial.print("R");
      }

      // Team 2 = Blue
      else if (pixel.r == 0 && pixel.g == 0 && pixel.b > 0) {
        Serial.print("B");
      }

      // Green (battery OK)
      else if (pixel.r == 0 && pixel.g > 0 && pixel.b == 0) {
        Serial.print("G");
      }

      // Yellow (battery low)
      else if (pixel.r > 0 && pixel.g > 0 && pixel.b == 0) {
        Serial.print("Y");
      }

      // Black
      else {
        Serial.print(".");
      }
    }

    Serial.println();
  }

  Serial.println("--------------------------------");
  Serial.println();
}
