#include "Scoreboard.h"

#include "Font.h"


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

  // Score variables -> 32x16 framebuffer
  render();

  // Optional debugging
  printFramebuffer();

  // Framebuffer -> PNG
  if (!png.encode(framebuffer)) {
    Serial.println("Scoreboard update failed: PNG");
    return;
  }

  // PNG -> LED 0x0002 packet
  if (!packet.build(png.data(), png.size())) {
    Serial.println("Scoreboard update failed: packet");
    return;
  }

  // Packet -> physical LED
  if (!display.sendImagePacket(packet.data(), packet.size())) {
    Serial.println("Scoreboard update failed: BLE send");
    return;
  }

  Serial.printf(
    "SCOREBOARD DISPLAYED | T1: %02u | T2: %02u\n",
    team1Score,
    team2Score
  );
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
