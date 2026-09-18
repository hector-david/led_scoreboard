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
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLESecurity.h>
#include <BLERemoteService.h>
#include <BLERemoteCharacteristic.h>
#include <BLERemoteDescriptor.h>

#include <map>

// ============================================================
// D18 + LED DUAL-CONNECTION TEST
//
// Goal:
//   - Stay connected to D18 HID remote
//   - Stay connected to LED_BLE_CD9B89CA
//   - button_1 -> brightness +10%
//   - button_5 -> brightness -10%
//
// This intentionally does NOT add automatic reconnection yet.
// First we want to prove both BLE links can coexist reliably.
// ============================================================


// ============================================================
// LED SCREEN
// ============================================================

static const char* LED_NAME = "LED_BLE_CD9B89CA";

static BLEUUID LED_SERVICE_UUID(
  "000000fa-0000-1000-8000-00805f9b34fb"
);

static BLEUUID LED_WRITE_UUID(
  "0000fa02-0000-1000-8000-00805f9b34fb"
);

static BLEUUID LED_NOTIFY_UUID(
  "0000fa03-0000-1000-8000-00805f9b34fb"
);

static BLEClient* ledClient = nullptr;
static BLERemoteCharacteristic* ledWriteChar = nullptr;
static BLERemoteCharacteristic* ledNotifyChar = nullptr;

static int brightness = 50;
static const int BRIGHTNESS_STEP = 10;
static const int MIN_BRIGHTNESS = 10;
static const int MAX_BRIGHTNESS = 100;


// ============================================================
// D18 REMOTE
// ============================================================

static const char* D18_NAME = "D18";

static BLEUUID HID_SERVICE_UUID((uint16_t)0x1812);
static BLEUUID REPORT_UUID((uint16_t)0x2A4D);
static BLEUUID REPORT_REF_UUID((uint16_t)0x2908);

static BLEAdvertisedDevice* d18Target = nullptr;
static BLEClient* d18Client = nullptr;

// Maps characteristic handle -> HID Report ID
static std::map<uint16_t, uint8_t> reportIdByHandle;


// ============================================================
// HID EVENT QUEUE
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


// button_3 = single center tap
// button_9 = double center tap
static bool pendingCenterTap = false;
static unsigned long pendingTapTime = 0;

static const unsigned long DOUBLE_TAP_MS = 450;


// ============================================================
// LED NOTIFICATION CALLBACK
// ============================================================

