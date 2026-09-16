#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLESecurity.h>
#include <BLERemoteService.h>
#include <BLERemoteCharacteristic.h>
#include <BLERemoteDescriptor.h>

#include <map>

// ============================================================
// D18 BLE REMOTE -> BUTTON DECODER
//
// Physical button layout:
//
//          button_1
//
// button_2  button_3  button_4
//
//          button_5
//
//          button_6
//
// button_7            button_8
//
//          button_9
//
//         button_10
//
// ============================================================

static const char* TARGET_NAME = "D18";

static BLEUUID HID_SERVICE_UUID((uint16_t)0x1812);
static BLEUUID REPORT_UUID((uint16_t)0x2A4D);
static BLEUUID REPORT_REF_UUID((uint16_t)0x2908);

static BLEAdvertisedDevice* target = nullptr;
static BLEClient* client = nullptr;

// Maps characteristic handle -> HID Report ID
static std::map<uint16_t, uint8_t> reportIdByHandle;


// ============================================================
// HID EVENT QUEUE
//
// BLE notification callbacks happen inside the BLE task.
// We copy the data into a queue and process it in loop().
// ============================================================

struct HidEvent {
  uint16_t handle;
  uint8_t reportId;
  uint8_t length;
  uint8_t data[8];
};

static QueueHandle_t hidQueue;


// ============================================================
// TOUCH GESTURE STATE
// ============================================================

struct TouchState {
  bool active = false;

  int startX = 0;
  int startY = 0;

  int lastX = 0;
  int lastY = 0;
};

static TouchState touch;


// button_3 vs button_9:
//
// button_3 = single center tap
// button_9 = double center tap
//
// We delay reporting button_3 slightly so we can determine
// whether a second tap follows.
//
static bool pendingCenterTap = false;
static unsigned long pendingTapTime = 0;

static const unsigned long DOUBLE_TAP_MS = 450;


// ============================================================
// PRINT BUTTON
// ============================================================

void emitButton(int buttonNumber) {
  Serial.printf("button_%d\n", buttonNumber);
}


// ============================================================
// BLE SCAN CALLBACK
// ============================================================

class D18ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice device) override {

    if (!device.haveName()) {
      return;
    }

    if (device.getName() != TARGET_NAME) {
      return;
    }

    Serial.println();
    Serial.println("D18 found.");

    Serial.printf(
      "Address: %s | RSSI: %d\n",
      device.getAddress().toString().c_str(),
      device.getRSSI()
    );

    target = new BLEAdvertisedDevice(device);

    BLEDevice::getScan()->stop();
  }
};


// ============================================================
// BLE NOTIFICATION CALLBACK
// ============================================================

void notificationCallback(
  BLERemoteCharacteristic* chr,
  uint8_t* data,
  size_t length,
  bool isNotify
) {
  if (length == 0) {
    return;
  }

  HidEvent event {};

  event.handle = chr->getHandle();

  auto it = reportIdByHandle.find(event.handle);

  if (it == reportIdByHandle.end()) {
    return;
  }

  event.reportId = it->second;

  event.length = min(
    length,
    sizeof(event.data)
  );

  memcpy(
    event.data,
    data,
    event.length
  );

  // Never block the BLE host task.
  xQueueSend(
    hidQueue,
    &event,
    0
  );
}


// ============================================================
// REPORT ID 1
//
// Consumer Control buttons.
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

