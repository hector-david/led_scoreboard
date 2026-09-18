#include "D18Remote.h"

#include <BLERemoteService.h>
#include <BLERemoteDescriptor.h>

#include "Config.h"


// ============================================================
// GATT IDENTIFIERS
// ============================================================

static BLEUUID HID_SERVICE_UUID((uint16_t)0x1812);
static BLEUUID REPORT_UUID((uint16_t)0x2A4D);
static BLEUUID REPORT_REF_UUID((uint16_t)0x2908);


// ============================================================
// GESTURE THRESHOLDS
// ============================================================

// Minimum travel along the dominant axis for a swipe.
static const int SWIPE_DISTANCE = 250;

// Maximum travel on either axis for a tap.
static const int TAP_MAX_MOVEMENT = 120;

// Touchpad region that counts as the center.
static const int CENTER_X_MIN = 400;
static const int CENTER_X_MAX = 600;
static const int CENTER_Y_MIN = 300;
static const int CENTER_Y_MAX = 500;

static const unsigned long DOUBLE_TAP_MS = 450;

static const int HID_QUEUE_LENGTH = 32;


D18Remote* D18Remote::instance = nullptr;


D18Remote::D18Remote()
  : scanCallbacks(*this) {
  instance = this;
}


// ============================================================
// SETUP
// ============================================================

bool D18Remote::begin() {

  hidQueue = xQueueCreate(HID_QUEUE_LENGTH, sizeof(HidEvent));

  if (!hidQueue) {
    Serial.println("ERROR: could not create HID queue.");
    return false;
  }

  return true;
}


void D18Remote::setButtonHandler(ButtonHandler handler) {
  buttonHandler = handler;
}


bool D18Remote::isConnected() const {
  return client && client->isConnected();
}


void D18Remote::disconnect() {

  if (client && client->isConnected()) {
    client->disconnect();
  }
}


// ============================================================
// SCAN CALLBACK
// ============================================================

void D18Remote::ScanCallbacks::onResult(BLEAdvertisedDevice device) {

  // Ignore results from LED scans, and any late result that
  // arrives after we already picked a target.
  if (!owner.scanningForD18 || owner.target) {
    return;
  }

  if (!device.haveName()) {
    return;
  }

  if (device.getName() != Config::D18_NAME) {
    return;
  }

  Serial.println();
  Serial.println("D18 found.");

  Serial.printf(
    "Address: %s | RSSI: %d\n",
    device.getAddress().toString().c_str(),
    device.getRSSI()
  );

  owner.target = new BLEAdvertisedDevice(device);

  BLEDevice::getScan()->stop();
}


// ============================================================
// CONNECT
// ============================================================

bool D18Remote::connect() {

  BLEScan* scan = BLEDevice::getScan();

  // Same object every time; re-installing it is harmless.
  scan->setAdvertisedDeviceCallbacks(&scanCallbacks);

  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);

  target = nullptr;

  Serial.println("Scanning for D18... (press a button on the remote)");

  scanningForD18 = true;

  scan->start(Config::BLE_SCAN_SECONDS, false);

  scanningForD18 = false;

  if (!target) {
    Serial.println("D18 not found.");
    return false;
  }

  scan->clearResults();

  delay(50);

  if (!client) {
    client = BLEDevice::createClient();
  }

  Serial.println("Connecting to D18...");

  bool connected = client->connect(target);

  delete target;
  target = nullptr;

  if (!connected) {
    Serial.println("ERROR: D18 connection failed.");
    return false;
  }

  Serial.println("D18 connected.");


  Serial.println("Securing D18 connection...");

  if (!client->secureConnection()) {
    Serial.println("ERROR: D18 security failed.");
    disconnect();
    return false;
  }

  Serial.println("D18 connection secured.");

  return true;
}


// ============================================================
// SUBSCRIBE TO HID REPORTS
// ============================================================

bool D18Remote::subscribeHidReports() {

  if (!isConnected()) {
    Serial.println("ERROR: D18 not connected.");
    return false;
  }

  // Handles are rediscovered on every connection, so drop
  // the map from the previous link. No notifications can
  // arrive while we rebuild it: nothing is subscribed yet.
  reportIdByHandle.clear();

  BLERemoteService* hid = client->getService(HID_SERVICE_UUID);

  if (!hid) {
    Serial.println("ERROR: D18 HID service missing.");
    return false;
  }

  std::map<uint16_t, BLERemoteCharacteristic*>* chars =
    hid->getCharacteristicsByHandle();

  for (auto& entry : *chars) {

    BLERemoteCharacteristic* chr = entry.second;

    if (!chr->getUUID().equals(REPORT_UUID)) {
      continue;
    }

    BLERemoteDescriptor* reportRef = chr->getDescriptor(REPORT_REF_UUID);

    if (!reportRef) {
      continue;
    }

    uint16_t ref = reportRef->readUInt16();

    uint8_t reportId = ref & 0xFF;
    uint8_t reportType = (ref >> 8) & 0xFF;

    // Only INPUT reports.
    if (reportType != 1) {
      continue;
    }

    uint16_t handle = chr->getHandle();

    reportIdByHandle[handle] = reportId;

    Serial.printf("D18 Report %u | handle 0x%04X", reportId, handle);

    if (chr->canNotify()) {

      bool ok = chr->subscribe(true, notificationCallback, true);

      Serial.printf(" | subscribe: %s\n", ok ? "OK" : "FAILED");
    }
    else {
      Serial.println(" | notifications unsupported");
    }
  }

  return true;
}