static void ledNotifyCallback(
  BLERemoteCharacteristic* characteristic,
  uint8_t* data,
  size_t length,
  bool isNotify
) {
  Serial.print("LED ACK: ");

  for (size_t i = 0; i < length; i++) {
    if (data[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(data[i], HEX);

    if (i < length - 1) {
      Serial.print(" ");
    }
  }

  Serial.println();
}


// ============================================================
// SEND LED BRIGHTNESS
//
// Confirmed packet:
//   05 00 04 80 XX
//
// XX = brightness percentage, 0x0A..0x64 for 10..100 here.
// ============================================================

void sendBrightness() {

  if (
    !ledClient ||
    !ledClient->isConnected() ||
    !ledWriteChar
  ) {
    Serial.println(
      "ERROR: Cannot send brightness; LED is not connected."
    );
    return;
  }

  uint8_t brightnessCommand[] = {
    0x05,
    0x00,
    0x04,
    0x80,
    (uint8_t)brightness
  };

  Serial.printf(
    "Brightness -> %d%% | packet: 05 00 04 80 %02X\n",
    brightness,
    brightnessCommand[4]
  );

  ledWriteChar->writeValue(
    brightnessCommand,
    sizeof(brightnessCommand),
    false
  );
}


void increaseBrightness() {
  brightness += BRIGHTNESS_STEP;

  if (brightness > MAX_BRIGHTNESS) {
    brightness = MAX_BRIGHTNESS;
  }

  sendBrightness();
}


void decreaseBrightness() {
  brightness -= BRIGHTNESS_STEP;

  if (brightness < MIN_BRIGHTNESS) {
    brightness = MIN_BRIGHTNESS;
  }

  sendBrightness();
}


// ============================================================
// BUTTON EVENT
//
// Important:
// This runs from loop(), NOT directly from the BLE callback.
// That keeps us from trying to perform an LED GATT write from
// inside the D18 notification callback.
// ============================================================

void emitButton(int buttonNumber) {

  Serial.printf(
    "button_%d\n",
    buttonNumber
  );

  switch (buttonNumber) {

    case 1:
      increaseBrightness();
      break;

    case 5:
      decreaseBrightness();
      break;

    default:
      // All other buttons are decoded but do nothing yet.
      break;
  }
}


// ============================================================
// D18 SCAN CALLBACK
// ============================================================

class D18ScanCallbacks : public BLEAdvertisedDeviceCallbacks {

  void onResult(
    BLEAdvertisedDevice device
  ) override {

    if (!device.haveName()) {
      return;
    }

    if (device.getName() != D18_NAME) {
      return;
    }

    Serial.println();
    Serial.println("D18 found.");

    Serial.printf(
      "Address: %s | RSSI: %d\n",
      device.getAddress().toString().c_str(),
      device.getRSSI()
    );

    d18Target =
      new BLEAdvertisedDevice(device);

    BLEDevice::getScan()->stop();
  }
};


// ============================================================
// D18 BLE NOTIFICATION CALLBACK
// ============================================================

void d18NotificationCallback(
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

  auto it =
    reportIdByHandle.find(
      event.handle
    );

  if (it == reportIdByHandle.end()) {
    return;
  }

  event.reportId =
    it->second;

  event.length =
    min(
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
// ============================================================

void decodeTouch(
  const uint8_t* data,
  int& x,
  int& y,
  bool& touching
) {
  touching =
    (data[0] & 0x01) != 0;

  x =
    data[1] |
    ((data[2] & 0x0F) << 8);

  y =
    ((data[2] >> 4) & 0x0F) |
    (data[3] << 4);
}


// ============================================================
// FINISH D18 GESTURE
// ============================================================

void finishGesture() {

  int dx =
    touch.lastX -
    touch.startX;

  int dy =
    touch.lastY -
    touch.startY;

  int absDx = abs(dx);
  int absDy = abs(dy);


  // button_1
  if (
    dy > 250 &&
    absDy > absDx * 2
  ) {
    emitButton(1);
    return;
  }


  // button_5
  if (
    dy < -250 &&
    absDy > absDx * 2
  ) {
    emitButton(5);
    return;
  }


  // button_2
  if (
    dx > 250 &&
    absDx > absDy * 2
  ) {
    emitButton(2);
    return;
  }


  // button_4
  if (
    dx < -250 &&
    absDx > absDy * 2
  ) {
    emitButton(4);
    return;
  }


  // button_3 / button_9
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
    unsigned long now =
      millis();

    if (
      pendingCenterTap &&
      (
        now -
        pendingTapTime <=
        DOUBLE_TAP_MS
      )
    ) {
      pendingCenterTap = false;

      emitButton(9);
    }
    else {
      pendingCenterTap = true;
      pendingTapTime = now;
    }

    return;
  }
}


// ============================================================
// PROCESS D18 TOUCH REPORT
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
}


// ============================================================
// PROCESS D18 HID EVENT
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
      break;
  }
}


// ============================================================
// CONNECT TO D18
//
// We connect D18 FIRST because it only advertises for a short
// time after a button press.
// ============================================================

bool connectD18() {

  BLEScan* scan =
    BLEDevice::getScan();

  scan->setAdvertisedDeviceCallbacks(
    new D18ScanCallbacks()
  );

  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);

  d18Target = nullptr;

  Serial.println(
    "Put D18 in pairing/advertising mode."
  );

  Serial.println(
    "Scanning for D18..."
  );

  scan->start(
    10,
    false
  );

  if (!d18Target) {
    Serial.println(
      "ERROR: D18 not found."
    );

    return false;
  }

  scan->clearResults();

  delay(50);

  d18Client =
    BLEDevice::createClient();

  Serial.println(
    "Connecting to D18..."
  );

  if (
    !d18Client->connect(
      d18Target
    )
  ) {
    Serial.println(
      "ERROR: D18 connection failed."
    );

    return false;
  }

  Serial.println(
    "D18 connected."
  );


  Serial.println(
    "Securing D18 connection..."
  );

  if (
    !d18Client->secureConnection()
  ) {
    Serial.println(
      "ERROR: D18 security failed."
    );

    return false;
  }

  Serial.println(
    "D18 connection secured."
  );

  return true;
}


// ============================================================
// SUBSCRIBE TO D18 HID REPORTS
// ============================================================

