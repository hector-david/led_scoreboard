#pragma once

#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEClient.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLERemoteCharacteristic.h>

#include <map>

#include "Config.h"

// ============================================================
// D18 REMOTE
//
// BLE HID client for the D18 remote. Handles scanning,
// connecting, subscribing to HID input reports, and turning
// raw reports into logical button numbers:
//
//   button_1  swipe down          button_6   consumer 04 00
//   button_2  swipe right         button_7   consumer 00 80
//   button_3  single center tap   button_8   consumer 00 40
//   button_4  swipe left          button_9   double center tap
//   button_5  swipe up            button_10  consumer 40 00
//
// BLE notifications arrive on the BLE host task. They are
// queued and drained from update() so that button handlers
// run on the main loop, never inside a BLE callback.
// ============================================================

class D18Remote {

public:

  typedef void (*ButtonHandler)(int buttonNumber);


  D18Remote();

  // Creates the HID event queue. Call once before scanning.
  bool begin();

  // Starts looking for the remote, and returns immediately:
  // the scan runs in the background so the loop can keep
  // flashing the panel while it waits. A no-op while a scan
  // is already running, so it is safe to call every pass.
  // The scan is short and restarted rather than endless, so a
  // remote that appears late is still picked up.
  void startScan();

  // True once a scan has seen the remote. The scan stops
  // itself at that point; call connectToFoundRemote() next.
  bool foundRemote() const { return target != nullptr; }

  // Second half of the bring-up: connect to what the scan
  // found and secure the link. Blocks, but only once the
  // remote is actually there. Subscribe to HID reports after
  // this. False leaves nothing connected.
  bool connectToFoundRemote();

  // Stops any running scan and forgets what it found. Call
  // before anything else needs the radio to itself - an LED
  // reconnect scans on the same shared scan object.
  void cancelScan();

  // Discover HID INPUT reports and subscribe to them.
  // Must be repeated after every (re)connect.
  bool subscribeHidReports();

  // Drops the link so the next bring-up starts clean.
  void disconnect();

  bool isConnected() const;

  // The underlying link, so other modules (RemoteBattery) can
  // read non-HID services on the same connection. May be
  // nullptr before the first connect().
  BLEClient* getClient() const { return client; }

  void setButtonHandler(ButtonHandler handler);

  // Drains queued reports and resolves pending taps.
  // Call from loop().
  void update();


private:

  struct HidEvent {
    uint16_t handle;
    uint8_t reportId;
    uint8_t length;
    uint8_t data[8];
  };

  struct TouchState {
    bool active = false;

    int startX = 0;
    int startY = 0;

    int lastX = 0;
    int lastY = 0;
  };

  // Stops the radio side of a scan, leaving any found target
  // in place for connectToFoundRemote().
  void stopScanning();

  // Passed to the background scan; the library calls it when
  // the scan ends, whether it timed out or was stopped.
  static void scanComplete(BLEScanResults results);


  class ScanCallbacks : public BLEAdvertisedDeviceCallbacks {

  public:

    explicit ScanCallbacks(D18Remote& owner) : owner(owner) {}

    void onResult(BLEAdvertisedDevice device) override;

  private:

    D18Remote& owner;
  };


  // BLE gives us a plain function pointer, so the callback
  // reaches the object through this pointer.
  static D18Remote* instance;

  static void notificationCallback(
    BLERemoteCharacteristic* characteristic,
    uint8_t* data,
    size_t length,
    bool isNotify
  );

  static void decodeTouch(
    const uint8_t* data,
    int& x,
    int& y,
    bool& touching
  );


  void processHidEvent(const HidEvent& event);

  void processConsumerReport(const uint8_t* data, size_t length);

  void processTouchReport(const uint8_t* data, size_t length);

  void finishGesture();

  void emitButton(int buttonNumber);


  // The scan object is shared with LedDisplay, so this
  // callback stays installed and ignores results unless
  // connect() is actively looking for the D18.
  ScanCallbacks scanCallbacks;

  bool scanningForD18 = false;

  // A background scan is running. Static so the library's
  // scan-complete callback, a plain function pointer, can
  // clear it; there is only ever one remote.
  static volatile bool scanRunning;

  // Backstop for scanRunning in case the completion callback
  // never arrives: after this the scan is assumed to be over.
  unsigned long scanEndTime = 0;

  BLEAdvertisedDevice* target = nullptr;

  // Created once and reused across reconnects.
  BLEClient* client = nullptr;

  // Maps characteristic handle -> HID Report ID
  std::map<uint16_t, uint8_t> reportIdByHandle;

  QueueHandle_t hidQueue = nullptr;

  TouchState touch;

  // button_3 = single center tap
  // button_9 = double center tap
  bool pendingCenterTap = false;

  unsigned long pendingTapTime = 0;

  ButtonHandler buttonHandler = nullptr;
};
