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
#include "RemoteBattery.h"
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
//   - button_10 x2 -> reset both scores to 00 (double press)
//   - button_8 -> brightness up
//   - button_7 -> brightness down
//   - button_3 -> show D18 battery level for a few seconds
//
// Automatic reconnection:
//   Both links are checked every loop. Whichever one is down
//   gets a fresh scan + connect attempt - the LED panel first,
//   the D18 only once the panel is up - and failed attempts
//   simply retry on the next pass, forever. The scores live
//   in RAM, so after the LED comes back they are re-sent.
//
//   While the remote is missing the panel blinks the scores on
//   and off; the display returns to normal as soon as the
//   remote is connected.
//
// Module layout:
//   Config.h          shared names, geometry, buffer sizes
//   Font              7x14 digit glyphs
//   Framebuffer       32x16 RGB pixel buffer + drawing
//   PngImage          framebuffer -> PNG (PNGenc)
//   LedImagePacket    PNG -> panel 0x0002 packet
//   LedDisplay        LED panel BLE client
//   D18Remote         D18 remote BLE HID client + gestures
//   RemoteBattery     D18 battery level over BLE Battery Service
//   BatteryScreen     battery level -> framebuffer
//   Scoreboard        scores + display pipeline
// ============================================================


// ============================================================
// MODULES
// ============================================================

static LedDisplay ledDisplay;

static D18Remote remote;

static RemoteBattery remoteBattery(remote);

static Scoreboard scoreboard(ledDisplay);


// ============================================================
// BUTTON HANDLER
//
// Called by D18Remote::update() from loop().
// ============================================================

static const int BATTERY_BUTTON = 3;


void showRemoteBattery() {

  Serial.println("Reading D18 battery...");

  uint8_t percent;

  if (!remoteBattery.read(percent)) {
    // Already logged why; leave the scores on the panel.
    return;
  }

  scoreboard.showBattery(percent);
}


void onButton(int buttonNumber) {

  if (buttonNumber == BATTERY_BUTTON) {
    showRemoteBattery();
    return;
  }

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
  Serial.println("button_10 x2 = reset both to 00 (double press)");
  Serial.println("button_8 = brightness up");
  Serial.println("button_7 = brightness down");
  Serial.println("button_3 = show D18 battery level");
  Serial.println("============================================");
  Serial.println();

  printConnectionStatus();
}


// ============================================================
// CONNECTION MANAGEMENT
//
// The LED panel is always brought up first. It is what makes
// the board useful, and it has to be there before the missing
// remote can be signalled by blinking the scores, so a round
// that cannot reach the panel does not go looking for the D18
// at all.
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

  // A scan blocks the loop, so while the panel is blinking for
  // the missing remote we scan in short slices: each one gives
  // scoreboard.tick() a chance to advance the blink.
  uint32_t scanSeconds = scoreboard.isBlinking()
    ? Config::BLE_SCAN_SECONDS_SHORT
    : Config::BLE_SCAN_SECONDS;

  if (!remote.connect(scanSeconds)) {
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
  // this is the initial 00 - 00 frame. If the remote is still
  // missing, maintainConnections() turns this into a blink on
  // the way out.
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


  // Blink the panel whenever the remote is missing. Needs the
  // panel itself, so this stops on its own if the LED drops.
  scoreboard.setBlinking(ledUp && !d18Up);


  if (d18Up && ledUp) {
    return;
  }

  // Back off briefly after a failed round.
  if ((long)(millis() - nextAttemptTime) < 0) {
    return;
  }


  // The panel comes first. It advertises continuously, so this
  // succeeds as soon as it is powered and not held by the phone
  // app, and until it is up there is nowhere to show anything -
  // not even the blink that asks for a button press.
  if (!ledUp) {
    ledUp = connectDisplay();
    ledWasConnected = ledUp;
  }

  // Still no panel: spend the next round on it again instead of
  // pairing a remote we could not display anything for.
  if (!ledUp) {
    nextAttemptTime = millis() + RETRY_DELAY_MS;
    return;
  }


  // Blink from here on, so the panel is already asking for a
  // button press while the D18 scan below is running.
  scoreboard.setBlinking(!d18Up);

  if (!d18Up) {
    d18Up = connectRemote();
    d18WasConnected = d18Up;
  }

  // Stop the blink the moment the remote answers. Re-check the
  // panel: it may have dropped during the scan above.
  scoreboard.setBlinking(ledDisplay.isConnected() && !d18Up);


  // The banner claims both links, so make sure the panel really
  // survived the scan.
  if (d18Up && ledDisplay.isConnected()) {
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

  // Do not let the library start pairing by itself on every
  // connect. The LED panel needs no pairing, and because the
  // "security started" flag is global, an LED connect would
  // claim it and leave D18Remote::connect() waiting forever on a
  // pairing request that was never sent. Pairing is started
  // explicitly, on the D18 link only.
  BLESecurity::setForceAuthentication(false);


  Serial.printf(
    "INITIAL SCORE | Team 1: %u | Team 2: %u\n",
    scoreboard.getTeam1Score(),
    scoreboard.getTeam2Score()
  );

  // Connections are made (and remade) from loop(): the LED
  // panel first, then the D18.
  Serial.println("Connecting to the LED panel first.");
  Serial.println("Once the scores start blinking, press a button on the D18 so the board can find it.");
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  // Drain queued D18 reports and fire button handlers.
  remote.update();


  // Advance the "remote missing" blink, or put the scores back
  // once a battery screen has timed out.
  scoreboard.tick();


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
