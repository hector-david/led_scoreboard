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
// D18 + LED SCOREBOARD
//
// Goal:
//   - Stay connected to D18 HID remote
//   - Stay connected to LED_BLE_CD9B89CA
//   - button_1 -> Team 1 +1
//   - button_5 -> Team 1 -1
//   - button_4 -> Team 2 +1
//   - button_2 -> Team 2 -1
//   - button_10 -> reset both scores to 00
//   - button_8 -> brightness up
//   - button_7 -> brightness down
//
// Automatic reconnection:
//   Both links are checked every loop. Whichever one is down
//   gets a fresh scan + connect attempt, and failed attempts
//   simply retry on the next pass, forever. The scores live
//   in RAM, so after the LED comes back they are re-sent.
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


void printReadyBanner() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("BOTH BLE DEVICES CONNECTED");
  Serial.println("button_1 = Team 1 +1");
  Serial.println("button_5 = Team 1 -1");
  Serial.println("button_4 = Team 2 +1");
  Serial.println("button_2 = Team 2 -1");
  Serial.println("button_10 = reset both to 00");
  Serial.println("button_8 = brightness up");
  Serial.println("button_7 = brightness down");
  Serial.println("============================================");
  Serial.println();

  printConnectionStatus();
}


// ============================================================
// CONNECTION MANAGEMENT
//
// Each attempt blocks for one scan (Config::BLE_SCAN_SECONDS)
// plus the connect itself. That is acceptable: a device that
// is down cannot send us anything, and D18 reports that
// arrive while the LED is being reconnected just wait in the
// HID queue until the next remote.update().
// ============================================================

// Short pause between failed rounds so the BLE stack gets a
// moment to settle and the loop keeps servicing remote.update().
static const unsigned long RETRY_DELAY_MS = 500;

static bool d18WasConnected = false;

static bool ledWasConnected = false;

static unsigned long nextAttemptTime = 0;


// Full D18 bring-up: scan, connect, secure, subscribe.
bool connectRemote() {

  if (!remote.connect()) {
    return false;
  }

  if (!remote.subscribeHidReports()) {
    // Connected but useless without reports; drop it so the
    // next pass sees it as down and starts over.
    remote.disconnect();
    return false;
  }

  return true;
}


// Full LED bring-up: scan, connect, then restore panel state.
bool connectDisplay() {

  if (!ledDisplay.connect()) {
    return false;
  }

  delay(300);

  // Establish a known starting point.
  // We cannot assume the panel's existing brightness matches
  // our local variable, so explicitly set it to 50%.
  ledDisplay.sendBrightness();

  // Put the current scores back on the panel. On first boot
  // this is the initial 00 - 00 frame.
  Serial.println("Sending scoreboard...");

  scoreboard.update();

  return true;
}


void maintainConnections() {

  bool d18Up = remote.isConnected();
  bool ledUp = ledDisplay.isConnected();


  // Announce drops once, not every pass.
  if (d18WasConnected && !d18Up) {
    Serial.println();
    Serial.println("D18 DISCONNECTED. Press a button on the remote to reconnect.");
  }

  if (ledWasConnected && !ledUp) {
    Serial.println();
    Serial.println("LED DISCONNECTED. Reconnecting...");
  }

  d18WasConnected = d18Up;
  ledWasConnected = ledUp;


  if (d18Up && ledUp) {
    return;
  }

  // Back off briefly after a failed round.
  if ((long)(millis() - nextAttemptTime) < 0) {
    return;
  }


  // D18 first: it only advertises for a short time after a
  // button press, so give it the first scan of every round.
  if (!d18Up) {
    d18Up = connectRemote();
    d18WasConnected = d18Up;
  }

  // The LED advertises continuously, so this succeeds as soon
  // as the panel is powered and not held by the phone app.
  if (!ledUp) {
    ledUp = connectDisplay();
    ledWasConnected = ledUp;
  }


  if (d18Up && ledUp) {
    printReadyBanner();
  }
  else {
    nextAttemptTime = millis() + RETRY_DELAY_MS;
  }
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(2000);

  Serial.println();
  Serial.println("=== D18 + LED SCOREBOARD ===");


  if (!remote.begin()) {
    // Without the HID queue nothing can work; stop here.
    while (true) {
      delay(1000);
    }
  }

  remote.setButtonHandler(onButton);


  BLEDevice::init("ESP32-Scoreboard");

  BLEDevice::setPower(ESP_PWR_LVL_P9);


  // D18 uses Just Works pairing.
  BLESecurity::setCapability(ESP_IO_CAP_NONE);

  BLESecurity::setAuthenticationMode(true, false, false);


  Serial.printf(
    "INITIAL SCORE | Team 1: %u | Team 2: %u\n",
    scoreboard.getTeam1Score(),
    scoreboard.getTeam2Score()
  );

  // Connections are made (and remade) from loop().
  Serial.println("Press a button on the D18 so the board can find it.");
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  // Drain queued D18 reports and fire button handlers.
  remote.update();


  // Reconnect whatever is down. Blocks for a scan when a
  // device is missing; returns immediately otherwise.
  maintainConnections();


  // Print both connection states every 5 seconds.
  static unsigned long lastStatusTime = 0;

  if (millis() - lastStatusTime >= 5000) {
    lastStatusTime = millis();
    printConnectionStatus();
  }


  delay(5);
}
