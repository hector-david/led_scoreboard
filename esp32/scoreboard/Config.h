#pragma once

#include <Arduino.h>

// ============================================================
// SHARED CONFIGURATION
//
// Values that more than one module needs to agree on.
// Module-specific details (UUIDs, packet layouts, gesture
// thresholds) live next to the code that uses them.
// ============================================================

namespace Config {

  // ---- LED screen -------------------------------------------

  static const char* LED_NAME = "LED_BLE_CD9B89CA";

  static const int BRIGHTNESS_DEFAULT = 50;
  static const int BRIGHTNESS_STEP = 10;
  static const int BRIGHTNESS_MIN = 10;
  static const int BRIGHTNESS_MAX = 100;


  // ---- D18 remote -------------------------------------------

  static const char* D18_NAME = "D18";


  // ---- Display geometry -------------------------------------

  static const int DISPLAY_WIDTH = 32;
  static const int DISPLAY_HEIGHT = 16;


  // ---- Buffers ----------------------------------------------

  // More than enough for a 32x16 RGB PNG.
  static const size_t PNG_BUFFER_SIZE = 4096;

  // Bytes in front of the PNG in a 0x0002 image packet.
  static const size_t LED_HEADER_SIZE = 15;
}
