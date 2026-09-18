Set:
Tools > Flash Size:
Board:              ESP32S3 Dev Module
Port:               COM7
Upload Speed:       921600
USB CDC On Boot:    Disabled
CPU Frequency:      240MHz (WiFi)
Flash Mode:         QIO 80MHz
Flash Size:         16MB (128Mb)
PSRAM:              OPI PSRAM

Open:
C:\Users\hecto\AppData\Local\Arduino15\packages\esp32\hardware\esp32\3.3.11\libraries\BLE\src\BLEClient.cpp

search for:
rc = ble_gattc_exchange_mtu(client->m_conn_id, nullptr, nullptr);

Should see:
rc = ble_gattc_exchange_mtu(client->m_conn_id, nullptr, nullptr);
if (rc != 0) {
  log_e("BLEClient", "MTU exchange error; rc=%d %s", rc, BLEUtils::returnCodeToString(rc));
  break;
}

Replace block with:

rc = ble_gattc_exchange_mtu(client->m_conn_id, nullptr, nullptr);

if (rc == BLE_HS_EALREADY) {
  log_w("BLEClient", "MTU exchange already in progress; treating connection as established");

  // The peer already started the MTU procedure.
  // Do not wait 30 seconds for an MTU event that may never arrive.
  if (pTaskData != nullptr) {
    BLEUtils::taskRelease(*pTaskData, 0);
  }

  return 0;
}

if (rc != 0) {
  log_e("BLEClient", "MTU exchange error; rc=%d %s",
        rc, BLEUtils::returnCodeToString(rc));
  break;
}


Installed Library:
PNGenc