#include "server_controller/afe_global.hpp"
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("AFE global test failed"); }
struct Fake : Mmio32 {
  uint32_t global = 0, bias = 0;
  uint64_t fail_at = 0;
  std::vector<uint64_t> reads;
  uint32_t read32(uint64_t address) override {
    reads.push_back(address);
    if (address == fail_at) throw std::runtime_error("private injected read failure");
    if (address == kAfeGlobalControlAddress) return global;
    if (address == kBiasEnableAddress) return bias;
    throw std::runtime_error("Unexpected MMIO address");
  }
  void write32(uint64_t, uint32_t) override { throw std::runtime_error("Unexpected write"); }
};
void no_decoded(const daphne::AfeGlobalObservation& r) {
  require(!r.has_power_state_bit() && !r.has_reset_asserted() && !r.has_busy_afe0() &&
      !r.has_busy_afe12() && !r.has_busy_afe34() && !r.has_bias_enabled() && !r.identity_bracket_verified());
}
}

int main() {
  using namespace daphne_sc;
  unsigned cases = 0;
  for (uint32_t abi : {kGatewareAbiV2, kGatewareAbiV21, kGatewareAbiV22})
    for (uint32_t variant : {1, 2}) for (uint32_t word = 0; word < 32; ++word)
      for (uint32_t enable : {0, 1}) {
        Fake io; io.global = word; io.bias = enable;
        uint64_t now = 100;
        auto r = read_afe_global(io, io, {kGatewareIdentityMagic, abi, variant, 0x1234567}, [&] { return now++; });
        require(io.reads == std::vector<uint64_t>{0x80000000, 0x9400000c});
        require(afe_global_consistent(r) && !r.identity_bracket_verified());
        require(r.reset_asserted() == bool(word & 1) && r.power_state_bit() == bool(word & 2));
        require(r.busy_afe0() == bool(word & 4) && r.busy_afe12() == bool(word & 8) && r.busy_afe34() == bool(word & 16));
        require(r.bias_enabled() == bool(enable) && r.global_control_raw() == word && r.bias_enable_raw() == enable);
        daphne::AfeGlobalObservation decoded;
        require(decoded.ParseFromString(r.SerializeAsString()) && afe_global_consistent(decoded));
        // Explicit false/zero values retain presence on the wire.
        require(decoded.has_bias_enabled() && decoded.has_reset_asserted() && decoded.has_global_control_raw());
        decoded.set_busy_afe0(!r.busy_afe0()); require(!afe_global_consistent(decoded));
        invalidate_afe_global(r, daphne::MEASUREMENT_ERROR, "outer bracket failed");
        require(r.has_global_control_raw() && r.global_control_raw() == word && !afe_global_consistent(r));
        no_decoded(r); ++cases;
      }
  const GatewareIdentity good{kGatewareIdentityMagic, kGatewareAbiV2, 1, 0x3f17f1b};
  for (unsigned failure = 0; failure < 6; ++failure) {
    auto id = good;
    if (failure == 0) id.magic = 0;
    if (failure == 1) id.abi = 0x20003;
    if (failure == 2) id.abi = 0x10000;
    if (failure == 3) id.variant = 0;
    if (failure == 4) id.variant = 3;
    if (failure == 5) id.build_id |= 0x10000000;
    Fake io; unsigned clocks = 0;
    auto r = read_afe_global(io, io, id, [&] { ++clocks; return 100; });
    require(!supports_afe_global(id) && io.reads.empty() && clocks == 0);
    require(r.quality() == daphne::MEASUREMENT_UNAVAILABLE && !r.has_global_control_raw()); no_decoded(r);
  }
  for (unsigned bit = 0; bit < 32; ++bit) {
    for (bool bias : {false, true}) {
      if (bit < (bias ? 1U : 5U)) continue;
      Fake io; if (bias) io.bias = 1U << bit; else io.global = 1U << bit;
      auto r = read_afe_global(io, io, good, [] { return 100; });
      require(r.quality() == daphne::MEASUREMENT_ERROR && r.has_global_control_raw() && r.has_bias_enable_raw());
      no_decoded(r);
    }
  }
  for (auto address : {kAfeGlobalControlAddress, kBiasEnableAddress}) {
    Fake io; io.fail_at = address;
    auto r = read_afe_global(io, io, good, [] { return 100; });
    require(r.quality() == daphne::MEASUREMENT_ERROR && !r.has_bias_enable_raw());
    require(r.has_global_control_raw() == (address == kBiasEnableAddress));
    require(r.message().find("private") == std::string::npos); no_decoded(r);
  }
  for (unsigned test = 0; test < 5; ++test) {
    Fake io; unsigned clocks = 0;
    auto r = read_afe_global(io, io, good, [&]() -> uint64_t {
      ++clocks;
      if (test == 0) return 0;
      if (test == 1 && clocks == 2) throw std::runtime_error("clock failure");
      if (clocks == 1) return 100;
      if (test == 2) return 99;
      return 100 + uint64_t(kAfeGlobalMaximumAcquisitionMs) * 1000000 + (test == 4);
    });
    require(r.quality() == (test == 3 ? daphne::MEASUREMENT_GOOD :
        test == 4 ? daphne::MEASUREMENT_STALE : daphne::MEASUREMENT_ERROR));
    if (test == 3) require(afe_global_consistent(r)); else no_decoded(r);
    require(io.reads.size() == (test == 0 ? 0U : 2U));
  }
  std::cout << cases << " mode/ABI/bit combinations, wire presence, admission, reserved bits, read/clock failures and no writes passed\n";
}
