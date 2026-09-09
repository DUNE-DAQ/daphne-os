#pragma once

#include <cstdint>

namespace ad5327 {
// AD5327 Rev. D, p. 17: addressed output [15:14], GAIN [13], BUF [12],
// code [11:0]. GAIN=0 selects x1; GAIN=1 selects x2 for that output only.
// This is a command word, not hardware readback.
constexpr uint32_t encode_word(uint32_t channel, uint32_t code, bool gain, bool buffer) {
  return ((channel & 0x3u) << 14) | (uint32_t(gain) << 13) |
         (uint32_t(buffer) << 12) | (code & 0xFFFu);
}
}
