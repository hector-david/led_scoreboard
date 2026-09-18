#include "LedDisplay.h"

#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLERemoteService.h>


// ============================================================
// GATT IDENTIFIERS
// ============================================================

static BLEUUID LED_SERVICE_UUID("000000fa-0000-1000-8000-00805f9b34fb");
static BLEUUID LED_WRITE_UUID("0000fa02-0000-1000-8000-00805f9b34fb");
static BLEUUID LED_NOTIFY_UUID("0000fa03-0000-1000-8000-00805f9b34fb");


// ============================================================
// CONNECT
//
// Normally runs while the D18 remains connected. The scan
// object is shared with D18Remote; its callback ignores
// results unless D18Remote is the one scanning.
// ============================================================

bool LedDisplay::connect() {

  // Anything left from a previous link is invalid now.
  writeChar = nullptr;
  notifyChar = nullptr;

  BLEScan* scan = BLEDevice::getScan();

  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);

  Serial.println();
  Serial.println("Scanning for LED...");

  BLEScanResults* results = scan->start(Config::BLE_SCAN_SECONDS, false);

  BLEAdvertisedDevice* target = nullptr;

  for (int i = 0; i < results->getCount(); i++) {

    BLEAdvertisedDevice device = results->getDevice(i);

    if (device.haveName() && device.getName() == Config::LED_NAME) {
      target = new BLEAdvertisedDevice(device);
      break;
    }
  }

  if (!target) {
    Serial.println("LED not found.");
    scan->clearResults();
    return false;
  }

  Serial.println("LED found.");

  scan->clearResults();

  delay(50);

  if (!client) {
    client = BLEDevice::createClient();
  }

  Serial.println("Connecting to LED...");

  bool connected = client->connect(target);

  delete target;

  if (!connected) {
    Serial.println("ERROR: LED connection failed.");
    return false;
  }

  Serial.println("LED connected.");


  Serial.println("Requesting LED MTU 517...");

  bool mtuOk = client->setMTU(517);

  delay(100);

  Serial.printf(
    "LED MTU negotiation: %s | MTU: %u\n",
    mtuOk ? "OK" : "FAILED",
    client->getMTU()
  );


  BLERemoteService* service = client->getService(LED_SERVICE_UUID);

  // From here on a failure leaves a half-usable link, so
  // drop it: isConnected() must only be true when the
  // characteristics are ready.
  if (!service) {
    Serial.println("ERROR: LED FA service not found.");
    disconnect();
    return false;
  }

  writeChar = service->getCharacteristic(LED_WRITE_UUID);
  notifyChar = service->getCharacteristic(LED_NOTIFY_UUID);

  if (!writeChar || !notifyChar) {
    Serial.println("ERROR: LED characteristics missing.");
    disconnect();
    return false;
  }


  Serial.println("Subscribing to LED notifications...");

  if (!notifyChar->canNotify()) {
    Serial.println("ERROR: LED FA03 does not support notify.");
    disconnect();
    return false;
  }

  notifyChar->registerForNotify(notifyCallback);

  return true;
}


void LedDisplay::disconnect() {

  writeChar = nullptr;
  notifyChar = nullptr;

  if (client && client->isConnected()) {
    client->disconnect();
  }
}


bool LedDisplay::isConnected() const {
  return client && client->isConnected();
}


// ============================================================
// BRIGHTNESS
//
// Confirmed packet:
//   05 00 04 80 XX
//
// XX = brightness percentage, 0x0A..0x64 for 10..100 here.
// ============================================================

void LedDisplay::sendBrightness() {

  if (!isConnected() || !writeChar) {
    Serial.println("ERROR: Cannot send brightness; LED is not connected.");
    return;
  }

  uint8_t command[] = {
    0x05,
    0x00,
    0x04,
    0x80,
    (uint8_t)brightness
  };

  Serial.printf(
    "Brightness -> %d%% | packet: 05 00 04 80 %02X\n",
    brightness,
    command[4]
  );

  writeChar->writeValue(command, sizeof(command), false);
}


void LedDisplay::increaseBrightness() {

  brightness += Config::BRIGHTNESS_STEP;

  if (brightness > Config::BRIGHTNESS_MAX) {
    brightness = Config::BRIGHTNESS_MAX;
  }

  sendBrightness();
}


void LedDisplay::decreaseBrightness() {

  brightness -= Config::BRIGHTNESS_STEP;

  if (brightness < Config::BRIGHTNESS_MIN) {
    brightness = Config::BRIGHTNESS_MIN;
  }

  sendBrightness();
}


// ============================================================
// IMAGE PACKET
// ============================================================

bool LedDisplay::sendImagePacket(const uint8_t* packet, size_t length) {

  if (!isConnected() || !writeChar) {
    Serial.println("SEND ERROR: LED is not connected.");
    return false;
  }

  uint16_t mtu = client->getMTU();

  size_t maxWritePayload = mtu > 3 ? mtu - 3 : 0;

  Serial.printf(
    "Sending scoreboard | packet: %u bytes | MTU payload: %u bytes\n",
    (unsigned int)length,
    (unsigned int)maxWritePayload
  );

  // Important:
  // Do NOT allow the BLE library to silently turn
  // this proprietary packet into a prepared/long write.
  if (length > maxWritePayload) {
    Serial.println("SEND ERROR: packet exceeds negotiated MTU.");
    return false;
  }

  // writeValue takes a non-const pointer but does not modify the data.
  bool ok = writeChar->writeValue(
    const_cast<uint8_t*>(packet),
    length,
    true
  );

  Serial.printf("LED image write: %s\n", ok ? "OK" : "FAILED");

  return ok;
}


// ============================================================
// NOTIFICATION CALLBACK
//
// The panel ACKs each command on FA03.
// ============================================================

void LedDisplay::notifyCallback(
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
