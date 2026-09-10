#include "PmbusLinear.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

void check(bool ok) { if (!ok) throw std::runtime_error("PMBus numeric test failed"); }
int main() {
  // Exhaust the complete wire space, not just the nominal rail voltages.
  for (unsigned raw = 0; raw < 65536; ++raw) {
    int exponent = raw / 2048; if (exponent >= 16) exponent -= 32;
    int mantissa = raw % 2048; if (mantissa >= 1024) mantissa -= 2048;
    check(daphne_sc::pmbus_linear11(raw) == mantissa * std::pow(2., exponent));
    for (unsigned mode = 0; mode < 32; ++mode) {
      int e = mode; if (e >= 16) e -= 32;
      check(daphne_sc::pmbus_linear16(raw, mode) == raw * std::pow(2., e));
    }
  }
  for (unsigned mode = 32; mode < 256; ++mode) {
    bool rejected = false;
    try { daphne_sc::pmbus_linear16(0x8000, mode); }
    catch (const std::invalid_argument&) { rejected = true; }
    check(rejected);
  }
  check(daphne_sc::pmbus_linear16(0x8000, 0x17) == 64.);
  check(daphne_sc::pmbus_linear11(0xe7ff) == -0.0625);
  check(daphne_sc::pmbus_linear11(0xe005) == 0.3125);
  std::cout << "All L11/L16 wire values, signs and unsupported VOUT_MODE formats passed\n";
}
