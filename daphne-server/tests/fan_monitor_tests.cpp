#include "server_controller/fan_monitor.hpp"
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("Fan register test failed"); }
struct Fake : Mmio32 {
  uint32_t pwm = 0, after = 0, tach0 = 0, tach1 = 0;
  unsigned fail_read = 0, writes = 0;
  std::vector<uint64_t> reads;
  uint32_t read32(uint64_t address) override {
    reads.push_back(address);
    if (reads.size() == fail_read) throw std::runtime_error("private injected fault");
    if (address == kFanControlAddress) return reads.size() == 1 ? pwm : after;
    if (address == kFanTach0Address) return tach0;
    if (address == kFanTach1Address) return tach1;
    throw std::runtime_error("Unexpected address");
  }
  void write32(uint64_t, uint32_t) override { ++writes; throw std::runtime_error("Unexpected write"); }
};
void unavailable(const daphne::FanStatus& r) {
  require(!r.has_pwm_command() && !r.has_tach_pulses_capped() && !r.has_tach_at_counter_limit());
  require(!r.has_present() && !r.has_pwm_enabled() && !r.has_duty_cycle_percent() &&
      !r.has_tach_rpm() && !r.tach_valid() && !r.has_running() && !r.has_stalled() &&
      !r.has_stall_count() && !r.has_control_mode() && !r.source_sample_time_known() && !r.identity_bracket_verified());
}
const GatewareIdentity good{kGatewareIdentityMagic, kGatewareAbiV2, 1, 0x3f17f1b};
}

