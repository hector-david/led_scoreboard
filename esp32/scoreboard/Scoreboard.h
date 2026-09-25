#pragma once

#include <Arduino.h>

// BLE headers must come before PNGenc: PNGenc's zutil.h does
// "#define local static", which breaks NimBLE's ble_sm.h
// (it has a struct field named "local").
#include "LedDisplay.h"

#include "Framebuffer.h"
#include "PngImage.h"
#include "LedImagePacket.h"

// ============================================================
// SCOREBOARD
//
// Owns the two team scores and the full display pipeline:
//
//   scores -> Framebuffer -> PngImage -> LedImagePacket -> LedDisplay
//
// Keep the instance global: it holds ~10 KB of buffers.
// ============================================================

class Scoreboard {

public:

  explicit Scoreboard(LedDisplay& display);

  uint8_t getTeam1Score() const { return team1Score; }

  uint8_t getTeam2Score() const { return team2Score; }

  // Maps a D18 button number to a scoreboard action.
  void handleButton(int buttonNumber);

  // Renders the current scores and pushes them to the panel.
  // Also cancels any temporary screen (see showBattery).
  void update();

  // Replaces the scores with the remote battery level for
  // BatteryScreen::SHOW_MS, after which tick() brings the
  // scores back. Any score change in between restores them
  // immediately.
  void showBattery(uint8_t percent);

  // Blinks the scores on and off while the remote is missing.
  // tick() drives the animation; turning it off puts the scores
  // straight back on the panel.
  void setBlinking(bool blinking);

  bool isBlinking() const { return blinkActive; }

  // Call from loop(): advances the blink, or restores the
  // scoreboard once a temporary screen has expired. Returns
  // immediately otherwise.
  void tick();

  // Scores -> framebuffer only (no encoding, no BLE).
  void render();

  void printFramebuffer() const;

  // Debug helper: fills the panel solid red.
  void testSolidRedFrame();


private:

  void drawScore(uint8_t score, int startX, RGB color);

  // Framebuffer -> PNG -> packet -> LED. Shared by every
  // screen; the caller has already drawn the framebuffer.
  // quiet suppresses the per-frame logging, for the flash.
  bool sendFrame(bool quiet = false);

  // Pushes an empty frame: the dark half of a flash.
  bool sendBlank(bool quiet = false);

  // Flips the scores on or off once their half of the flash
  // is up. Returns immediately otherwise.
  void tickBlink();


  LedDisplay& display;

  Framebuffer framebuffer;

  PngImage png;

  LedImagePacket packet;

  uint8_t team1Score = 0;

  uint8_t team2Score = 0;

  // Double-press state for the button_10 reset.
  bool resetArmed = false;

  unsigned long resetArmedTime = 0;

  // A temporary screen (battery level) is on the panel until
  // this time, after which tick() re-sends the scores.
  bool temporaryScreen = false;

  unsigned long temporaryScreenEnd = 0;

  // Blink state: while active the panel alternates between the
  // scores and an empty frame, every FLASH_MS.
  bool blinkActive = false;

  bool flashLit = false;

  unsigned long flashToggleTime = 0;
};
