#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include "ADS1261.hpp"

using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("ADS1261 test failed"); }
template <typename F> void rejects(F f) {
  bool rejected = false;
  try { f(); } catch (const std::exception&) { rejected = true; }
  require(rejected);
}
struct Model {
  std::array<uint8_t, 19> reg{};
  std::vector<std::vector<uint8_t>> calls;
  uint64_t now = 1000000000, ready_at = 0;
  uint32_t code = 0xffffff;
  uint8_t conversion_status = 4;
  bool never_ready = false, bad_echo = false, bad_crc = false, short_read = false;
  Model() { reset(); }
  void reset() { reg.fill(0); reg[0] = 0x80; reg[1] = 1; reg[2] = 0x24; reg[3] = 1;
                 reg[6] = 5; reg[12] = 0x40; reg[13] = 0xff; reg[17] = 0xff; ready_at = 0; }
  std::vector<uint8_t> transfer(const std::vector<uint8_t>& tx) {
    calls.push_back(tx);
    require(tx.size() >= 2);
    const bool crc = reg[5] & 0x20;
    const size_t data = crc ? 4 : 2;
    std::vector<uint8_t> rx(tx.size(), 0xff);
    rx[1] = tx[0];
    if (crc) {
      require(tx.size() >= 4 && tx[2] == ads1261_crc({tx[0], tx[1]}) && tx[3] == 0);
      rx[2] = tx[1]; rx[3] = tx[2];
    }
    if (tx[0] == 0x06) reset();
    else if (tx[0] == 0x08) { ready_at = now + 3000000; reg[1] &= ~4; }
    else if (tx[0] == 0x12) {
      require(crc && tx.size() == 9 && ready_at && now >= ready_at);
      rx[4] = conversion_status;
      rx[5] = code >> 16; rx[6] = code >> 8; rx[7] = code;
      rx[8] = ads1261_crc({rx[4], rx[5], rx[6], rx[7]});
      ready_at = 0; reg[1] &= ~4;
    } else if ((tx[0] & 0xe0) == 0x20) {
      const auto address = tx[0] & 0x1f;
      require(address < reg.size() && tx.size() > data);
      if (address == 1 && ready_at && now >= ready_at && !never_ready) reg[1] |= 4;
      rx[data] = reg[address];
      if (crc) rx[data + 1] = ads1261_crc({reg[address]});
    } else if ((tx[0] & 0xe0) == 0x40) {
      require((tx[0] & 0x1f) < reg.size());
      reg[tx[0] & 0x1f] = tx[1];
    } else throw std::runtime_error("Unexpected ADC command");
    if (bad_echo) rx[1] ^= 1;
    if (bad_crc && crc) rx.back() ^= 1;
    if (short_read) rx.pop_back();
    return rx;
  }
  ADS1261 adc() { return ADS1261([&](const auto& tx) { return transfer(tx); },
                                [&] { return now; }, [&](uint64_t ns) { now += ns; }); }
};
int main() {
  // CRC-8/I-432-1 polynomial with init=FF, no final XOR (ADS1261 variant).
  require(ads1261_crc({}) == 0xff);
  require(ads1261_crc({0xff}) == 0);
  require(ads1261_crc({0xff, 0x01}) == 0x07);
  for (unsigned i = 0; i < 5; ++i) require(ads1261_afe_mux(i) == 0x21 + 0x22 * i);
  rejects([] { ads1261_afe_mux(5); });
  require(ads1261_signed_code(0) == 0 && ads1261_signed_code(0xffffff) == -1);
  require(ads1261_signed_code(0x800000) == -8388608 && ads1261_signed_code(0x7fffff) == 8388607);
  rejects([] { ads1261_signed_code(0x1000000); });
  for (bool crc : {false, true}) {
    Model m;
    m.reg[5] = crc ? 0x60 : 0;
    auto adc = m.adc();
    require(m.calls.empty()); // No initialization writes in constructor.
    const auto before = m.reg;
    require(adc.probe() == 0x80 && adc.crc_enabled() == crc && m.reg == before);
    require(m.calls.size() == 1 && m.calls[0][0] == 0x20);
    adc.initialize();
    require(adc.crc_enabled() && m.reg[6] == 0x10 && m.reg[16] == 0x80 && m.reg[3] == 0x11);
    for (unsigned afe = 0; afe < 5; ++afe) {
      const auto result = adc.convert(afe);
      require(result.id == 0x80 && result.input_mux == ads1261_afe_mux(afe) && result.status == 4);
      require(result.raw_code == -1 && !result.saturated && result.observed_monotonic_ns > 0);
      require(std::abs(result.differential_volts + 2.5 / 8388608) < 1e-15);
    }
    for (auto code : {0u, 0x7fffffu, 0x800000u}) {
      m.code = code;
      const auto result = adc.convert(0);
      require(result.saturated == (code != 0));
    }
    m.reg[12] ^= 1;
    rejects([&] { adc.convert(0); }); // Calibration register changed.
  }
  for (unsigned fault = 0; fault < 6; ++fault) {
    Model m;
    auto adc = m.adc();
    if (fault == 0) { m.reg[0] = 0xa0; rejects([&] { adc.initialize(); });
      require(m.calls.size() == 1); continue; }
    adc.initialize();
    if (fault == 1) m.bad_echo = true;
    if (fault == 2) m.bad_crc = true;
    if (fault == 3) m.short_read = true;
    if (fault == 4) m.never_ready = true;
    if (fault == 5) m.reg[1] = 1;
    rejects([&] { adc.convert(0); });
    require(m.now < 1200000000); // Bounded polling even when no conversion appears.
  }
  Model fault_status;
  auto adc = fault_status.adc();
  adc.initialize();
  fault_status.conversion_status = 0x3c;
  require(adc.convert(0).status == 0x3c); // Preserve faults for protocol quality, never discard them.
  std::cout << "ADS1261 identity/framing, CRC, setup, mux, signed/scaled data, saturation, fault and timeout tests passed\n";
}
