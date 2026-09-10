#include "server_controller/fpga_status.hpp"
#include "server_controller/board_monitor.hpp"
#include "server_controller/afe_global.hpp"
#include <iostream>
#include <stdexcept>

namespace {
using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("FPGA status test failed"); }
struct Fixture {
  RuntimeState runtime{"instance", "boot", [] { return ObservationTime{monotonic_time_ns(), 1}; }};
  daphne::SystemStatusSnapshot status;
  GatewareIdentity identity{kGatewareIdentityMagic, kGatewareAbiV2, 1, 0x03f17f1b};
  unsigned programs = 0, ids = 0, timings = 0, timestamps = 0, histories = 0, afes = 0, fans = 0;
  unsigned fail_program = 0, change_id = 0, throw_id = 0, change_abi = 0;
  bool fail_timing = false, unknown_program = false, change_timing = false;
  FpgaStatusReaders readers;
  Fixture() {
    runtime.begin_operation(202, 1, 1);
    runtime.begin_configuration();
    runtime.hardware_started();
    runtime.finish_configuration(true, "fixture", std::string(64, 'a'), true);
    runtime.end_operation();
    readers.programming = [&] {
      ++programs;
      daphne::FpgaProgrammingStatus p;
      if (unknown_program) return p;
      p.set_manager_quality(daphne::MEASUREMENT_GOOD);
      p.set_manager_observed_monotonic_ns(monotonic_time_ns());
      p.set_manager_state(programs == fail_program ? "write" : "operating");
      if (programs == fail_program) return p;
      p.set_configuration_quality(daphne::MEASUREMENT_GOOD);
      p.set_configuration_status_raw(0x16907ffc);
      p.set_configuration_observed_monotonic_ns(monotonic_time_ns());
      return p;
    };
    readers.identity = [&] {
      ++ids;
      if (ids == throw_id) throw std::runtime_error("injected identity read error");
      auto value = identity;
      if (ids == change_id) ++value.build_id;
      if (ids == change_abi) value.abi = identity.abi == kGatewareAbiV2 ? kGatewareAbiV21 : kGatewareAbiV2;
      return value;
    };
    readers.timing = [&] {
      ++timings;
      if (fail_timing) throw std::runtime_error("injected timing read error");
      daphne::EndpointStatus ep;
      ep.set_observation_quality(daphne::MEASUREMENT_GOOD);
      ep.set_observed_monotonic_ns(monotonic_time_ns());
      if (change_timing && timings > 1) ep.set_endpoint_clock_control_raw(4);
      // Local clock, endpoint not ready: collection may still succeed.
      return ep;
    };
    readers.timestamp = [&](const GatewareIdentity& value) {
      ++timestamps;
      require(value.abi == kGatewareAbiV21 || value.abi == kGatewareAbiV22);
      daphne::NativeTimestampObservation observation;
      observation.set_quality(daphne::MEASUREMENT_GOOD);
      auto* sample = observation.add_samples();
      sample->set_quality(daphne::MEASUREMENT_GOOD);
      sample->set_timestamp_ticks(100);
      sample->set_source(daphne::NATIVE_TIMESTAMP_LOCAL_COUNTER);
      return observation; // Tests outer bracketing; raw pair validity has separate tests.
    };
    readers.protocol_errors = [&](const GatewareIdentity& value) {
      ++histories;
      require(value.abi == kGatewareAbiV22);
      daphne::ProtocolErrorObservation observation;
      observation.set_quality(daphne::MEASUREMENT_GOOD);
      observation.set_count(7); observation.set_reasons_seen(1);
      observation.set_saturated(false); observation.set_overflowed(false);
      observation.set_receiver_reset(true);
      auto* attempt = observation.add_attempts();
      attempt->set_quality(daphne::MEASUREMENT_GOOD);
      attempt->set_count_raw(7); attempt->set_detail_raw(129);
      return observation; // Outer checks only; raw contract has dedicated tests.
    };
    readers.afe_global = [&](const GatewareIdentity& value) {
      ++afes; require(same_gateware_identity(value, identity));
      daphne::AfeGlobalObservation r;
      r.set_quality(daphne::MEASUREMENT_GOOD); r.set_global_control_raw(0); r.set_bias_enable_raw(1);
      r.set_power_state_bit(false); r.set_reset_asserted(false);
      r.set_busy_afe0(false); r.set_busy_afe12(false); r.set_busy_afe34(false); r.set_bias_enabled(true);
      r.set_acquisition_started_monotonic_ns(monotonic_time_ns()); r.set_observed_monotonic_ns(monotonic_time_ns());
      r.set_source(kAfeGlobalSource); r.set_maximum_acquisition_ms(kAfeGlobalMaximumAcquisitionMs);
      return r;
    };
    readers.fans = [&](const GatewareIdentity& value) {
      ++fans; require(same_gateware_identity(value, identity));
      struct FanIo : Mmio32 {
        uint32_t read32(uint64_t address) override { return address == kFanControlAddress ? 255 : 128; }
        void write32(uint64_t, uint32_t) override { throw std::runtime_error("Unexpected fan write"); }
      } io;
      return read_fan_registers(io, value, monotonic_time_ns);
    };
  }
  bool collect() {
    return collect_fpga_status(status, static_cast<GatewareMode>(identity.variant), identity, &runtime, readers);
  }
};
}

