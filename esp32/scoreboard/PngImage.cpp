#include "PngImage.h"

using Config::DISPLAY_WIDTH;
using Config::DISPLAY_HEIGHT;


// ============================================================
// WHY THIS DOES NOT USE PNGENC::addLine()
//
// PNGenc ends every zlib stream with Z_FULL_FLUSH and then
// Z_FINISH. After the pixel data that leaves an empty stored
// block and a second, empty final block. The panel took the
// 00 - 00 frame encoded that way (FA03 status 03) but never
// drew it: going from 01 - 00 down to 00 - 00 left 01 - 00 up,
// and 00 - 01 right after it showed fine.
//
// Pillow, which the Python version uses, feeds the rows with
// Z_NO_FLUSH and ends with one Z_FINISH, so the pixel data is
// itself the final block and nothing but the Adler-32 follows.
// This file does the same with PNGenc's bundled zlib. The row
// filters below make the same choices PNGenc did, so only the
// way the stream ends is different.
//
// Note the panel ACKs a PNG it cannot decode with status 03
// all the same: an ACK proves the transfer, not the picture.
// ============================================================

static const int BYTES_PER_PIXEL = 3;

static const int ROW_BYTES = DISPLAY_WIDTH * BYTES_PER_PIXEL;


// ============================================================
// ZLIB MEMORY
//
// PNGenc's zlib has malloc disabled, so it allocates from this
// pool. Window and memory level are the ones PNGenc used: a
// 4 KB window covers the whole 1552-byte image.
// ============================================================

static const int ZLIB_WINDOW_BITS = 12;

static const int ZLIB_MEM_LEVEL = 5;

// Exactly what deflateInit2_() asks for with those settings:
// its state, the window (2 bytes per slot), prev (one Pos per
// window slot), head (one Pos per hash slot) and the pending
// buffer (sizeof(ush) + 2 bytes per literal slot). Plus room
// for rounding each of the five allocations up to 4 bytes.
static const size_t ZLIB_POOL_SIZE =
  sizeof(deflate_state)
  + ((size_t)2 << ZLIB_WINDOW_BITS)
  + (sizeof(Pos) << ZLIB_WINDOW_BITS)
  + (sizeof(Pos) << (ZLIB_MEM_LEVEL + 7))
  + ((sizeof(ush) + 2) << (ZLIB_MEM_LEVEL + 6))
  + 5 * 4;

static uint8_t zlibPool[ZLIB_POOL_SIZE] __attribute__((aligned(4)));

static size_t zlibPoolUsed = 0;


static voidpf zlibAlloc(voidpf opaque, uInt items, uInt size) {

  size_t bytes = ((size_t)items * size + 3) & ~(size_t)3;

  if (zlibPoolUsed + bytes > sizeof(zlibPool)) {
    return Z_NULL;
  }

  voidpf block = &zlibPool[zlibPoolUsed];

  zlibPoolUsed += bytes;

  return block;
}


static void zlibFree(voidpf opaque, voidpf address) {
  // Nothing to do: deflateRows() rewinds the whole pool before
  // every image.
}


// ============================================================
// ROW FILTERS
//
// Same choice PNGenc makes: run all five PNG filters and keep
// the one whose output has the smallest sum of |signed byte|;
// the lowest-numbered filter wins a tie.
// ============================================================

static int paeth(int left, int up, int upLeft) {

  int estimate = left + up - upLeft;

  int toLeft = abs(estimate - left);
  int toUp = abs(estimate - up);
  int toUpLeft = abs(estimate - upLeft);

  if (toLeft <= toUp && toLeft <= toUpLeft) {
    return left;
  }

  if (toUp <= toUpLeft) {
    return up;
  }

  return upLeft;
}


// Filtered value of byte i of row. above is null for the first
// row, where PNG treats the row above as all zeros.
static uint8_t filterByte(uint8_t filter, const uint8_t* row, const uint8_t* above, int i) {

  int left = (i >= BYTES_PER_PIXEL) ? row[i - BYTES_PER_PIXEL] : 0;
  int up = above ? above[i] : 0;
  int upLeft = (above && i >= BYTES_PER_PIXEL) ? above[i - BYTES_PER_PIXEL] : 0;

  switch (filter) {

    case 1:  // Sub
      return (uint8_t)(row[i] - left);

    case 2:  // Up
      return (uint8_t)(row[i] - up);

    case 3:  // Average
      return (uint8_t)(row[i] - ((left + up) >> 1));

    case 4:  // Paeth
      return (uint8_t)(row[i] - paeth(left, up, upLeft));

    default: // None
      return row[i];
  }
}


static uint8_t chooseFilter(const uint8_t* row, const uint8_t* above) {

  uint8_t best = 0;

  uint32_t bestCost = UINT32_MAX;

  for (uint8_t filter = 0; filter <= 4; filter++) {

    uint32_t cost = 0;

    for (int i = 0; i < ROW_BYTES; i++) {

      uint8_t value = filterByte(filter, row, above, i);

      cost += (value < 128) ? value : 256 - value;
    }

    if (cost < bestCost) {
      bestCost = cost;
      best = filter;
    }
  }

  return best;
}


// ============================================================
// PNG
// ============================================================