// ============================================================
// BLE NOTIFICATION CALLBACK
//
// Runs on the BLE host task. Copy the report into the queue
// and get out; never block here.
// ============================================================

void D18Remote::notificationCallback(
  BLERemoteCharacteristic* characteristic,
  uint8_t* data,
  size_t length,
  bool isNotify
) {
  if (!instance || length == 0) {
    return;
  }

  HidEvent event {};

  event.handle = characteristic->getHandle();

  auto it = instance->reportIdByHandle.find(event.handle);

  if (it == instance->reportIdByHandle.end()) {
    return;
  }

  event.reportId = it->second;

  event.length = min(length, sizeof(event.data));

  memcpy(event.data, data, event.length);

  xQueueSend(instance->hidQueue, &event, 0);
}


// ============================================================
// UPDATE (main loop)
// ============================================================

void D18Remote::update() {

  HidEvent event;

  while (xQueueReceive(hidQueue, &event, 0) == pdTRUE) {
    processHidEvent(event);
  }

  // Resolve single center tap as button_3 once the
  // double-tap window has passed.
  if (pendingCenterTap && (millis() - pendingTapTime > DOUBLE_TAP_MS)) {
    pendingCenterTap = false;
    emitButton(3);
  }
}


void D18Remote::processHidEvent(const HidEvent& event) {

  switch (event.reportId) {

    case 1:
      processConsumerReport(event.data, event.length);
      break;

    case 2:
      processTouchReport(event.data, event.length);
      break;

    default:
      break;
  }
}


// ============================================================
// REPORT ID 1: CONSUMER CONTROL
//
// Known D18 mappings:
//
// button_6  -> 04 00
// button_7  -> 00 80
// button_8  -> 00 40
// button_10 -> 40 00
//
// 00 00 = release
// ============================================================

void D18Remote::processConsumerReport(const uint8_t* data, size_t length) {

  if (length < 2) {
    return;
  }

  uint16_t value = (uint16_t)data[0] | ((uint16_t)data[1] << 8);

  if (value == 0x0000) {
    return;
  }

  switch (value) {

    case 0x0004:
      emitButton(6);
      break;

    case 0x8000:
      emitButton(7);
      break;

    case 0x4000:
      emitButton(8);
      break;

    case 0x0040:
      emitButton(10);
      break;

    default:
      Serial.printf(
        "Unknown consumer report: %02X %02X\n",
        data[0],
        data[1]
      );
      break;
  }
}


// ============================================================
// REPORT ID 2: TOUCHPAD
// ============================================================

void D18Remote::decodeTouch(
  const uint8_t* data,
  int& x,
  int& y,
  bool& touching
) {
  touching = (data[0] & 0x01) != 0;

  x = data[1] | ((data[2] & 0x0F) << 8);

  y = ((data[2] >> 4) & 0x0F) | (data[3] << 4);
}


void D18Remote::processTouchReport(const uint8_t* data, size_t length) {

  if (length < 4) {
    return;
  }

  int x;
  int y;
  bool touching;

  decodeTouch(data, x, y, touching);


  // Touch begins.
  if (touching && !touch.active) {

    touch.active = true;

    touch.startX = x;
    touch.startY = y;

    touch.lastX = x;
    touch.lastY = y;

    return;
  }


  // Touch continues.
  if (touching && touch.active) {

    touch.lastX = x;
    touch.lastY = y;

    return;
  }


  // Touch released.
  if (!touching && touch.active) {

    touch.active = false;

    finishGesture();

    return;
  }
}


void D18Remote::finishGesture() {

  int dx = touch.lastX - touch.startX;
  int dy = touch.lastY - touch.startY;

  int absDx = abs(dx);
  int absDy = abs(dy);


  // button_1: swipe down
  if (dy > SWIPE_DISTANCE && absDy > absDx * 2) {
    emitButton(1);
    return;
  }

  // button_5: swipe up
  if (dy < -SWIPE_DISTANCE && absDy > absDx * 2) {
    emitButton(5);
    return;
  }

  // button_2: swipe right
  if (dx > SWIPE_DISTANCE && absDx > absDy * 2) {
    emitButton(2);
    return;
  }

  // button_4: swipe left
  if (dx < -SWIPE_DISTANCE && absDx > absDy * 2) {
    emitButton(4);
    return;
  }


  // button_3 / button_9: center tap
  bool smallMovement =
    absDx <= TAP_MAX_MOVEMENT &&
    absDy <= TAP_MAX_MOVEMENT;

  bool centerTap =
    touch.startX >= CENTER_X_MIN &&
    touch.startX <= CENTER_X_MAX &&
    touch.startY >= CENTER_Y_MIN &&
    touch.startY <= CENTER_Y_MAX;

  if (smallMovement && centerTap) {

    unsigned long now = millis();

    if (pendingCenterTap && (now - pendingTapTime <= DOUBLE_TAP_MS)) {
      pendingCenterTap = false;
      emitButton(9);
    }
    else {
      pendingCenterTap = true;
      pendingTapTime = now;
    }
  }
}


// ============================================================
// BUTTON EVENT
//
// Runs from update(), NOT from the BLE callback, so handlers
// are free to perform LED GATT writes.
// ============================================================

void D18Remote::emitButton(int buttonNumber) {

  Serial.printf("button_%d\n", buttonNumber);

  if (buttonHandler) {
    buttonHandler(buttonNumber);
  }
}