int main() {
  for (unsigned mode : {1, 2}) for (auto abi : {kGatewareAbiV2, kGatewareAbiV21, kGatewareAbiV22}) {
    Fixture f;
    f.identity.variant = mode;
    f.identity.abi = abi;
    require(f.collect());
    require(f.programs == 2 && f.ids == 2 && f.timings == (abi == kGatewareAbiV2 ? 1 : 2));
    require(f.timestamps == (abi == kGatewareAbiV2 ? 0 : 1));
    require(f.histories == (abi == kGatewareAbiV22 ? 1 : 0));
    require(f.afes == 1 && afe_global_consistent(f.status.afe_global()) && f.status.afe_global().identity_bracket_verified());
    require(f.fans == 1 && f.status.fans_size() == 2);
    for (unsigned i = 0; i < 2; ++i)
      require(fan_registers_consistent(f.status.fans(i), i) && f.status.fans(i).identity_bracket_verified());
    require(f.status.endpoint().live_timestamp().identity_bracket_verified() == (abi != kGatewareAbiV2));
    require(f.status.endpoint().protocol_errors().identity_bracket_verified() == (abi == kGatewareAbiV22));
    require(f.status.endpoint().protocol_errors().has_count() == (abi == kGatewareAbiV22));
    require(!f.status.endpoint().protocol_errors().reset_epoch_known());
    require(f.runtime.snapshot().applied_configuration_valid());
    require(f.status.gateware_identity().matches_admitted_profile());
    require(f.status.gateware_identity().observed_monotonic_ns() >= f.status.endpoint().observed_monotonic_ns());
    require(!f.status.endpoint().ready());
  }
  // ABI 2.2 history must not be accessed before admission, and an outer failure
  // must remove ALL usable fields while retaining evidence already acquired.
  for (unsigned mode : {1, 2}) for (unsigned failure = 0; failure < 10; ++failure) {
    Fixture f; f.identity.variant = mode; f.identity.abi = kGatewareAbiV22;
    if (failure == 0) f.fail_program = 1;
    if (failure == 1) f.fail_program = 2;
    if (failure == 2) f.change_id = 1;
    if (failure == 3) f.change_id = 2;
    if (failure == 4) f.throw_id = 1;
    if (failure == 5) f.throw_id = 2;
    if (failure == 6) f.change_abi = 1;
    if (failure == 7) f.change_abi = 2;
    if (failure == 8) f.change_timing = true;
    if (failure == 9) f.fail_timing = true;
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    const bool collected = failure == 1 || failure == 3 || failure == 5 || failure == 7;
    require(f.histories == unsigned(collected));
    require(f.afes == unsigned(collected));
    require(f.fans == unsigned(collected));
    for (const auto& fan : f.status.fans())
      require(!fan.has_pwm_command() && !fan.has_tach_pulses_capped() && !fan.identity_bracket_verified() &&
          fan.has_tachometer_raw() == collected);
    require(!f.status.afe_global().has_bias_enabled() && !f.status.afe_global().has_power_state_bit() &&
        !f.status.afe_global().identity_bracket_verified());
    require(f.status.afe_global().has_global_control_raw() == collected);
    const auto& r = f.status.endpoint().protocol_errors();
    require(!r.has_count() && !r.has_reasons_seen() && !r.has_saturated() &&
            !r.has_overflowed() && !r.has_receiver_reset() && !r.identity_bracket_verified());
    if (collected) {
      require(r.quality() == daphne::MEASUREMENT_ERROR && r.attempts_size() == 1);
      require(r.attempts(0).quality() == daphne::MEASUREMENT_ERROR && r.attempts(0).count_raw() == 7);
    }
  }
  for (auto abi : {kGatewareAbiV2, kGatewareAbiV21, 0x00020003U}) {
    bool rejected = false;
    auto reader = default_fpga_status_readers();
    try { reader.protocol_errors({kGatewareIdentityMagic, abi, 1, 1}); }
    catch (const std::logic_error&) { rejected = true; }
    require(rejected); // Guard fires before opening /dev/mem, no board required.
  }
  for (unsigned mode : {1, 2}) {
    Fixture f; f.identity.variant = mode; f.identity.abi = kGatewareAbiV22;
    require(!collect_fpga_status(f.status, static_cast<GatewareMode>(mode), std::nullopt, &f.runtime, f.readers));
    require(f.ids == 0 && f.timings == 0 && f.timestamps == 0 && f.histories == 0 && f.afes == 0);
    require(f.runtime.snapshot().applied_configuration_valid());
  }
  for (auto quality : {daphne::MEASUREMENT_UNAVAILABLE, daphne::MEASUREMENT_ERROR, daphne::MEASUREMENT_STALE}) {
    Fixture f; f.identity.abi = kGatewareAbiV22;
    f.readers.protocol_errors = [quality](const GatewareIdentity&) {
      daphne::ProtocolErrorObservation r; r.set_quality(quality); return r;
    };
    require(f.collect() && f.runtime.snapshot().applied_configuration_valid());
    require(f.status.endpoint().protocol_errors().quality() == quality);
    require(f.status.endpoint().protocol_errors().identity_bracket_verified());
    // Timestamp unavailability is independent of valid parser history.
    Fixture g; g.identity.abi = kGatewareAbiV22;
    g.readers.timestamp = [quality](const GatewareIdentity&) {
      daphne::NativeTimestampObservation r; r.set_quality(quality); return r;
    };
    require(g.collect() && g.histories == 1 && !g.status.endpoint().ready());
    require(g.status.endpoint().protocol_errors().has_count() && g.runtime.snapshot().applied_configuration_valid());
  }
  {
    Fixture f; f.identity.abi = kGatewareAbiV22;
    f.readers.protocol_errors = [](const GatewareIdentity&) -> daphne::ProtocolErrorObservation {
      throw std::runtime_error("injected history mapping failure");
    };
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    require(!f.status.endpoint().protocol_errors().identity_bracket_verified());
  }
  {
    Fixture f;
    f.fail_program = 1;
    require(!f.collect() && f.ids == 0 && f.timings == 0);
    require(!f.runtime.snapshot().applied_configuration_valid());
    require(f.status.endpoint().observation_quality() == daphne::MEASUREMENT_UNAVAILABLE);
  }
  {
    Fixture f;
    f.unknown_program = true;
    require(!f.collect() && f.ids == 0 && f.timings == 0);
    require(f.runtime.snapshot().applied_configuration_valid()); // Unknown is not an observed reset.
  }
  {
    Fixture f;
    f.fail_program = 2;
    require(!f.collect() && f.ids == 1 && f.timings == 1);
    require(!f.runtime.snapshot().applied_configuration_valid());
    require(f.status.gateware_identity().quality() == daphne::MEASUREMENT_ERROR);
    require(!f.status.endpoint().ready());
  }
  for (unsigned at : {1, 2}) {
    Fixture f;
    f.change_id = at;
    require(!f.collect() && f.ids == at && !f.runtime.snapshot().applied_configuration_valid());
    require(f.status.gateware_identity().quality() == daphne::MEASUREMENT_GOOD);
    require(f.status.gateware_identity().has_matches_admitted_profile() && !f.status.gateware_identity().matches_admitted_profile());
    require(f.status.endpoint().observation_quality() == daphne::MEASUREMENT_ERROR);
  }
  for (unsigned at : {1, 2}) {
    Fixture f;
    f.throw_id = at;
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    require(f.status.gateware_identity().quality() == daphne::MEASUREMENT_ERROR);
    require(!f.status.gateware_identity().has_matches_admitted_profile());
  }
  {
    Fixture f;
    f.fail_timing = true;
    require(!f.collect() && f.ids == 1 && !f.runtime.snapshot().applied_configuration_valid());
  }
  // This helper is shared with ADS1261 admission; do not require hardware to
  // prove a rejected image invalidates the previous canonical FE evidence.
  for (unsigned at : {1, 2}) {
    Fixture f; f.identity.abi = kGatewareAbiV21; f.change_abi = at;
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    require(!f.status.endpoint().live_timestamp().identity_bracket_verified());
    for (const auto& sample : f.status.endpoint().live_timestamp().samples()) require(!sample.has_timestamp_ticks());
  }
  {
    Fixture f; f.identity.abi = kGatewareAbiV21; f.change_timing = true;
    require(!f.collect() && f.timestamps == 1 && !f.runtime.snapshot().applied_configuration_valid());
    require(!f.status.endpoint().live_timestamp().samples(0).has_timestamp_ticks());
  }
  {
    Fixture f; f.identity.abi = kGatewareAbiV21; f.fail_program = 1;
    require(!f.collect() && f.timestamps == 0 && f.timings == 0);
  }
  {
    Fixture f; f.identity.abi = kGatewareAbiV21;
    require(!collect_fpga_status(f.status, GatewareMode::kSelfTrigger, std::nullopt, &f.runtime, f.readers));
    require(f.ids == 0 && f.timings == 0 && f.timestamps == 0);
    require(f.runtime.snapshot().applied_configuration_valid());
  }
  for (auto quality : {daphne::MEASUREMENT_UNAVAILABLE, daphne::MEASUREMENT_ERROR, daphne::MEASUREMENT_STALE}) {
    Fixture f; f.identity.abi = kGatewareAbiV21;
    f.readers.timestamp = [quality](const GatewareIdentity&) {
      daphne::NativeTimestampObservation live; live.set_quality(quality); return live;
    };
    require(f.collect() && f.runtime.snapshot().applied_configuration_valid());
    require(f.status.endpoint().live_timestamp_quality() == quality);
    require(f.status.endpoint().live_timestamp().identity_bracket_verified());
  }
  {
    Fixture f; f.identity.abi = kGatewareAbiV21;
    f.readers.timestamp = [](const GatewareIdentity&) {
      daphne::NativeTimestampObservation live;
      auto* sample = live.add_samples(); sample->set_quality(daphne::MEASUREMENT_GOOD);
      sample->set_source(daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS); sample->set_timestamp_ticks(10);
      return live;
    };
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    require(!f.status.endpoint().live_timestamp().samples(0).has_timestamp_ticks());
  }
  {
    Fixture f;
    validate_runtime_gateware(f.identity, GatewareMode::kSelfTrigger, f.identity.build_id, &f.runtime);
    require(f.runtime.snapshot().applied_configuration_valid());
    bool rejected = false;
    try { validate_runtime_gateware(f.identity, GatewareMode::kFullStream, f.identity.build_id, &f.runtime); }
    catch (const std::exception&) { rejected = true; }
    require(rejected && !f.runtime.snapshot().applied_configuration_valid());
  }
  for (unsigned failure = 0; failure < 6; ++failure) {
    auto id = Fixture{}.identity;
    if (failure == 0) id.magic = 0;
    if (failure == 1) id.abi = 0x20003;
    if (failure == 2) id.abi = 0x10000;
    if (failure == 3) id.variant = 0;
    if (failure == 4) id.variant = 3;
    if (failure == 5) id.build_id |= 0x10000000;
    bool rejected = false;
    try { default_fpga_status_readers().afe_global(id); }
    catch (const std::logic_error&) { rejected = true; }
    require(rejected); // Invalid identity rejected before opening /dev/mem.
    rejected = false;
    try { default_fpga_status_readers().fans(id); }
    catch (const std::logic_error&) { rejected = true; }
    require(rejected);
  }
  {
    Fixture f; require(f.collect());
    f.unknown_program = true;
    require(!f.collect() && !f.status.afe_global().has_global_control_raw() && !f.status.afe_global().has_bias_enabled());
    require(f.afes == 1); // Reusing a snapshot cannot retain the previous successful observation.
    require(f.fans == 1 && f.status.fans_size() == 2);
    for (const auto& fan : f.status.fans())
      require(!fan.has_tachometer_raw() && !fan.has_pwm_command() && !fan.identity_bracket_verified());
  }
  for (unsigned failure = 0; failure < 2; ++failure) {
    Fixture f;
    if (failure == 0) f.readers.afe_global = [](const GatewareIdentity&) -> daphne::AfeGlobalObservation {
      throw std::runtime_error("mapping failed");
    };
    else {
      auto original = f.readers.afe_global;
      f.readers.afe_global = [original](const GatewareIdentity& id) {
        auto r = original(id); r.set_bias_enabled(false); return r;
      };
    }
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    require(!f.status.afe_global().has_bias_enabled() && !f.status.afe_global().identity_bracket_verified());
  }
  for (auto quality : {daphne::MEASUREMENT_UNAVAILABLE, daphne::MEASUREMENT_ERROR, daphne::MEASUREMENT_STALE}) {
    Fixture f;
    f.readers.afe_global = [quality](const GatewareIdentity&) {
      daphne::AfeGlobalObservation r; r.set_quality(quality); return r;
    };
    require(f.collect() && f.runtime.snapshot().applied_configuration_valid());
    require(f.status.afe_global().quality() == quality && !f.status.afe_global().has_bias_enabled());
    require(f.status.afe_global().identity_bracket_verified());
    // A completed identity bracket is not a guarantee that every diagnostic succeeded.
  }
  for (unsigned fault = 0; fault < 7; ++fault) {
    Fixture f;
    auto original = f.readers.fans;
    f.readers.fans = [original, fault](const GatewareIdentity& id) {
      if (fault == 0) throw std::runtime_error("fan mapping failed");
      auto fans = original(id);
      if (fault == 1) fans[0].set_tach_pulses_capped(2);
      if (fault == 2) fans[1].set_present(false);
      if (fault == 3) { fans[1].set_pwm_control_raw(1); fans[1].set_pwm_control_after_raw(1); fans[1].set_pwm_command(1); }
      if (fault == 4) fans[1].set_observed_monotonic_ns(fans[1].observed_monotonic_ns() + 1);
      if (fault == 5) fans[1].set_quality(daphne::MEASUREMENT_ERROR); // Must clear decoded values.
      if (fault == 6) fans[1].set_quality(static_cast<daphne::MeasurementQuality>(99));
      return fans;
    };
    require(!f.collect() && !f.runtime.snapshot().applied_configuration_valid());
    for (const auto& fan : f.status.fans())
      require(!fan.has_pwm_command() && !fan.has_tach_pulses_capped() && !fan.has_present() && !fan.identity_bracket_verified());
  }
  for (auto quality : {daphne::MEASUREMENT_UNAVAILABLE, daphne::MEASUREMENT_ERROR, daphne::MEASUREMENT_STALE}) {
    Fixture f;
    f.readers.fans = [quality](const GatewareIdentity&) {
      auto result = unavailable_fan_observations();
      for (auto& fan : result) fan.set_quality(quality);
      return result;
    };
    require(f.collect() && f.runtime.snapshot().applied_configuration_valid());
    for (const auto& fan : f.status.fans())
      require(fan.quality() == quality && !fan.has_pwm_command() && fan.identity_bracket_verified());
  }
  std::cout << "Both ABI variants, lazy admission, before/after failures, known invalidation, fan reads and ADC-shared guard passed\n";
}