static void writeBe32(uint8_t* destination, uint32_t value) {
  destination[0] = (value >> 24) & 0xFF;
  destination[1] = (value >> 16) & 0xFF;
  destination[2] = (value >> 8) & 0xFF;
  destination[3] = value & 0xFF;
}


bool PngImage::encode(const Framebuffer& framebuffer, uint8_t level) {

  length = 0;

  static const uint8_t SIGNATURE[8] = {
    0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A
  };

  memcpy(buffer, SIGNATURE, sizeof(SIGNATURE));

  size_t pos = sizeof(SIGNATURE);


  // IHDR: 32 x 16, 8 bits per channel, colour type 2 (RGB),
  // deflate, adaptive filtering, not interlaced.
  uint8_t* header = &buffer[pos + 8];

  writeBe32(&header[0], DISPLAY_WIDTH);
  writeBe32(&header[4], DISPLAY_HEIGHT);

  header[8] = 8;
  header[9] = 2;
  header[10] = 0;
  header[11] = 0;
  header[12] = 0;

  pos = finishChunk(pos, "IHDR", 13);


  // IDAT: compressed straight into place, leaving room for its
  // own length, type and CRC and for the 12-byte IEND chunk.
  size_t capacity = Config::PNG_BUFFER_SIZE - pos - 12 - 12;

  size_t compressed = 0;

  if (!deflateRows(framebuffer, level, &buffer[pos + 8], capacity, compressed)) {
    return false;
  }

  pos = finishChunk(pos, "IDAT", compressed);


  pos = finishChunk(pos, "IEND", 0);

  length = pos;

  return true;
}


bool PngImage::deflateRows(
  const Framebuffer& framebuffer,
  uint8_t level,
  uint8_t* out,
  size_t capacity,
  size_t& outLength
) {
  z_stream stream;

  memset(&stream, 0, sizeof(stream));

  stream.zalloc = zlibAlloc;
  stream.zfree = zlibFree;
  stream.opaque = Z_NULL;

  // Every image starts from an empty pool.
  zlibPoolUsed = 0;

  int result = deflateInit2(
    &stream,
    level,
    Z_DEFLATED,
    ZLIB_WINDOW_BITS,
    ZLIB_MEM_LEVEL,
    Z_DEFAULT_STRATEGY
  );

  if (result != Z_OK) {
    Serial.printf("PNG ERROR: deflateInit2() failed: %d\n", result);
    return false;
  }

  stream.next_out = out;
  stream.avail_out = (uInt)capacity;


  uint8_t row[ROW_BYTES];
  uint8_t previous[ROW_BYTES];

  // Filter type byte, then the filtered row.
  uint8_t filtered[1 + ROW_BYTES];

  for (int y = 0; y < DISPLAY_HEIGHT; y++) {

    for (int x = 0; x < DISPLAY_WIDTH; x++) {

      RGB pixel = framebuffer.getPixel(x, y);

      row[x * BYTES_PER_PIXEL + 0] = pixel.r;
      row[x * BYTES_PER_PIXEL + 1] = pixel.g;
      row[x * BYTES_PER_PIXEL + 2] = pixel.b;
    }

    const uint8_t* above = (y == 0) ? nullptr : previous;

    uint8_t filter = chooseFilter(row, above);

    filtered[0] = filter;

    for (int i = 0; i < ROW_BYTES; i++) {
      filtered[1 + i] = filterByte(filter, row, above, i);
    }

    memcpy(previous, row, ROW_BYTES);


    // No flush between rows, and none before the end: the last
    // row goes in with Z_FINISH, which makes the pixel data the
    // stream's one final block.
    bool lastRow = (y == DISPLAY_HEIGHT - 1);

    stream.next_in = filtered;
    stream.avail_in = sizeof(filtered);

    result = deflate(&stream, lastRow ? Z_FINISH : Z_NO_FLUSH);

    bool ok = lastRow
      ? (result == Z_STREAM_END)
      : (result == Z_OK && stream.avail_in == 0);

    if (!ok) {
      Serial.printf("PNG ERROR: deflate() failed on row %d: %d\n", y, result);
      deflateEnd(&stream);
      return false;
    }
  }

  outLength = stream.total_out;

  deflateEnd(&stream);

  return true;
}


size_t PngImage::finishChunk(size_t start, const char* type, size_t dataLength) {

  writeBe32(&buffer[start], (uint32_t)dataLength);

  memcpy(&buffer[start + 4], type, 4);

  // The CRC covers the type and the data, not the length.
  uint32_t crc = crc32(0L, &buffer[start + 4], (uInt)(4 + dataLength));

  writeBe32(&buffer[start + 8 + dataLength], crc);

  return start + 12 + dataLength;
}


void PngImage::printInfo() const {

  Serial.printf(
    "PNG encoded successfully: %u bytes\n",
    (unsigned int)length
  );

  Serial.print("PNG signature: ");

  size_t count = min(length, (size_t)8);

  for (size_t i = 0; i < count; i++) {

    if (buffer[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(buffer[i], HEX);

    if (i < count - 1) {
      Serial.print(" ");
    }
  }

  Serial.println();

  Serial.printf(
    "Projected LED packet size: %u bytes\n",
    (unsigned int)(length + Config::LED_HEADER_SIZE)
  );
}
