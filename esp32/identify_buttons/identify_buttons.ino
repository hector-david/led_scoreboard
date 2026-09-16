#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLERemoteCharacteristic.h>
#include <BLERemoteDescriptor.h>
#include <BLESecurity.h>

static const char* TARGET_NAME = "D18";

static BLEAdvertisedDevice* target = nullptr;
static bool foundTarget = false;

class D18ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice device) override {

    if (!device.haveName()) {
      return;
    }

    if (device.getName() != TARGET_NAME) {
      return;
    }

    Serial.println();
    Serial.println("D18 SEEN!");

    Serial.printf(
      "addr=%s  type=%u  rssi=%d\n",
      device.getAddress().toString().c_str(),
      device.getAddressType(),
      device.getRSSI()
    );

    // Make our own copy before scan results are cleared.
    target = new BLEAdvertisedDevice(device);
    foundTarget = true;

    Serial.println("Stopping scan NOW...");

    BLEDevice::getScan()->stop();
  }
};

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== D18 TRUE IMMEDIATE CONNECT TEST ===");

  BLEDevice::init("ESP32-D18");

  BLESecurity::setCapability(ESP_IO_CAP_NONE);

// Bonding, no MITM, don't require LE Secure Connections.
// Allows simple "Just Works" pairing.
BLESecurity::setAuthenticationMode(
  true,   // bonding
  false,  // MITM
  false   // Secure Connections not required
);

  BLEDevice::setPower(ESP_PWR_LVL_P9);

  BLEScan* scan = BLEDevice::getScan();

  scan->setAdvertisedDeviceCallbacks(
    new D18ScanCallbacks()
  );

  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);

  Serial.println("Put D18 in pairing mode.");
  Serial.println("Starting scan...");

  unsigned long startTime = millis();

  // This can run up to 10 seconds,
  // BUT our callback stops it immediately when D18 appears.
  scan->start(10, false);

  unsigned long foundTime = millis();

  Serial.printf(
    "Scan returned after %lu ms\n",
    foundTime - startTime
  );

  if (!foundTarget || target == nullptr) {
    Serial.println("ERROR: D18 not found.");
    return;
  }

  scan->clearResults();

  // Tiny pause only to allow scanner shutdown to settle.
  delay(50);

  Serial.println("Creating client...");

  BLEClient* client = BLEDevice::createClient();

  Serial.println("CONNECTING NOW...");

  unsigned long connectStart = millis();

  bool ok = client->connectTimeout(
    target,
    10000
  );

  Serial.printf(
    "connect() finished after %lu ms\n",
    millis() - connectStart
  );

  if (!ok) {
    Serial.println("ERROR: Connection failed.");
    return;
  }

  Serial.println();
  Serial.println("SUCCESS: D18 CONNECTED!");

  Serial.println("Securing / pairing connection...");

  bool secured = client->secureConnection();

  Serial.printf(
    "Security result: %s\n",
    secured ? "SUCCESS" : "FAILED"
  );

  if (!secured) {
    return;
  }

  delay(500);

  Serial.printf("RSSI: %d\n", client->getRssi());
  Serial.println();
Serial.println("Looking for HID service 0x1812...");

BLERemoteService* hid =
  client->getService(BLEUUID((uint16_t)0x1812));

if (!hid) {
  Serial.println("ERROR: HID service not found.");
  return;
}

Serial.println("HID service FOUND!");

Serial.println();
Serial.println("Reading HID Report Map 0x2A4B...");

BLERemoteCharacteristic* reportMap =
  hid->getCharacteristic(BLEUUID((uint16_t)0x2A4B));

if (!reportMap) {
  Serial.println("ERROR: Report Map characteristic not found.");
  return;
}

String mapData = reportMap->readValue();

Serial.printf("Report Map length: %u bytes\n", mapData.length());
Serial.println("Report Map HEX:");

for (size_t i = 0; i < mapData.length(); i++) {
  uint8_t b = (uint8_t)mapData[i];

  if (b < 0x10) Serial.print("0");
  Serial.print(b, HEX);
  Serial.print(" ");

  if ((i + 1) % 16 == 0) {
    Serial.println();
  }
}

Serial.println();
Serial.println("End Report Map");
Serial.println();

// Important: use handles, not UUID map.
// D18 has multiple 0x2A4D report characteristics.
std::map<uint16_t, BLERemoteCharacteristic*>* chars =
  hid->getCharacteristicsByHandle();

Serial.printf("Characteristics by handle: %d\n", chars->size());

for (auto& entry : *chars) {
  uint16_t handle = entry.first;
  BLERemoteCharacteristic* c = entry.second;

  Serial.printf(
    "Handle 0x%04X | UUID %s | NOTIFY:%s\n",
    handle,
    c->getUUID().toString().c_str(),
    c->canNotify() ? "Y" : "N"
  );

  if (c->getUUID().equals(BLEUUID((uint16_t)0x2A4D))) {

    BLERemoteDescriptor* reportRef =
      c->getDescriptor(BLEUUID((uint16_t)0x2908));

    if (reportRef) {
      uint16_t ref = reportRef->readUInt16();

      uint8_t reportId   = ref & 0xFF;
      uint8_t reportType = (ref >> 8) & 0xFF;

      Serial.printf(
        "  Report Reference: ID=%u Type=%u",
        reportId,
        reportType
      );

      if (reportType == 1) Serial.print(" (INPUT)");
      if (reportType == 2) Serial.print(" (OUTPUT)");
      if (reportType == 3) Serial.print(" (FEATURE)");

      Serial.println();

    } else {
      Serial.println("  Report Reference 0x2908 not found");
    }
  }

  if (c->getUUID().equals(BLEUUID((uint16_t)0x2A4D)) &&
      c->canNotify()) {

    bool ok = c->subscribe(
      true,
      [](BLERemoteCharacteristic* chr,
         uint8_t* data,
         size_t length,
         bool isNotify) {

        Serial.printf(
          "REPORT handle=0x%04X len=%u data=",
          chr->getHandle(),
          (unsigned)length
        );

        for (size_t i = 0; i < length; i++) {
          if (data[i] < 0x10) Serial.print("0");
          Serial.print(data[i], HEX);

          if (i + 1 < length) Serial.print(" ");
        }

        Serial.println();
      },
      true
    );

    Serial.printf(
      "  Subscribe handle 0x%04X: %s\n",
      handle,
      ok ? "OK" : "FAILED"
    );
  }
}

Serial.println();
Serial.println("Ready. Press D18 buttons...");
}

void loop() {
  delay(1000);
}