#pragma once

#include <Arduino.h>

#include "D18Remote.h"

// ============================================================
// REMOTE BATTERY
//
// Reads the D18's charge level over the standard BLE Battery
// Service on the link that D18Remote already holds:
//
//   Service        0x180F  (Battery Service)
//   Characteristic 0x2A19  (Battery Level, 0..100 %)
//
// The characteristic is looked up fresh on every read. Handles
// are only valid for one connection, so caching the pointer
// would leave a dangling reference after a D18 reconnect; the
// BLE client caches the discovered service itself, so a repeat
// lookup on the same link is cheap.
//
// read() blocks for one GATT round trip. Call it from the main
// loop (a button handler is fine), never from a BLE callback.
// ============================================================

class RemoteBattery {

public:

  explicit RemoteBattery(D18Remote& remote);

  // Fetches the battery level (0..100) into percent.
  // Returns false if the D18 is down or does not expose the
  // Battery Service; percent is untouched in that case.
  bool read(uint8_t& percent);

  // Last value read() returned successfully, or -1 if none yet.
  int getLastPercent() const { return lastPercent; }


private:

  D18Remote& remote;

  int lastPercent = -1;
};
