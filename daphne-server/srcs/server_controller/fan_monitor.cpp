#include "server_controller/fan_monitor.hpp"
#include <stdexcept>

namespace daphne_sc {
bool supports_fan_registers(const GatewareIdentity& id) noexcept {
  return id.magic == kGatewareIdentityMagic && supports_gateware_abi(id.abi) &&
      (id.variant == 1 || id.variant == 2) && !(id.build_id & kGatewareBuildIdUpperNibbleMask);
}

void invalidate_fan_registers(daphne::FanStatus& r, daphne::MeasurementQuality quality, const char* reason) {
  r.set_quality(quality); r.set_message(reason);
  r.clear_pwm_command(); r.clear_tach_pulses_capped(); r.clear_tach_at_counter_limit();
  r.clear_present(); r.clear_pwm_enabled(); r.clear_duty_cycle_percent(); r.clear_tach_rpm();
  r.set_tach_valid(false); r.clear_running(); r.clear_stalled(); r.clear_stall_count(); r.clear_control_mode();
  r.set_source_sample_time_known(false); r.set_identity_bracket_verified(false);
}

FanObservations unavailable_fan_observations() {
  FanObservations result;
  for (unsigned i = 0; i < result.size(); ++i) {
    auto& r = result[i];
    r.set_name(i ? "fan1" : "fan0");
    r.set_source(kFanSource); r.set_maximum_acquisition_ms(kFanMaximumAcquisitionMs);
    r.set_message("Fan MMIO not collected: programming/admission prerequisites required");
  }
  return result;
}

bool fan_registers_consistent(const daphne::FanStatus& r, unsigned index) noexcept {
  if (index > 1 || r.name() != (index ? "fan1" : "fan0") || r.source() != kFanSource ||
      r.quality() != daphne::MEASUREMENT_GOOD || r.maximum_acquisition_ms() != kFanMaximumAcquisitionMs ||
      r.message().empty() || !r.has_pwm_control_raw() || !r.has_pwm_control_after_raw() ||
      !r.has_tachometer_raw() || !r.has_pwm_command() || !r.has_tach_pulses_capped() ||
      !r.has_tach_at_counter_limit() || r.pwm_control_raw() > 255 ||
      r.pwm_control_raw() != r.pwm_control_after_raw() || r.pwm_command() != r.pwm_control_raw() ||
      (r.tachometer_raw() & ~0xF80U) || r.tach_pulses_capped() != (r.tachometer_raw() >> 7) ||
      r.tach_at_counter_limit() != (r.tach_pulses_capped() == 31) ||
      !r.acquisition_started_monotonic_ns() || r.observed_monotonic_ns() < r.acquisition_started_monotonic_ns() ||
      r.observed_monotonic_ns() - r.acquisition_started_monotonic_ns() > uint64_t(kFanMaximumAcquisitionMs) * 1000000)
    return false;
  return !r.has_present() && !r.has_pwm_enabled() && !r.has_duty_cycle_percent() && !r.has_tach_rpm() &&
      !r.tach_valid() && !r.source_sample_time_known() && !r.has_running() && !r.has_stalled() &&
      !r.has_stall_count() && !r.has_control_mode();
}

bool fan_observations_consistent(const FanObservations& fans) noexcept {
  for (unsigned i = 0; i < fans.size(); ++i) {
    const auto& r = fans[i];
    if (r.name() != (i ? "fan1" : "fan0") || r.source() != kFanSource || r.message().empty() ||
        r.maximum_acquisition_ms() != kFanMaximumAcquisitionMs)
      return false;
    if (r.quality() == daphne::MEASUREMENT_GOOD) {
      if (!fan_registers_consistent(r, i)) return false;
    } else {
      if (r.quality() != daphne::MEASUREMENT_UNAVAILABLE && r.quality() != daphne::MEASUREMENT_ERROR &&
          r.quality() != daphne::MEASUREMENT_STALE) return false;
      if (r.has_pwm_command() || r.has_tach_pulses_capped() || r.has_tach_at_counter_limit() ||
          r.has_present() || r.has_pwm_enabled() || r.has_duty_cycle_percent() || r.has_tach_rpm() ||
          r.tach_valid() || r.source_sample_time_known() || r.has_running() || r.has_stalled() ||
          r.has_stall_count() || r.has_control_mode()) return false;
    }
  }
  // One shared four-read acquisition. Equal observations are not a hardware
  // latch: an intervening command change and restoration can escape the bracket.
  const auto& a = fans[0]; const auto& b = fans[1];
  return a.quality() == b.quality() &&
      a.has_pwm_control_raw() == b.has_pwm_control_raw() && a.pwm_control_raw() == b.pwm_control_raw() &&
      a.has_pwm_control_after_raw() == b.has_pwm_control_after_raw() &&
      a.pwm_control_after_raw() == b.pwm_control_after_raw() &&
      a.acquisition_started_monotonic_ns() == b.acquisition_started_monotonic_ns() &&
      a.observed_monotonic_ns() == b.observed_monotonic_ns();
}

FanObservations read_fan_registers(Mmio32& io, const GatewareIdentity& admitted,
    const std::function<uint64_t()>& clock) {
  auto result = unavailable_fan_observations();
  if (!supports_fan_registers(admitted)) return result;
  auto invalidate = [&](daphne::MeasurementQuality quality, const char* reason) {
    for (auto& r : result) invalidate_fan_registers(r, quality, reason);
  };
  try {
    const auto started = clock();
    if (!started) throw std::runtime_error("Invalid observation clock");
    for (auto& r : result) r.set_acquisition_started_monotonic_ns(started);
    const auto before = io.read32(kFanControlAddress);
    for (auto& r : result) r.set_pwm_control_raw(before);
    result[0].set_tachometer_raw(io.read32(kFanTach0Address));
    result[1].set_tachometer_raw(io.read32(kFanTach1Address));
    const auto after = io.read32(kFanControlAddress);
    for (auto& r : result) r.set_pwm_control_after_raw(after);
    const auto observed = clock();
    for (auto& r : result) r.set_observed_monotonic_ns(observed);
    if (observed < started || before > 255 || after > 255 ||
        (result[0].tachometer_raw() & ~0xF80U) || (result[1].tachometer_raw() & ~0xF80U))
      throw std::runtime_error("Invalid clock or fan register encoding");
    if (before != after) {
      invalidate(daphne::MEASUREMENT_ERROR, "Shared fan command changed around sequential tach reads");
    } else if (observed - started > uint64_t(kFanMaximumAcquisitionMs) * 1000000) {
      invalidate(daphne::MEASUREMENT_STALE, "Fan register reads exceeded their host acquisition budget");
    } else {
      for (auto& r : result) {
        r.set_quality(daphne::MEASUREMENT_GOOD); r.set_pwm_command(before);
        r.set_tach_pulses_capped(r.tachometer_raw() >> 7);
        r.set_tach_at_counter_limit(r.tach_pulses_capped() == 31);
        r.set_message("Shared PWM code and capped tach counter readback; no fan presence, physical RPM, stall policy or source sample time; outer identity bracket required");
      }
    }
  } catch (const std::exception&) {
    invalidate(daphne::MEASUREMENT_ERROR, "Fan register readback failed; retained raw words are unqualified evidence");
  }
  return result;
}
} // namespace daphne_sc
