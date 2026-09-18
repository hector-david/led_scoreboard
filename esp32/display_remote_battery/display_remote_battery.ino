#include <Arduino.h>

#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLESecurity.h>
#include <BLERemoteService.h>
#include <BLERemoteCharacteristic.h>

#include <map>

// ============================================================
// D18 BLE REMOTE -> BATTERY LEVEL READER
//
// Step 1: connect + secure exactly like the button decoder,
// then look for the standard BLE Battery Service:
//
//   Service        0x180F  (Battery Service)
//   Characteristic 0x2A19  (Battery Level, 0..100 %)
//
// If the D18 exposes it, we read it once, subscribe to
// notifications (if supported), and re-read it periodically.
//
// If the D18 does NOT expose it, we print every service the
// remote advertises so we know where to look next.
// ============================================================

static const char* TARGET_NAME = "D18";

static BLEUUID BATTERY_SERVICE_UUID((uint16_t)0x180F);
static BLEUUID BATTERY_LEVEL_UUID((uint16_t)0x2A19);

static BLEAdvertisedDevice* target = nullptr;
static BLEClient* client = nullptr;

static BLERemoteCharacteristic* batteryChr = nullptr;

// How often to poll the battery level in loop().
static const unsigned long BATTERY_POLL_MS = 30000;

static unsigned long lastBatteryPoll = 0;


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
// BATTERY NOTIFICATION CALLBACK
//
// Some remotes push a notification whenever the level changes.
// ============================================================

void batteryNotifyCallback(
  BLERemoteCharacteristic* chr,
  uint8_t* data,
  size_t length,
  bool isNotify
) {
  if (length == 0) {
    return;
  }

  Serial.printf(
    "Battery (notify): %u%%\n",
    data[0]
  );
}


// ============================================================
// READ BATTERY LEVEL
// ============================================================

void readBattery() {

  if (!batteryChr) {
    return;
  }

  if (!batteryChr->canRead()) {
    Serial.println(
      "Battery characteristic is not readable."
    );

    return;
  }

  uint8_t level =
    batteryChr->readUInt8();

  Serial.printf(
    "Battery (read): %u%%\n",
    level
  );
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
  // The battery characteristic may be a protected attribute
  // just like the HID reports, so secure the link first.
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
// LIST ALL SERVICES
//
// Fallback diagnostic when the Battery Service is missing.
// ============================================================

void listServices() {

  Serial.println();
  Serial.println(
    "Services exposed by D18:"
  );

  std::map<
    std::string,
    BLERemoteService*
  >* services =
    client->getServices();

  if (!services) {
    Serial.println(
      "  (none)"
    );

    return;
  }

  for (auto& entry : *services) {

    BLERemoteService* svc =
      entry.second;

    Serial.printf(
      "  Service %s\n",
      svc->getUUID().toString().c_str()
    );

    std::map<
      std::string,
      BLERemoteCharacteristic*
    >* chars =
      svc->getCharacteristics();

    if (!chars) {
      continue;
    }

    for (auto& c : *chars) {

      BLERemoteCharacteristic* chr =
        c.second;

      Serial.printf(
        "    Char %s | handle 0x%04X | %s%s%s\n",
        chr->getUUID().toString().c_str(),
        chr->getHandle(),
        chr->canRead()   ? "R" : "-",
        chr->canNotify() ? "N" : "-",
        chr->canWrite()  ? "W" : "-"
      );
    }
  }

  Serial.println();
}


// ============================================================
// FIND BATTERY CHARACTERISTIC
// ============================================================

bool setupBattery() {

  BLERemoteService* batt =
    client->getService(
      BATTERY_SERVICE_UUID
    );

  if (!batt) {
    Serial.println(
      "Battery Service (0x180F) not found."
    );

    listServices();

    return false;
  }

  Serial.println(
    "Battery Service found."
  );

  batteryChr =
    batt->getCharacteristic(
      BATTERY_LEVEL_UUID
    );

  if (!batteryChr) {
    Serial.println(
      "Battery Level (0x2A19) not found."
    );

    listServices();

    return false;
  }

  Serial.printf(
    "Battery Level | handle 0x%04X | read: %s | notify: %s\n",
    batteryChr->getHandle(),
    batteryChr->canRead()   ? "yes" : "no",
    batteryChr->canNotify() ? "yes" : "no"
  );

  if (batteryChr->canNotify()) {

    bool ok =
      batteryChr->subscribe(
        true,
        batteryNotifyCallback,
        true
      );

    Serial.printf(
      "Battery notify subscribe: %s\n",
      ok ? "OK" : "FAILED"
    );
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
    "=== D18 BATTERY READER ==="
  );


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


  if (!setupBattery()) {
    return;
  }


  Serial.println();
  Serial.println(
    "================================"
  );

  // First read right away.
  readBattery();

  lastBatteryPoll = millis();

  Serial.println(
    "================================"
  );

  Serial.println();
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  if (!batteryChr) {
    delay(100);
    return;
  }

  if (
    millis() - lastBatteryPoll >=
    BATTERY_POLL_MS
  ) {
    lastBatteryPoll = millis();

    readBattery();
  }

  delay(50);
}
