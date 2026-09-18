#pragma once

#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEClient.h>
#include <BLERemoteCharacteristic.h>

#include "Config.h"

// ============================================================
// LED DISPLAY
//
// BLE client for the LED_BLE_CD9B89CA panel. Owns the GATT
// connection, the write/notify characteristics, and the
// brightness state.
// ============================================================

class LedDisplay {

public:

  // Scan, connect, negotiate MTU, resolve characteristics,
  // and subscribe to ACK notifications.
  // Safe to call again after the link drops.
  bool connect();

  // Drops the link so the next connect() starts clean.
  void disconnect();

  bool isConnected() const;

  int getBrightness() const { return brightness; }

  // Pushes the current brightness value to the panel.
  void sendBrightness();

  void increaseBrightness();

  void decreaseBrightness();

  // Writes a fully built 0x0002 image packet in a single
  // GATT write. Refuses packets larger than the MTU payload.
  bool sendImagePacket(const uint8_t* packet, size_t length);


private:

  static void notifyCallback(
    BLERemoteCharacteristic* characteristic,
    uint8_t* data,
    size_t length,
    bool isNotify
  );


  // Created once and reused across reconnects.
  BLEClient* client = nullptr;

  // Rediscovered on every connect(); stale after a drop.
  BLERemoteCharacteristic* writeChar = nullptr;

  BLERemoteCharacteristic* notifyChar = nullptr;

  int brightness = Config::BRIGHTNESS_DEFAULT;
};
