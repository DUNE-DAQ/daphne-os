#include "server_controller/afe_global.hpp"
#include <stdexcept>

namespace daphne_sc {
bool supports_afe_global(const GatewareIdentity& id) noexcept {
  return id.magic == kGatewareIdentityMagic && supports_gateware_abi(id.abi) &&
      (id.variant == 1 || id.variant == 2) && !(id.build_id & kGatewareBuildIdUpperNibbleMask);
}

void invalidate_afe_global(daphne::AfeGlobalObservation& r,
    daphne::MeasurementQuality quality, const char* reason) {
  r.set_quality(quality); r.set_message(reason);
  r.clear_power_state_bit(); r.clear_reset_asserted();
  r.clear_busy_afe0(); r.clear_busy_afe12(); r.clear_busy_afe34(); r.clear_bias_enabled();
  r.set_identity_bracket_verified(false);
}

bool afe_global_consistent(const daphne::AfeGlobalObservation& r) noexcept {
  if (r.quality() != daphne::MEASUREMENT_GOOD || !r.has_global_control_raw() ||
      !r.has_bias_enable_raw() || (r.global_control_raw() & ~31U) || (r.bias_enable_raw() & ~1U) ||
      !r.has_power_state_bit() || !r.has_reset_asserted() || !r.has_busy_afe0() ||
      !r.has_busy_afe12() || !r.has_busy_afe34() || !r.has_bias_enabled() ||
      r.source() != kAfeGlobalSource || r.maximum_acquisition_ms() != kAfeGlobalMaximumAcquisitionMs ||
      !r.acquisition_started_monotonic_ns() || r.observed_monotonic_ns() < r.acquisition_started_monotonic_ns() ||
      r.observed_monotonic_ns() - r.acquisition_started_monotonic_ns() > uint64_t(kAfeGlobalMaximumAcquisitionMs) * 1000000)
    return false;
  const auto raw = r.global_control_raw();
  return r.reset_asserted() == bool(raw & 1) && r.power_state_bit() == bool(raw & 2) &&
      r.busy_afe0() == bool(raw & 4) && r.busy_afe12() == bool(raw & 8) &&
      r.busy_afe34() == bool(raw & 16) && r.bias_enabled() == bool(r.bias_enable_raw() & 1);
}

daphne::AfeGlobalObservation read_afe_global(Mmio32& afe, Mmio32& bias,
    const GatewareIdentity& admitted, const AfeGlobalClock& clock) {
  daphne::AfeGlobalObservation r;
  r.set_source(kAfeGlobalSource);
  r.set_maximum_acquisition_ms(kAfeGlobalMaximumAcquisitionMs);
  if (!supports_afe_global(admitted)) {
    r.set_message("AFE global readback requires admitted ABI 2.0/2.1/2.2 and a known variant; no registers read");
    return r;
  }
  try {
    r.set_acquisition_started_monotonic_ns(clock());
    if (!r.acquisition_started_monotonic_ns()) throw std::runtime_error("Invalid observation clock");
    r.set_global_control_raw(afe.read32(kAfeGlobalControlAddress));
    r.set_bias_enable_raw(bias.read32(kBiasEnableAddress));
    r.set_observed_monotonic_ns(clock());
    if (r.observed_monotonic_ns() < r.acquisition_started_monotonic_ns() ||
        (r.global_control_raw() & ~31U) || (r.bias_enable_raw() & ~1U))
      throw std::runtime_error("Invalid observation clock or reserved register bits");
    if (r.observed_monotonic_ns() - r.acquisition_started_monotonic_ns() > uint64_t(kAfeGlobalMaximumAcquisitionMs) * 1000000) {
      invalidate_afe_global(r, daphne::MEASUREMENT_STALE, "AFE global reads exceeded their host acquisition budget");
      return r;
    }
    const auto raw = r.global_control_raw();
    r.set_reset_asserted(raw & 1); r.set_power_state_bit(raw & 2);
    r.set_busy_afe0(raw & 4); r.set_busy_afe12(raw & 8); r.set_busy_afe34(raw & 16);
    r.set_bias_enabled(r.bias_enable_raw() & 1);
    r.set_quality(daphne::MEASUREMENT_GOOD);
    r.set_message("Sequential FPGA control-register readback, not physical power/bias voltage, cached SC requests or busy history; outer identity bracket required");
    return r;
  } catch (const std::exception&) {
    invalidate_afe_global(r, daphne::MEASUREMENT_ERROR, "AFE global readback failed; raw evidence is not a qualified observation");
    return r;
  }
}
}
