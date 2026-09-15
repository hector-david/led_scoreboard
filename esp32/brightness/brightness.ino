#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>

const char* TARGET_NAME = "LED_BLE_CD9B89CA";

static BLEUUID SERVICE_UUID(
  "000000fa-0000-1000-8000-00805f9b34fb"
);

static BLEUUID WRITE_UUID(
  "0000fa02-0000-1000-8000-00805f9b34fb"
);

static BLEUUID NOTIFY_UUID(
  "0000fa03-0000-1000-8000-00805f9b34fb"
);

static void notifyCallback(
  BLERemoteCharacteristic* characteristic,
  uint8_t* data,
  size_t length,
  bool isNotify
) {
  Serial.print("Notification: ");

  for (size_t i = 0; i < length; i++) {
    if (data[i] < 0x10) Serial.print("0");
    Serial.print(data[i], HEX);

    if (i < length - 1) {
      Serial.print(" ");
    }
  }

  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("=== BRIGHTNESS COMMAND TEST ===");

  BLEDevice::init("");

  BLEScan* scan = BLEDevice::getScan();
  scan->setActiveScan(true);

  Serial.println("Scanning...");

  BLEScanResults* results = scan->start(10, false);

  BLEAdvertisedDevice* target = nullptr;

  for (int i = 0; i < results->getCount(); i++) {
    BLEAdvertisedDevice device = results->getDevice(i);

    if (device.haveName() &&
        device.getName() == TARGET_NAME) {

      target = new BLEAdvertisedDevice(device);
      break;
    }
  }

  if (!target) {
    Serial.println("ERROR: LED not found.");
    return;
  }

  Serial.println("LED found.");
  Serial.println("Connecting...");

  BLEClient* client = BLEDevice::createClient();

  if (!client->connect(target)) {
    Serial.println("ERROR: Connection failed.");
    return;
  }

  Serial.println("Connected.");

  BLERemoteService* service =
    client->getService(SERVICE_UUID);

  if (!service) {
    Serial.println("ERROR: Service not found.");
    return;
  }

  BLERemoteCharacteristic* writeChar =
    service->getCharacteristic(WRITE_UUID);

  BLERemoteCharacteristic* notifyChar =
    service->getCharacteristic(NOTIFY_UUID);

  if (!writeChar || !notifyChar) {
    Serial.println("ERROR: Characteristics missing.");
    return;
  }

  Serial.println("Subscribing to notifications...");

  if (notifyChar->canNotify()) {
    notifyChar->registerForNotify(notifyCallback);
  } else {
    Serial.println("ERROR: FA03 does not support notify.");
    return;
  }

  delay(500);

  uint8_t brightnessCommand[] = {
    0x05,
    0x00,
    0x04,
    0x80,
    0x64
  };

  Serial.println("Setting brightness to 30%...");

  writeChar->writeValue(
    brightnessCommand,
    sizeof(brightnessCommand),
    false
  );

  Serial.println("Command sent.");

  delay(3000);

  Serial.println("Test finished.");
}

void loop() {
}