int main() {
  unsigned cases = 0;
  for (auto abi : {kGatewareAbiV2, kGatewareAbiV21, kGatewareAbiV22})
    for (uint32_t variant : {1, 2}) for (uint32_t pwm = 0; pwm < 256; ++pwm)
      for (uint32_t pulses = 0; pulses < 32; ++pulses) {
        Fake io; io.pwm = io.after = pwm; io.tach0 = pulses << 7; io.tach1 = (31 - pulses) << 7;
        uint64_t now = 100;
        auto r = read_fan_registers(io, {kGatewareIdentityMagic, abi, variant, good.build_id}, [&] { return now++; });
        require(fan_observations_consistent(r));
        require(io.reads == std::vector<uint64_t>{0x94000000, 0x94000004, 0x94000008, 0x94000000} && io.writes == 0);
        for (unsigned i = 0; i < 2; ++i) {
          require(fan_registers_consistent(r[i], i) && !r[i].identity_bracket_verified());
          require(r[i].pwm_command() == pwm && r[i].tach_pulses_capped() == (i ? 31 - pulses : pulses));
          require(r[i].tach_at_counter_limit() == (i ? pulses == 0 : pulses == 31));
          daphne::FanStatus decoded;
          require(decoded.ParseFromString(r[i].SerializeAsString()) && fan_registers_consistent(decoded, i));
          require(decoded.has_pwm_command() && decoded.has_tach_at_counter_limit()); // including zero/false
          decoded.set_tach_pulses_capped(32); require(!fan_registers_consistent(decoded, i));
          invalidate_fan_registers(r[i], daphne::MEASUREMENT_ERROR, "outer bracket failed");
          require(r[i].has_tachometer_raw() && r[i].has_pwm_control_raw()); unavailable(r[i]);
        }
        ++cases;
      }
  for (unsigned fault = 0; fault < 6; ++fault) {
    auto id = good;
    if (fault == 0) id.magic = 0;
    if (fault == 1) id.abi = 0x20003;
    if (fault == 2) id.abi = 0x10000;
    if (fault == 3) id.variant = 0;
    if (fault == 4) id.variant = 3;
    if (fault == 5) id.build_id |= 0x10000000;
    Fake io; unsigned clocks = 0;
    auto r = read_fan_registers(io, id, [&] { ++clocks; return 100; });
    require(fan_observations_consistent(r));
    require(!supports_fan_registers(id) && io.reads.empty() && !clocks && !io.writes);
    for (auto& fan : r) { require(fan.quality() == daphne::MEASUREMENT_UNAVAILABLE); unavailable(fan); }
  }
  for (unsigned fault = 1; fault <= 4; ++fault) {
    Fake io; io.fail_read = fault;
    auto r = read_fan_registers(io, good, [] { return 100; });
    require(fan_observations_consistent(r));
    require(io.reads.size() == fault && !io.writes);
    for (unsigned i = 0; i < 2; ++i) {
      require(r[i].quality() == daphne::MEASUREMENT_ERROR && r[i].message().find("private") == std::string::npos);
      require(r[i].has_pwm_control_raw() == (fault > 1) && !r[i].has_pwm_control_after_raw());
      require(r[i].has_tachometer_raw() == (fault > i + 2)); unavailable(r[i]);
    }
  }
  for (unsigned word = 0; word < 4; ++word) for (unsigned bit = 0; bit < 32; ++bit) {
    if ((word == 0 || word == 3) ? bit < 8 : (bit >= 7 && bit <= 11)) continue;
    Fake io;
    if (word == 0) io.pwm = 1U << bit;
    if (word == 1) io.tach0 = 1U << bit;
    if (word == 2) io.tach1 = 1U << bit;
    if (word == 3) io.after = 1U << bit;
    const auto r = read_fan_registers(io, good, [] { return 100; });
    require(fan_observations_consistent(r));
    for (auto& fan : r) { require(fan.quality() == daphne::MEASUREMENT_ERROR); unavailable(fan); }
  }
  for (unsigned fault = 0; fault < 7; ++fault) {
    Fake io; if (fault == 6) io.after = 255;
    unsigned clocks = 0;
    const auto r = read_fan_registers(io, good, [&]() -> uint64_t {
      ++clocks;
      if (fault == 0) return 0;
      if (fault == 1 && clocks == 2) throw std::runtime_error("private clock error");
      if (clocks == 1 || fault == 6) return 100;
      if (fault == 2) return 99;
      return 100 + uint64_t(kFanMaximumAcquisitionMs) * 1000000 + (fault == 4 ? 1 : 0);
    });
    for (unsigned i = 0; i < 2; ++i) {
      const auto expected = fault == 3 || fault == 5 ? daphne::MEASUREMENT_GOOD :
          fault == 4 ? daphne::MEASUREMENT_STALE : daphne::MEASUREMENT_ERROR;
      require(r[i].quality() == expected);
      if (expected == daphne::MEASUREMENT_GOOD) require(fan_registers_consistent(r[i], i)); else unavailable(r[i]);
    }
    require(io.reads.size() == (fault == 0 ? 0U : 4U) && !io.writes);
  }
  // Contract validator must not accept physical health claims or malformed provenance.
  Fake io;
  const auto valid = read_fan_registers(io, good, [] { return 100; });
  for (unsigned fault = 0; fault < 8; ++fault) {
    auto r = valid;
    if (fault == 0) {
      r[1].set_pwm_control_raw(1); r[1].set_pwm_control_after_raw(1); r[1].set_pwm_command(1);
    }
    if (fault == 1) r[1].set_observed_monotonic_ns(101);
    if (fault == 2) r[1].set_acquisition_started_monotonic_ns(99);
    if (fault == 3) r[1].set_quality(daphne::MEASUREMENT_ERROR); // Retained decoded values.
    if (fault == 4) r[1].set_quality(static_cast<daphne::MeasurementQuality>(99));
    if (fault == 5) r[1].set_name("fan0");
    if (fault == 6) r[1].clear_pwm_control_raw();
    if (fault == 7) invalidate_fan_registers(r[1], daphne::MEASUREMENT_ERROR, "mismatched acquisition quality");
    require(!fan_observations_consistent(r));
  }
  for (unsigned fault = 0; fault < 16; ++fault) {
    auto r = valid[0];
    if (fault == 0) r.set_present(false);
    if (fault == 1) r.set_pwm_enabled(false);
    if (fault == 2) r.set_duty_cycle_percent(0);
    if (fault == 3) r.set_tach_rpm(0);
    if (fault == 4) r.set_tach_valid(true);
    if (fault == 5) r.set_running(false);
    if (fault == 6) r.set_stalled(false);
    if (fault == 7) r.set_stall_count(0);
    if (fault == 8) r.set_control_mode("automatic");
    if (fault == 9) r.set_source_sample_time_known(true);
    if (fault == 10) r.set_name("fan1");
    if (fault == 11) r.set_source("cached");
    if (fault == 12) r.set_maximum_acquisition_ms(101);
    if (fault == 13) r.clear_message();
    if (fault == 14) r.clear_tach_at_counter_limit();
    if (fault == 15) r.set_pwm_command(1);
    require(!fan_registers_consistent(r, 0));
  }
  std::cout << cases << " mode/ABI/PWM/tach combinations; wire presence, failure paths and no writes passed\n";
}
