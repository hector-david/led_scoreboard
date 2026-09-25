#include "Scoreboard.h"

#include "Font.h"
#include "BatteryScreen.h"


// ============================================================
// LAYOUT
//
// Same layout as the working Python scoreboard.
// ============================================================

static const int DIGIT_GAP = 1;
static const int DIGIT_Y = 1;

static const int TEAM1_X = 0;
static const int TEAM2_X = 17;

static const RGB TEAM1_COLOR = Colors::RED;
static const RGB TEAM2_COLOR = Colors::BLUE;

static const uint8_t MAX_SCORE = 99;

// button_10 must be pressed twice within this window to reset
// the scores, so a single accidental press does nothing.
static const unsigned long RESET_DOUBLE_PRESS_MS = 800;

// Minimum time each half of a blink stays on the panel. The
// real rate is slower than this: tick() can only run between
// the blocking BLE scans that look for the remote.
static const unsigned long BLINK_MS = 400;


Scoreboard::Scoreboard(LedDisplay& display)
  : display(display) {
}


// ============================================================
// BUTTON HANDLING
// ============================================================

void Scoreboard::handleButton(int buttonNumber) {

  switch (buttonNumber) {

    case 1:

      if (team1Score < MAX_SCORE) {
        team1Score++;
      }

      break;


    case 5:

      if (team1Score > 0) {
        team1Score--;
      }

      break;


    case 4:

      if (team2Score < MAX_SCORE) {
        team2Score++;
      }

      break;


    case 2:

      if (team2Score > 0) {
        team2Score--;
      }

      break;


    case 10: {

      unsigned long now = millis();

      // First press only arms the reset. A second press inside
      // the window completes it; a late press re-arms instead.
      if (!resetArmed || (now - resetArmedTime > RESET_DOUBLE_PRESS_MS)) {
        resetArmed = true;
        resetArmedTime = now;

        Serial.println("RESET ARMED | press button_10 again to reset");

        return;
      }

      resetArmed = false;

      team1Score = 0;
      team2Score = 0;

      break;
    }


    // Brightness only touches the panel setting; the scores
    // and the displayed frame do not change, so return early
    // instead of re-rendering.

    case 8:

      display.increaseBrightness();

      return;


    case 7:

      display.decreaseBrightness();

      return;


    default:

      // Other buttons do nothing yet.

      return;
  }

  Serial.printf(
    "SCORE | Team 1: %u | Team 2: %u\n",
    team1Score,
    team2Score
  );

  update();
}


// ============================================================
// DISPLAY PIPELINE
// ============================================================

void Scoreboard::update() {

  // Whatever was borrowing the panel is done now.
  temporaryScreen = false;

  // Score variables -> 32x16 framebuffer
  render();

  // Optional debugging
  printFramebuffer();

  if (!sendFrame()) {
    return;
  }

  Serial.printf(
    "SCOREBOARD DISPLAYED | T1: %02u | T2: %02u\n",
    team1Score,
    team2Score
  );
}


bool Scoreboard::sendBlank() {

  framebuffer.clear();

  return sendFrame();
}


bool Scoreboard::sendFrame() {

  // Framebuffer -> PNG
  if (!png.encode(framebuffer)) {
    Serial.println("Frame send failed: PNG");
    return false;
  }

  // PNG -> LED 0x0002 packet
  if (!packet.build(png.data(), png.size())) {
    Serial.println("Frame send failed: packet");
    return false;
  }

  // Packet -> physical LED
  if (!display.sendImagePacket(packet.data(), packet.size())) {
    Serial.println("Frame send failed: BLE send");
    return false;
  }

  return true;
}


// ============================================================
// BLINKING (remote not connected)
// ============================================================

void Scoreboard::setBlinking(bool blinking) {

  if (blinking == blinkActive) {
    return;
  }

  blinkActive = blinking;


  if (blinking) {

    Serial.println("Remote missing: blinking the scoreboard.");

    // Whatever was borrowing the panel loses it to the blink.
    temporaryScreen = false;

    // Start dark, so the very first tick lights the scores up
    // again and the blink is obvious right away.
    blinkVisible = false;

    blinkToggleTime = millis() + BLINK_MS;

    sendBlank();

    return;
  }


  Serial.println("Remote connected: scoreboard back to normal.");

  // Nothing to restore while the panel is down; connectDisplay()
  // re-sends the scores when it comes back.
  if (!display.isConnected()) {
    return;
  }

  update();
}


void Scoreboard::tickBlink() {

  if ((long)(millis() - blinkToggleTime) < 0) {
    return;
  }

  blinkToggleTime = millis() + BLINK_MS;

  blinkVisible = !blinkVisible;

  // No framebuffer dump here: this runs a few times a second.
  if (!blinkVisible) {
    sendBlank();
    return;
  }

  render();

  sendFrame();
}


// ============================================================
// TEMPORARY SCREENS
// ============================================================

void Scoreboard::showBattery(uint8_t percent) {

  BatteryScreen::render(framebuffer, percent);

  Serial.println();
  Serial.printf("FRAMEBUFFER | BATTERY %u%%\n", percent);
  framebuffer.print();

  if (!sendFrame()) {
    // Nothing reached the panel, so there is nothing to undo.
    return;
  }

  Serial.printf(
    "BATTERY DISPLAYED | %u%% | scores back in %lu ms\n",
    percent,
    BatteryScreen::SHOW_MS
  );

  temporaryScreen = true;
  temporaryScreenEnd = millis() + BatteryScreen::SHOW_MS;
}


void Scoreboard::tick() {

  // The blink owns the panel while it is running.
  if (blinkActive) {
    tickBlink();
    return;
  }

  if (!temporaryScreen) {
    return;
  }

  if ((long)(millis() - temporaryScreenEnd) < 0) {
    return;
  }

  Serial.println("Restoring scoreboard...");

  // Clears temporaryScreen as a side effect.
  update();
}


void Scoreboard::render() {

  framebuffer.clear();

  drawScore(team1Score, TEAM1_X, TEAM1_COLOR);
  drawScore(team2Score, TEAM2_X, TEAM2_COLOR);
}


void Scoreboard::drawScore(uint8_t score, int startX, RGB color) {

  if (score > MAX_SCORE) {
    score = MAX_SCORE;
  }

  int tens = score / 10;
  int ones = score % 10;

  framebuffer.drawDigit(tens, startX, DIGIT_Y, color);

  framebuffer.drawDigit(
    ones,
    startX + Font::DIGIT_W + DIGIT_GAP,
    DIGIT_Y,
    color
  );
}


void Scoreboard::printFramebuffer() const {

  Serial.println();

  Serial.printf(
    "FRAMEBUFFER | T1 %02u | T2 %02u\n",
    team1Score,
    team2Score
  );

  framebuffer.print();
}


// ============================================================
// TEST
// ============================================================

void Scoreboard::testSolidRedFrame() {

  Serial.println("TEST: building solid RED framebuffer");

  framebuffer.fill(Colors::RED);

  if (!png.encode(framebuffer)) {
    Serial.println("TEST FAILED: PNG encoding");
    return;
  }

  png.printInfo();

  if (!packet.build(png.data(), png.size())) {
    Serial.println("TEST FAILED: packet build");
    return;
  }

  display.sendImagePacket(packet.data(), packet.size());
}
