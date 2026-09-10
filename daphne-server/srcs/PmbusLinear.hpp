#pragma once

#include <cmath>
#include <cstdint>
#include <stdexcept>

namespace daphne_sc {
// PMBus L11: signed 5-bit exponent and signed 11-bit mantissa. Use arithmetic
// subtraction for sign extension, avoiding implementation-defined signed casts.
inline double pmbus_linear11(uint16_t raw) {
  const int exponent = int(raw >> 11) - ((raw & 0x8000) ? 32 : 0);
  const int mantissa = int(raw & 0x07ff) - ((raw & 0x0400) ? 2048 : 0);
  return std::ldexp(double(mantissa), exponent);
}
// VOUT_MODE selects the format; linear VOUT has an UNSIGNED 16-bit mantissa.
// Do not use L11 or cast the mantissa to int16_t. VID/direct formats need
// different conversion information and must not silently use this decoder.
inline double pmbus_linear16(uint16_t raw, uint8_t vout_mode) {
  if (vout_mode & 0xe0) throw std::invalid_argument("Nonlinear PMBus VOUT_MODE");
  const int exponent = int(vout_mode & 0x1f) - ((vout_mode & 0x10) ? 32 : 0);
  return std::ldexp(double(raw), exponent);
}
} // namespace daphne_sc