bool setupD18HidReports() {

  BLERemoteService* hid =
    d18Client->getService(
      HID_SERVICE_UUID
    );

  if (!hid) {
    Serial.println(
      "ERROR: D18 HID service missing."
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
      "D18 Report %u | handle 0x%04X",
      reportId,
      handle
    );

    if (chr->canNotify()) {

      bool ok =
        chr->subscribe(
          true,
          d18NotificationCallback,
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
// CONNECT TO LED SCREEN
//
// This scan happens while the D18 remains connected.
// That is the actual dual-BLE test.
// ============================================================

bool connectLed() {

  BLEScan* scan =
    BLEDevice::getScan();

  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);

  Serial.println();
  Serial.println(
    "D18 should still be connected."
  );

  Serial.println(
    "Scanning for LED while D18 stays connected..."
  );

  BLEScanResults* results =
    scan->start(
      10,
      false
    );

  BLEAdvertisedDevice* ledTarget =
    nullptr;

  for (
    int i = 0;
    i < results->getCount();
    i++
  ) {
    BLEAdvertisedDevice device =
      results->getDevice(i);

    if (
      device.haveName() &&
      device.getName() == LED_NAME
    ) {
      ledTarget =
        new BLEAdvertisedDevice(
          device
        );

      break;
    }
  }

  if (!ledTarget) {
    Serial.println(
      "ERROR: LED not found."
    );

    scan->clearResults();

    return false;
  }

  Serial.println(
    "LED found."
  );

  scan->clearResults();

  delay(50);

  ledClient =
    BLEDevice::createClient();

  Serial.println(
    "Connecting to LED..."
  );

  if (
    !ledClient->connect(
      ledTarget
    )
  ) {
    Serial.println(
      "ERROR: LED connection failed."
    );

    delete ledTarget;

    return false;
  }

  delete ledTarget;

  Serial.println(
    "LED connected."
  );


  BLERemoteService* service =
    ledClient->getService(
      LED_SERVICE_UUID
    );

  if (!service) {
    Serial.println(
      "ERROR: LED FA service not found."
    );

    return false;
  }


  ledWriteChar =
    service->getCharacteristic(
      LED_WRITE_UUID
    );

  ledNotifyChar =
    service->getCharacteristic(
      LED_NOTIFY_UUID
    );

  if (
    !ledWriteChar ||
    !ledNotifyChar
  ) {
    Serial.println(
      "ERROR: LED characteristics missing."
    );

    return false;
  }


  Serial.println(
    "Subscribing to LED notifications..."
  );

  if (
    ledNotifyChar->canNotify()
  ) {
    ledNotifyChar->registerForNotify(
      ledNotifyCallback
    );
  }
  else {
    Serial.println(
      "ERROR: LED FA03 does not support notify."
    );

    return false;
  }


  return true;
}


// ============================================================
// CONNECTION STATUS
// ============================================================

void printConnectionStatus() {

  bool d18Ok =
    d18Client &&
    d18Client->isConnected();

  bool ledOk =
    ledClient &&
    ledClient->isConnected();

  Serial.printf(
    "STATUS | D18: %s | LED: %s | brightness: %d%%\n",
    d18Ok ? "CONNECTED" : "DISCONNECTED",
    ledOk ? "CONNECTED" : "DISCONNECTED",
    brightness
  );
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(2000);

  Serial.println();
  Serial.println(
    "=== D18 + LED DUAL BLE TEST ==="
  );


  hidQueue =
    xQueueCreate(
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
  BLESecurity::setCapability(
    ESP_IO_CAP_NONE
  );

  BLESecurity::setAuthenticationMode(
    true,
    false,
    false
  );


  // 1) D18 first.
  if (!connectD18()) {
    return;
  }


  // 2) Subscribe to its HID reports.
  if (!setupD18HidReports()) {
    return;
  }


  // 3) While D18 stays connected, connect the LED.
  if (!connectLed()) {
    return;
  }


  delay(300);


  // Establish a known starting point.
  // We cannot assume the panel's existing brightness matches
  // our local variable, so explicitly set it to 50%.
  sendBrightness();


  Serial.println();
  Serial.println(
    "============================================"
  );

  Serial.println(
    "BOTH BLE DEVICES CONNECTED"
  );

  Serial.println(
    "button_1 = brightness +10%"
  );

  Serial.println(
    "button_5 = brightness -10%"
  );

  Serial.println(
    "============================================"
  );

  Serial.println();

  printConnectionStatus();
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  HidEvent event;


  // Process queued D18 events.
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


  // Resolve single center tap as button_3.
  if (pendingCenterTap) {

    if (
      millis() -
      pendingTapTime >
      DOUBLE_TAP_MS
    ) {
      pendingCenterTap = false;

      emitButton(3);
    }
  }


  // Print both connection states every 5 seconds.
  static unsigned long lastStatusTime = 0;

  if (
    millis() -
    lastStatusTime >= 5000
  ) {
    lastStatusTime =
      millis();

    printConnectionStatus();
  }


  delay(5);
}
