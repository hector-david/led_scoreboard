#pragma once

#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEClient.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLERemoteCharacteristic.h>

#include <map>

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

  // Creates the HID event queue. Call once before connect().
  bool begin();

  // Scan, connect, and secure the link.
  // Connect the D18 before anything else: it only advertises
  // for a short time after a button press.
  // Safe to call again after the link drops.
  bool connect();

  // Discover HID INPUT reports and subscribe to them.
  // Must be repeated after every (re)connect.
  bool subscribeHidReports();

  // Drops the link so the next connect() starts clean.
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
