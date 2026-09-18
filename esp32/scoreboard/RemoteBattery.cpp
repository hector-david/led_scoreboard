#include "RemoteBattery.h"

#include <BLEClient.h>
#include <BLERemoteService.h>
#include <BLERemoteCharacteristic.h>


// ============================================================
// GATT IDENTIFIERS
// ============================================================

static BLEUUID BATTERY_SERVICE_UUID((uint16_t)0x180F);
static BLEUUID BATTERY_LEVEL_UUID((uint16_t)0x2A19);


RemoteBattery::RemoteBattery(D18Remote& remote)
  : remote(remote) {
}


// ============================================================
// READ
// ============================================================

bool RemoteBattery::read(uint8_t& percent) {

  if (!remote.isConnected()) {
    Serial.println("BATTERY | D18 not connected.");
    return false;
  }

  BLEClient* client = remote.getClient();

  BLERemoteService* battery = client->getService(BATTERY_SERVICE_UUID);

  if (!battery) {
    Serial.println("BATTERY | Battery Service (0x180F) not found.");
    return false;
  }

  BLERemoteCharacteristic* level =
    battery->getCharacteristic(BATTERY_LEVEL_UUID);

  if (!level) {
    Serial.println("BATTERY | Battery Level (0x2A19) not found.");
    return false;
  }

  if (!level->canRead()) {
    Serial.println("BATTERY | Battery Level is not readable.");
    return false;
  }

  uint8_t value = level->readUInt8();

  // The spec caps the level at 100; anything above means the
  // read itself failed (the library returns 0 on error, which
  // is indistinguishable from a flat battery, so let that pass).
  if (value > 100) {
    Serial.printf("BATTERY | invalid level %u\n", value);
    return false;
  }

  percent = value;
  lastPercent = value;

  Serial.printf("BATTERY | D18: %u%%\n", value);

  return true;
}
