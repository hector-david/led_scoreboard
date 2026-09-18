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
#include <PNGenc.h>

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
// SCOREBOARD STATE
// ============================================================

static uint8_t team1Score = 0;
static uint8_t team2Score = 0;

// ============================================================
// SCOREBOARD DISPLAY
// ============================================================

static const int WIDTH = 32;
static const int HEIGHT = 16;

struct RGB {
  uint8_t r;
  uint8_t g;
  uint8_t b;
};

static const RGB BLACK = {
  0, 0, 0
};

static const RGB TEAM1_COLOR = {
  255, 0, 0
};

static const RGB TEAM2_COLOR = {
  0, 0, 255
};


// 32 x 16 x 3 bytes = 1536 bytes
static RGB framebuffer[HEIGHT][WIDTH];


// ============================================================
// PNG ENCODER
// ============================================================

static PNGENC pngEncoder;

// More than enough for a 32x16 RGB PNG.
static const size_t PNG_BUFFER_SIZE = 4096;

static uint8_t pngBuffer[PNG_BUFFER_SIZE];

static size_t pngSize = 0;

// ============================================================
// LED IMAGE PACKET
// ============================================================

static const uint8_t BUFFER_NUMBER = 1;

static const size_t LED_HEADER_SIZE = 15;

static uint8_t ledPacket[
  PNG_BUFFER_SIZE + LED_HEADER_SIZE
];

static size_t ledPacketSize = 0;


// Same layout as the working Python scoreboard.
static const int DIGIT_W = 7;
static const int DIGIT_H = 14;
static const int DIGIT_GAP = 1;
static const int DIGIT_Y = 1;

static const int TEAM1_X = 0;
static const int TEAM2_X = 17;

// ============================================================
// DISPLAY FONT
// ============================================================

static const char* DIGITS[10][14] = {

  // 0
  {
    ".11111.",
    "1111111",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "1111111",
    ".11111."
  },

  // 1
  {
    "...11..",
    "..111..",
    ".1111..",
    "...11..",
    "...11..",
    "...11..",
    "...11..",
    "...11..",
    "...11..",
    "...11..",
    "...11..",
    "...11..",
    "1111111",
    "1111111"
  },

  // 2
  {
    ".11111.",
    "1111111",
    "11...11",
    ".....11",
    ".....11",
    "....111",
    "...111.",
    "..111..",
    ".111...",
    "11.....",
    "11.....",
    "11.....",
    "1111111",
    "1111111"
  },

  // 3
  {
    ".11111.",
    "1111111",
    "11...11",
    ".....11",
    ".....11",
    ".....11",
    "..1111.",
    "..1111.",
    ".....11",
    ".....11",
    ".....11",
    "11...11",
    "1111111",
    ".11111."
  },

  // 4
  {
    ".....11",
    "....111",
    "...1111",
    "..11.11",
    ".11..11",
    "11...11",
    "1111111",
    "1111111",
    ".....11",
    ".....11",
    ".....11",
    ".....11",
    ".....11",
    ".....11"
  },

  // 5
  {
    "1111111",
    "1111111",
    "11.....",
    "11.....",
    "11.....",
    "111111.",
    "1111111",
    ".....11",
    ".....11",
    ".....11",
    ".....11",
    "11...11",
    "1111111",
    ".11111."
  },

  // 6
  {
    ".11111.",
    "1111111",
    "11...11",
    "11.....",
    "11.....",
    "111111.",
    "1111111",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "1111111",
    ".11111."
  },

  // 7
  {
    "1111111",
    "1111111",
    ".....11",
    ".....11",
    "....11.",
    "....11.",
    "...11..",
    "...11..",
    "..11...",
    "..11...",
    "..11...",
    "..11...",
    "..11...",
    "..11..."
  },

  // 8
  {
    ".11111.",
    "1111111",
    "11...11",
    "11...11",
    "11...11",
    ".11111.",
    ".11111.",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "1111111",
    ".11111."
  },

  // 9
  {
    ".11111.",
    "1111111",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "11...11",
    "1111111",
    ".111111",
    ".....11",
    ".....11",
    "11...11",
    "1111111",
    ".11111."
  }
};

