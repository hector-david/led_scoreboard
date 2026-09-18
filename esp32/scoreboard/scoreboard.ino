/*
  ESP32-S3 N16R8 BOARD SETTINGS

  Board:            ESP32S3 Dev Module
  Upload Speed:     921600
  USB CDC On Boot:  Disabled
  CPU Frequency:    240MHz (WiFi)
  Flash Mode:       QIO 80MHz
  Flash Size:       16MB (128Mb)
  PSRAM:            OPI PSRAM

  Port:
  COM7 currently, but COM number may change.
*/

#include <Arduino.h>

#include <BLEDevice.h>
#include <BLESecurity.h>

#include "Config.h"
#include "LedDisplay.h"
#include "D18Remote.h"
#include "Scoreboard.h"

// ============================================================
// D18 + LED DUAL-CONNECTION TEST
//
// Goal:
//   - Stay connected to D18 HID remote
//   - Stay connected to LED_BLE_CD9B89CA
//   - button_1 -> Team 1 +1
//
// This intentionally does NOT add automatic reconnection yet.
// First we want to prove both BLE links can coexist reliably.
//
// Module layout:
//   Config.h          shared names, geometry, buffer sizes
//   Font              7x14 digit glyphs
//   Framebuffer       32x16 RGB pixel buffer + drawing
//   PngImage          framebuffer -> PNG (PNGenc)
//   LedImagePacket    PNG -> panel 0x0002 packet
//   LedDisplay        LED panel BLE client
//   D18Remote         D18 remote BLE HID client + gestures
//   Scoreboard        scores + display pipeline
// ============================================================


// ============================================================
// MODULES
// ============================================================

static LedDisplay ledDisplay;

static D18Remote remote;

static Scoreboard scoreboard(ledDisplay);


// ============================================================
// BUTTON HANDLER
//
// Called by D18Remote::update() from loop().
// ============================================================

void onButton(int buttonNumber) {
  scoreboard.handleButton(buttonNumber);
}


// ============================================================
// CONNECTION STATUS
// ============================================================

void printConnectionStatus() {

  Serial.printf(
    "STATUS | D18: %s | LED: %s | T1: %u | T2: %u\n",
    remote.isConnected() ? "CONNECTED" : "DISCONNECTED",
    ledDisplay.isConnected() ? "CONNECTED" : "DISCONNECTED",
    scoreboard.getTeam1Score(),
    scoreboard.getTeam2Score()
  );
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(2000);

  Serial.println();
  Serial.println("=== D18 + LED DUAL BLE TEST ===");


  if (!remote.begin()) {
    return;
  }

  remote.setButtonHandler(onButton);


  BLEDevice::init("ESP32-Scoreboard");

  BLEDevice::setPower(ESP_PWR_LVL_P9);


  // D18 uses Just Works pairing.
  BLESecurity::setCapability(ESP_IO_CAP_NONE);

  BLESecurity::setAuthenticationMode(true, false, false);


  // 1) D18 first.
  if (!remote.connect()) {
    return;
  }

  // 2) Subscribe to its HID reports.
  if (!remote.subscribeHidReports()) {
    return;
  }

  // 3) While D18 stays connected, connect the LED.
  if (!ledDisplay.connect()) {
    return;
  }


  delay(300);


  // Establish a known starting point.
  // We cannot assume the panel's existing brightness matches
  // our local variable, so explicitly set it to 50%.
  ledDisplay.sendBrightness();


  Serial.println();
  Serial.println("============================================");
  Serial.println("BOTH BLE DEVICES CONNECTED");
  Serial.println("button_1 = Team 1 +1");
  Serial.println("button_5 = not assigned yet");
  Serial.println("============================================");
  Serial.println();

  Serial.printf(
    "INITIAL SCORE | Team 1: %u | Team 2: %u\n",
    scoreboard.getTeam1Score(),
    scoreboard.getTeam2Score()
  );

  printConnectionStatus();

  Serial.println("Sending initial scoreboard...");

  scoreboard.update();

  // delay(1000);
  // scoreboard.testSolidRedFrame();
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  // Drain queued D18 reports and fire button handlers.
  remote.update();


  // Print both connection states every 5 seconds.
  static unsigned long lastStatusTime = 0;

  if (millis() - lastStatusTime >= 5000) {
    lastStatusTime = millis();
    printConnectionStatus();
  }


  delay(5);
}
