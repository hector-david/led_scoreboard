#pragma once

#include <Arduino.h>

#include "Framebuffer.h"

// ============================================================
// BATTERY SCREEN
//
// Draws a battery percentage (0..100) centered on the panel,
// colored by charge:
//
//   green   >= 50 %
//   yellow  20..49 %
//   red     < 20 %
//
// Render-only: it writes into a Framebuffer supplied by the
// caller and owns no buffers of its own, so the Scoreboard's
// existing PNG / packet pipeline pushes it to the LED.
// ============================================================

namespace BatteryScreen {

  // How long the level stays on the panel before the caller
  // should restore the scoreboard.
  static const unsigned long SHOW_MS = 3000;

  void render(Framebuffer& framebuffer, uint8_t percent);
}