uint32_t calculateCrc32(
  const uint8_t* data,
  size_t length
) {

  uint32_t crc = 0xFFFFFFFF;


  for (size_t i = 0; i < length; i++) {

    crc ^= data[i];


    for (int bit = 0; bit < 8; bit++) {

      if (crc & 1) {

        crc =
          (crc >> 1) ^
          0xEDB88320;

      }
      else {

        crc >>= 1;
      }
    }
  }


  return crc ^ 0xFFFFFFFF;
}

void writeLe16(
  uint8_t* destination,
  uint16_t value
) {

  destination[0] =
    value & 0xFF;

  destination[1] =
    (value >> 8) & 0xFF;
}


void writeLe32(
  uint8_t* destination,
  uint32_t value
) {

  destination[0] =
    value & 0xFF;

  destination[1] =
    (value >> 8) & 0xFF;

  destination[2] =
    (value >> 16) & 0xFF;

  destination[3] =
    (value >> 24) & 0xFF;
}

bool buildLedImagePacket() {

  if (pngSize == 0) {

    Serial.println(
      "PACKET ERROR: PNG size is zero."
    );

    return false;
  }


  ledPacketSize =
    LED_HEADER_SIZE +
    pngSize;


  if (
    ledPacketSize >
    sizeof(ledPacket)
  ) {

    Serial.println(
      "PACKET ERROR: packet buffer too small."
    );

    return false;
  }


  uint32_t crc =
    calculateCrc32(
      pngBuffer,
      pngSize
    );


  // Bytes 0-1
  // Total packet length
  writeLe16(
    &ledPacket[0],
    (uint16_t)ledPacketSize
  );


  // Bytes 2-3
  // Command 0x0002
  ledPacket[2] = 0x02;
  ledPacket[3] = 0x00;


  // Byte 4
  ledPacket[4] = 0x00;


  // Bytes 5-8
  // PNG byte length
  writeLe32(
    &ledPacket[5],
    (uint32_t)pngSize
  );


  // Bytes 9-12
  // PNG CRC32
  writeLe32(
    &ledPacket[9],
    crc
  );


  // Byte 13
  ledPacket[13] = 0x00;


  // Byte 14
  ledPacket[14] =
    BUFFER_NUMBER;


  // Bytes 15...
  // Actual PNG
  memcpy(
    &ledPacket[15],
    pngBuffer,
    pngSize
  );


  Serial.printf(
    "LED packet built | PNG: %u | CRC32: %08lX | total: %u\n",
    (unsigned int)pngSize,
    (unsigned long)crc,
    (unsigned int)ledPacketSize
  );


  Serial.print(
    "Header: "
  );


  for (int i = 0; i < 15; i++) {

    if (ledPacket[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(
      ledPacket[i],
      HEX
    );

    if (i < 14) {
      Serial.print(" ");
    }
  }


  Serial.println();


  return true;
}

void clearFramebuffer() {

  for (int y = 0; y < HEIGHT; y++) {

    for (int x = 0; x < WIDTH; x++) {

      framebuffer[y][x] = BLACK;
    }
  }
}

// ============================================================
// DRAW DIGITS
// ============================================================

void drawDigit(
  int digit,
  int startX,
  int startY,
  RGB color
) {

  if (
    digit < 0 ||
    digit > 9
  ) {
    return;
  }


  for (
    int row = 0;
    row < DIGIT_H;
    row++
  ) {

    for (
      int col = 0;
      col < DIGIT_W;
      col++
    ) {

      if (
        DIGITS[digit][row][col]
        != '1'
      ) {
        continue;
      }


      int x =
        startX + col;

      int y =
        startY + row;


      if (
        x >= 0 &&
        x < WIDTH &&
        y >= 0 &&
        y < HEIGHT
      ) {
        framebuffer[y][x] =
          color;
      }
    }
  }
}

void drawScore(
  uint8_t score,
  int startX,
  RGB color
) {

  if (score > 99) {
    score = 99;
  }


  int tens =
    score / 10;

  int ones =
    score % 10;


  drawDigit(
    tens,
    startX,
    DIGIT_Y,
    color
  );


  drawDigit(
    ones,
    startX + DIGIT_W + DIGIT_GAP,
    DIGIT_Y,
    color
  );
}

void renderScoreboard() {

  clearFramebuffer();


  drawScore(
    team1Score,
    TEAM1_X,
    TEAM1_COLOR
  );


  drawScore(
    team2Score,
    TEAM2_X,
    TEAM2_COLOR
  );
}

void printFramebuffer() {

  Serial.println();

  Serial.printf(
    "FRAMEBUFFER | T1 %02u | T2 %02u\n",
    team1Score,
    team2Score
  );

  Serial.println(
    "--------------------------------"
  );


  for (
    int y = 0;
    y < HEIGHT;
    y++
  ) {

    for (
      int x = 0;
      x < WIDTH;
      x++
    ) {

      RGB pixel =
        framebuffer[y][x];


      // Team 1 = Red
      if (
        pixel.r > 0 &&
        pixel.g == 0 &&
        pixel.b == 0
      ) {
        Serial.print("R");
      }

      // Team 2 = Blue
      else if (
        pixel.r == 0 &&
        pixel.g == 0 &&
        pixel.b > 0
      ) {
        Serial.print("B");
      }

      // Black
      else {
        Serial.print(".");
      }
    }

    Serial.println();
  }


  Serial.println(
    "--------------------------------"
  );

  Serial.println();
}

void updateScoreboard() {

  // 1. Score variables -> RGB pixels
  renderScoreboard();


  // Keep this for debugging for now.
  printFramebuffer();


  // 2. RGB pixels -> PNG
  if (
    !encodeFramebufferToPng()
  ) {
    return;
  }


  printPngInfo();


  // 3. PNG -> proprietary LED packet
  if (
    !buildLedImagePacket()
  ) {
    return;
  }


  // 4. Send packet to physical LED
  sendLedImagePacket();
}

// ============================================================
// PNG Function
// ============================================================

bool encodeFramebufferToPng() {

  pngSize = 0;

  // Tell PNGenc to write directly into our RAM buffer.
  int result =
    pngEncoder.open(
      pngBuffer,
      PNG_BUFFER_SIZE
    );

  if (result != PNG_SUCCESS) {

    Serial.printf(
      "PNG ERROR: open() failed: %d\n",
      result
    );

    return false;
  }


  // Match the Python version:
  //
  // 32 x 16
  // RGB888
  // 8 bits/channel
  // compression level 6
  result =
    pngEncoder.encodeBegin(
      WIDTH,
      HEIGHT,
      PNG_PIXEL_TRUECOLOR,
      8,
      nullptr,
      6
    );

  if (result != PNG_SUCCESS) {

    Serial.printf(
      "PNG ERROR: encodeBegin() failed: %d\n",
      result
    );

    pngEncoder.close();

    return false;
  }


  // PNGenc accepts one row at a time.
  uint8_t row[WIDTH * 3];


  for (int y = 0; y < HEIGHT; y++) {

    int index = 0;

    for (int x = 0; x < WIDTH; x++) {

      row[index++] =
        framebuffer[y][x].r;

      row[index++] =
        framebuffer[y][x].g;

      row[index++] =
        framebuffer[y][x].b;
    }


    result =
      pngEncoder.addLine(row);


    if (result != PNG_SUCCESS) {

      Serial.printf(
        "PNG ERROR: addLine() failed on row %d: %d\n",
        y,
        result
      );

      pngEncoder.close();

      return false;
    }
  }


  // close() finalizes the PNG and returns
  // the number of bytes written.
  int finalSize =
    pngEncoder.close();


  if (finalSize <= 0) {

    Serial.printf(
      "PNG ERROR: close() returned %d\n",
      finalSize
    );

    return false;
  }


  pngSize =
    (size_t)finalSize;


  return true;
}

void printPngInfo() {

  Serial.printf(
    "PNG encoded successfully: %u bytes\n",
    (unsigned int)pngSize
  );


  Serial.print(
    "PNG signature: "
  );


  size_t count =
    min(
      pngSize,
      (size_t)8
    );


  for (size_t i = 0; i < count; i++) {

    if (pngBuffer[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(
      pngBuffer[i],
      HEX
    );

    if (i < count - 1) {
      Serial.print(" ");
    }
  }


  Serial.println();


  Serial.printf(
    "Projected LED packet size: %u bytes\n",
    (unsigned int)(pngSize + 15)
  );
}

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

// Explicit prototype to prevent Arduino's
// automatic prototype generation from
// placing this before HidEvent is defined.
void processHidEvent(
  const HidEvent& event
);


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

      if (team1Score < 99) {
        team1Score++;
      }

      Serial.printf(
        "SCORE | Team 1: %u | Team 2: %u\n",
        team1Score,
        team2Score
      );

      updateScoreboard();

      break;


    case 5:

      // Team 2 comes next.
      // Do nothing for now.

      break;


    default:

      // Other buttons do nothing yet.

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

  Serial.println(
    "Requesting LED MTU 517..."
  );


  bool mtuOk =
    ledClient->setMTU(
      517
    );


  delay(100);


  Serial.printf(
    "LED MTU negotiation: %s | MTU: %u\n",
    mtuOk ? "OK" : "FAILED",
    ledClient->getMTU()
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

bool sendLedImagePacket() {

  if (
    !ledClient ||
    !ledClient->isConnected() ||
    !ledWriteChar
  ) {

    Serial.println(
      "SEND ERROR: LED is not connected."
    );

    return false;
  }


  uint16_t mtu =
    ledClient->getMTU();


  size_t maxWritePayload =
    mtu > 3
      ? mtu - 3
      : 0;


  Serial.printf(
    "Sending scoreboard | packet: %u bytes | MTU payload: %u bytes\n",
    (unsigned int)ledPacketSize,
    (unsigned int)maxWritePayload
  );


  // Important:
  // Do NOT allow the BLE library to silently turn
  // this proprietary packet into a prepared/long write.
  if (
    ledPacketSize >
    maxWritePayload
  ) {

    Serial.println(
      "SEND ERROR: packet exceeds negotiated MTU."
    );

    return false;
  }


  bool ok =
    ledWriteChar->writeValue(
      ledPacket,
      ledPacketSize,
      true
    );


  Serial.printf(
    "LED image write: %s\n",
    ok ? "OK" : "FAILED"
  );


  return ok;
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
    "STATUS | D18: %s | LED: %s | T1: %u | T2: %u\n",
    d18Ok ? "CONNECTED" : "DISCONNECTED",
    ledOk ? "CONNECTED" : "DISCONNECTED",
    team1Score,
    team2Score
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
  "button_1 = Team 1 +1"
  );

  Serial.println(
    "button_5 = not assigned yet"
  );

  Serial.println(
    "============================================"
  );

  Serial.println();

  Serial.printf(
    "INITIAL SCORE | Team 1: %u | Team 2: %u\n",
    team1Score,
    team2Score
  );

  printConnectionStatus();

  // renderScoreboard();

  delay(1000);

  testSolidRedFrame();

  printFramebuffer();
}


// ============================================================
// TEMP TEMP TEMP
// ============================================================

void testSolidRedFrame() {

  Serial.println(
    "TEST: building solid RED framebuffer"
  );

  for (int y = 0; y < HEIGHT; y++) {

    for (int x = 0; x < WIDTH; x++) {

      framebuffer[y][x].r = 255;
      framebuffer[y][x].g = 0;
      framebuffer[y][x].b = 0;
    }
  }


  if (!encodeFramebufferToPng()) {

    Serial.println(
      "TEST FAILED: PNG encoding"
    );

    return;
  }


  printPngInfo();


  if (!buildLedImagePacket()) {

    Serial.println(
      "TEST FAILED: packet build"
    );

    return;
  }


  sendLedImagePacket();
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