void processConsumerReport(
  const uint8_t* data,
  size_t length
) {
  if (length < 2) {
    return;
  }

  uint16_t value =
    (uint16_t)data[0] |
    ((uint16_t)data[1] << 8);

  // Ignore release report.
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
// REPORT ID 2 TOUCH DECODER
//
// Byte layout from the D18 HID Report Map:
//
// byte 0:
//   bit 0 = Tip Switch
//   bit 1 = In Range
//   bit 2 = Confidence
//   bits 3-7 = Contact ID
//
// X = 12 bits
// Y = 12 bits
//
// Remaining 3 bytes:
//
//   byte1        = X bits 0..7
//   byte2 low    = X bits 8..11
//   byte2 high   = Y bits 0..3
//   byte3        = Y bits 4..11
// ============================================================

void decodeTouch(
  const uint8_t* data,
  int& x,
  int& y,
  bool& touching
) {
  touching = (data[0] & 0x01) != 0;

  x =
    data[1] |
    ((data[2] & 0x0F) << 8);

  y =
    ((data[2] >> 4) & 0x0F) |
    (data[3] << 4);
}


// ============================================================
// FINISH GESTURE
// ============================================================

void finishGesture() {

  int dx = touch.lastX - touch.startX;
  int dy = touch.lastY - touch.startY;

  int absDx = abs(dx);
  int absDy = abs(dy);

  // ----------------------------------------------------------
  // button_1
  //
  // Vertical swipe:
  // approximately Y 450 -> 1000
  // ----------------------------------------------------------

  if (
    dy > 250 &&
    absDy > absDx * 2
  ) {
    emitButton(1);
    return;
  }


  // ----------------------------------------------------------
  // button_5
  //
  // Opposite vertical swipe:
  // approximately Y 650 -> 0
  // ----------------------------------------------------------

  if (
    dy < -250 &&
    absDy > absDx * 2
  ) {
    emitButton(5);
    return;
  }


  // ----------------------------------------------------------
  // button_2
  //
  // Horizontal swipe:
  // approximately X 300 -> 950
  // ----------------------------------------------------------

  if (
    dx > 250 &&
    absDx > absDy * 2
  ) {
    emitButton(2);
    return;
  }


  // ----------------------------------------------------------
  // button_4
  //
  // Opposite horizontal swipe:
  // approximately X 800 -> 50
  // ----------------------------------------------------------

  if (
    dx < -250 &&
    absDx > absDy * 2
  ) {
    emitButton(4);
    return;
  }


  // ----------------------------------------------------------
  // button_3 / button_9
  //
  // Both touch roughly:
  //
  // X = 500
  // Y = 400
  //
  // button_3 = one tap
  // button_9 = two taps
  // ----------------------------------------------------------

  bool smallMovement =
    absDx <= 120 &&
    absDy <= 120;

  bool centerTap =
    touch.startX >= 400 &&
    touch.startX <= 600 &&
    touch.startY >= 300 &&
    touch.startY <= 500;

  if (
    smallMovement &&
    centerTap
  ) {

    unsigned long now = millis();

    if (
      pendingCenterTap &&
      (now - pendingTapTime <= DOUBLE_TAP_MS)
    ) {
      // Second tap -> button_9
      pendingCenterTap = false;

      emitButton(9);
    }
    else {
      // Could be button_3, but wait briefly
      // to see whether another tap arrives.
      pendingCenterTap = true;
      pendingTapTime = now;
    }

    return;
  }

  // Other touch gestures belong to things such as
  // button_6/button_10 and are intentionally ignored.
}


// ============================================================
// REPORT ID 2 PROCESSOR
// ============================================================

void processTouchReport(
  const uint8_t* data,
  size_t length
) {
  if (length < 4) {
    return;
  }

  int x;
  int y;
  bool touching;

  decodeTouch(
    data,
    x,
    y,
    touching
  );


  // Touch begins.
  if (
    touching &&
    !touch.active
  ) {
    touch.active = true;

    touch.startX = x;
    touch.startY = y;

    touch.lastX = x;
    touch.lastY = y;

    return;
  }


  // Touch continues.
  if (
    touching &&
    touch.active
  ) {
    touch.lastX = x;
    touch.lastY = y;

    return;
  }


  // Touch released.
  if (
    !touching &&
    touch.active
  ) {
    touch.active = false;

    finishGesture();

    return;
  }

  // Duplicate release packets are ignored.
}


// ============================================================
// PROCESS HID EVENT
// ============================================================

void processHidEvent(
  const HidEvent& event
) {

  switch (event.reportId) {

    case 1:
      processConsumerReport(
        event.data,
        event.length
      );
      break;

    case 2:
      processTouchReport(
        event.data,
        event.length
      );
      break;

    default:
      // Report IDs 3,4,5 currently unused.
      break;
  }
}


// ============================================================
// CONNECT TO D18
// ============================================================

bool connectD18() {

  BLEScan* scan = BLEDevice::getScan();

  scan->setAdvertisedDeviceCallbacks(
    new D18ScanCallbacks()
  );

  scan->setActiveScan(true);

  scan->setInterval(100);
  scan->setWindow(99);

  Serial.println(
    "Put D18 in pairing mode."
  );

  Serial.println(
    "Scanning..."
  );

  scan->start(
    10,
    false
  );

  if (!target) {
    Serial.println(
      "ERROR: D18 not found."
    );

    return false;
  }

  scan->clearResults();

  delay(50);

  client = BLEDevice::createClient();

  Serial.println(
    "Connecting..."
  );

  if (!client->connect(target)) {
    Serial.println(
      "ERROR: connection failed."
    );

    return false;
  }

  Serial.println(
    "D18 connected."
  );


  // ----------------------------------------------------------
  // Pair / encrypt
  //
  // Required to read the HID Report Map and for reliable
  // access to protected HID attributes.
  // ----------------------------------------------------------

  Serial.println(
    "Securing connection..."
  );

  if (!client->secureConnection()) {
    Serial.println(
      "ERROR: security failed."
    );

    return false;
  }

  Serial.println(
    "Connection secured."
  );

  return true;
}


// ============================================================
// SUBSCRIBE TO HID REPORTS
// ============================================================

bool setupHidReports() {

  BLERemoteService* hid =
    client->getService(
      HID_SERVICE_UUID
    );

  if (!hid) {
    Serial.println(
      "ERROR: HID service missing."
    );

    return false;
  }

  std::map<
    uint16_t,
    BLERemoteCharacteristic*
  >* chars =
    hid->getCharacteristicsByHandle();


  for (auto& entry : *chars) {

    BLERemoteCharacteristic* chr =
      entry.second;

    if (
      !chr->getUUID().equals(
        REPORT_UUID
      )
    ) {
      continue;
    }

    BLERemoteDescriptor* reportRef =
      chr->getDescriptor(
        REPORT_REF_UUID
      );

    if (!reportRef) {
      continue;
    }

    uint16_t ref =
      reportRef->readUInt16();

    uint8_t reportId =
      ref & 0xFF;

    uint8_t reportType =
      (ref >> 8) & 0xFF;


    // Only INPUT reports.
    if (reportType != 1) {
      continue;
    }

    uint16_t handle =
      chr->getHandle();

    reportIdByHandle[handle] =
      reportId;

    Serial.printf(
      "Report %u | handle 0x%04X",
      reportId,
      handle
    );

    if (chr->canNotify()) {

      bool ok =
        chr->subscribe(
          true,
          notificationCallback,
          true
        );

      Serial.printf(
        " | subscribe: %s\n",
        ok ? "OK" : "FAILED"
      );
    }
    else {
      Serial.println(
        " | notifications unsupported"
      );
    }
  }

  return true;
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(2000);

  Serial.println();
  Serial.println(
    "=== D18 BUTTON DECODER ==="
  );


  // Create HID event queue.
  hidQueue = xQueueCreate(
    32,
    sizeof(HidEvent)
  );

  if (!hidQueue) {
    Serial.println(
      "ERROR: could not create HID queue."
    );

    return;
  }


  BLEDevice::init(
    "ESP32-Scoreboard"
  );

  BLEDevice::setPower(
    ESP_PWR_LVL_P9
  );


  // D18 uses Just Works pairing.
  //
  // Bonding enabled
  // MITM disabled
  // Secure Connections not required
  //
  BLESecurity::setCapability(
    ESP_IO_CAP_NONE
  );

  BLESecurity::setAuthenticationMode(
    true,
    false,
    false
  );


  if (!connectD18()) {
    return;
  }


  if (!setupHidReports()) {
    return;
  }


  Serial.println();
  Serial.println(
    "================================"
  );

  Serial.println(
    "D18 READY"
  );

  Serial.println(
    "Press buttons..."
  );

  Serial.println(
    "================================"
  );

  Serial.println();
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  HidEvent event;


  // Process queued BLE events.
  while (
    xQueueReceive(
      hidQueue,
      &event,
      0
    ) == pdTRUE
  ) {
    processHidEvent(
      event
    );
  }


  // If only one center tap occurred,
  // eventually declare it button_3.
  if (pendingCenterTap) {

    if (
      millis() - pendingTapTime >
      DOUBLE_TAP_MS
    ) {
      pendingCenterTap = false;

      emitButton(3);
    }
  }


  delay(5);
}