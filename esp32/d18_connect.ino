// D18 BLE remote connection test
// Targets arduino-esp32 3.3.x (NimBLE-backed BLE library) on ESP32-S3.
// Uses only API calls common to both the Bluedroid and NimBLE backends.

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLESecurity.h>

static const char* TARGET_NAME = "D18";
static BLEUUID HID_SERVICE_UUID((uint16_t)0x1812);

static const int MAX_ROUNDS   = 12;  // scan+connect attempts before giving up
static const int SCAN_SECONDS = 3;   // short, so we connect while it's awake

static BLEClient* client = nullptr;

// Scan briefly; return a copy of the D18 advert if seen (caller frees it).
BLEAdvertisedDevice* findTarget() {
  BLEScan* scan = BLEDevice::getScan();
  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);          // window must be <= interval

  BLEScanResults* results = scan->start(SCAN_SECONDS, false);

  BLEAdvertisedDevice* found = nullptr;
  for (int i = 0; i < results->getCount(); i++) {
    BLEAdvertisedDevice d = results->getDevice(i);
    if (d.haveName() && d.getName() == TARGET_NAME) {
      Serial.printf("  found %s  addr=%s  type=%u  rssi=%d\n",
                    TARGET_NAME,
                    d.getAddress().toString().c_str(),
                    d.getAddressType(),
                    d.getRSSI());
      found = new BLEAdvertisedDevice(d);
      break;
    }
  }

  // The important bit: fully tear the scanner down before connecting.
  scan->stop();
  scan->clearResults();
  delay(100);

  return found;
}

bool attemptConnect(BLEAdvertisedDevice* target) {
  Serial.println("  connecting...");

  if (!client->connect(target)) {
    Serial.println("  connect() returned false");
    delay(500);
    return false;
  }

  Serial.println("  CONNECTED");
  delay(500);   // let the link settle before touching GATT

  Serial.println("  discovering HID service 0x1812...");
  BLERemoteService* hid = client->getService(HID_SERVICE_UUID);

  if (hid) {
    Serial.println("  HID service 0x1812 FOUND");
  } else {
    Serial.println("  HID service NOT found (may need encryption first)");
    Serial.println("  services the device does expose:");
    std::map<std::string, BLERemoteService*>* svcs = client->getServices();
    for (auto& kv : *svcs) {
      Serial.printf("    %s\n", kv.first.c_str());
    }
  }

  return true;
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println("\n=== D18 CONNECTION TEST ===");

  BLEDevice::init("ESP32-D18");
  BLEDevice::setPower(ESP_PWR_LVL_P9);

  BLESecurity* security = new BLESecurity();
  security->setCapability(ESP_IO_CAP_NONE);
  // bonding, no MITM, NO secure connections.
  // These cheap remotes are legacy-pairing only; requesting SC breaks them.
  security->setAuthenticationMode(true, false, false);

  // Create the client once and reuse it across attempts, so we never
  // leak or have to tear down GATT client state between rounds.
  client = BLEDevice::createClient();

  Serial.println("Press a button on the remote NOW to wake it.\n");
  delay(1500);

  for (int round = 1; round <= MAX_ROUNDS; round++) {
    Serial.printf("--- round %d/%d ---\n", round, MAX_ROUNDS);

    BLEAdvertisedDevice* target = findTarget();
    if (!target) {
      Serial.println("  not advertising this round");
      continue;
    }

    bool ok = attemptConnect(target);
    delete target;

    if (ok) {
      Serial.println("\nDone.");
      return;
    }
  }

  Serial.println("\nGave up after all rounds.");
}

void loop() {
  delay(1000);
}
