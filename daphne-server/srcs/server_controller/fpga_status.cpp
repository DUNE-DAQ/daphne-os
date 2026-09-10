#include "server_controller/fpga_status.hpp"
#include "server_controller/readonly_mmio.hpp"
#include "server_controller/timing_status.hpp"
#include "server_controller/board_monitor.hpp"
#include "server_controller/native_timestamp.hpp"
#include "server_controller/protocol_errors.hpp"
#include "server_controller/afe_global.hpp"
#include <stdexcept>

namespace daphne_sc {
FpgaStatusReaders default_fpga_status_readers() {
  return {
    [] { return read_fpga_programming_status(); },
    [] { ReadOnlyMmio mmio(kGatewareIdentityMagicAddress, 16); return probe_gateware_identity(mmio); },
    [] { ReadOnlyMmio mmio(kTimingRegisterBase, 16); return read_timing_status(mmio); },
    [](const GatewareIdentity& admitted) {
      if (!supports_live_timestamp(admitted.abi))
        throw std::logic_error("Snapshot mapping requested without ABI 2.1/2.2 admission");
      ReadOnlyMmio mmio(kTimingRegisterBase, kNativeTimestampWindowLength);
      return read_native_timestamp(mmio, admitted.abi, monotonic_time_ns);
    },
    [](const GatewareIdentity& admitted) {
      if (!supports_protocol_error_history(admitted.abi))
        throw std::logic_error("Parser-history mapping requested without exact ABI 2.2 admission");
      ReadOnlyMmio mmio(kTimingRegisterBase, kProtocolErrorWindowLength);
      return read_protocol_error_history(mmio, admitted.abi, monotonic_time_ns);
    },
    [](const GatewareIdentity& admitted) {
      if (!supports_afe_global(admitted))
        throw std::logic_error("AFE global mapping requested without supported identity admission");
      ReadOnlyMmio afe(kAfeGlobalControlAddress, 4);
      ReadOnlyMmio bias(kBiasEnableAddress, 4);
      return read_afe_global(afe, bias, admitted, monotonic_time_ns);
    }
  };
}

bool collect_fpga_status(daphne::SystemStatusSnapshot& status, GatewareMode mode,
    std::optional<GatewareIdentity> admitted, RuntimeState* runtime, const FpgaStatusReaders& read) {
  status.clear_endpoint();
  status.clear_gateware_identity();
  status.clear_fpga_programming();
  status.clear_afe_global();
  status.mutable_afe_global()->set_message("AFE global MMIO not collected: programming/admission prerequisites required");
  auto* id = status.mutable_gateware_identity();
  auto* endpoint = status.mutable_endpoint();
  bool mmio_started = false;
  try {
    auto* p = status.mutable_fpga_programming();
    *p = read.programming();
    const auto now = monotonic_time_ns();
    if (!fpga_status_mmio_prerequisites(*p, now)) {
      if (runtime && fpga_programming_known_bad(*p, now))
        runtime->invalidate("Observed FPGA programming/startup state is not usable");
      status.set_message("FPGA status MMIO skipped: fresh operating/startup/error prerequisites were not established");
      endpoint->set_message(status.message());
      id->set_message(status.message());
      return false;
    }
    if (!admitted) {
      status.set_message("FPGA status MMIO skipped: no process-admitted image identity");
      endpoint->set_message(status.message());
      id->set_message(status.message());
      return false;
    }
    id->set_acquisition_started_monotonic_ns(monotonic_time_ns());
    auto observe_identity = [&](std::optional<GatewareIdentity> expected) {
      mmio_started = true;
      const auto value = read.identity();
      id->set_magic(value.magic);
      id->set_abi(value.abi);
      id->set_variant(value.variant);
      id->set_build_id(value.build_id);
      id->set_quality(daphne::MEASUREMENT_GOOD);
      id->set_observed_monotonic_ns(monotonic_time_ns());
      id->set_matches_admitted_profile(false);
      id->set_message("Sampled identity does not match admitted ABI/mode/build");
      validate_runtime_gateware(value, mode, expected ? std::optional<uint32_t>(expected->build_id) : std::nullopt, runtime);
      if (expected && !same_gateware_identity(value, *expected)) {
        if (runtime) runtime->invalidate("Observed complete FPGA identity changed from admission");
        throw std::runtime_error("Complete gateware identity mismatch");
      }
      id->set_matches_admitted_profile(true);
      id->set_message("Sampled identity matches admitted ABI/mode/build");
      return value;
    };
    const auto before = observe_identity(admitted);
    *endpoint = read.timing();
    if (endpoint->observation_quality() != daphne::MEASUREMENT_GOOD)
      throw std::runtime_error("Timing observation unavailable");
    if (supports_live_timestamp(before.abi)) {
      *endpoint->mutable_live_timestamp() = read.timestamp(before);
      const auto after_timing = read.timing();
      if (after_timing.observation_quality() != daphne::MEASUREMENT_GOOD ||
          after_timing.endpoint_clock_control_raw() != endpoint->endpoint_clock_control_raw() ||
          after_timing.endpoint_clock_status_raw() != endpoint->endpoint_clock_status_raw() ||
          after_timing.endpoint_control_raw() != endpoint->endpoint_control_raw() ||
          after_timing.endpoint_status_raw() != endpoint->endpoint_status_raw())
        throw std::runtime_error("Timing context changed around native timestamp reads");
      for (const auto& sample : endpoint->live_timestamp().samples()) {
        if (sample.quality() == daphne::MEASUREMENT_GOOD &&
            sample.source() != (endpoint->endpoint_clock_selected() ?
                daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS : daphne::NATIVE_TIMESTAMP_LOCAL_COUNTER))
          throw std::runtime_error("Native timestamp source disagrees with bracketed timing controls");
      }
      endpoint->set_live_timestamp_quality(endpoint->live_timestamp().quality());
    } else {
      endpoint->mutable_live_timestamp()->set_message(
          "Platform ABI 2.0 has no native timestamp snapshot; extension addresses were not accessed");
    }
    if (supports_protocol_error_history(before.abi)) {
      *endpoint->mutable_protocol_errors() = read.protocol_errors(before);
    } else {
      endpoint->mutable_protocol_errors()->set_message(
          "Parser history requires exact platform ABI 2.2; diagnostic addresses were not accessed");
    }
    *status.mutable_afe_global() = read.afe_global(before);
    if (status.afe_global().quality() == daphne::MEASUREMENT_GOOD &&
        !afe_global_consistent(status.afe_global()))
      throw std::runtime_error("Inconsistent AFE global observation");
    // Recheck host programming state before closing the MMIO identity bracket.
    *p = read.programming();
    if (!fpga_status_mmio_prerequisites(*p, monotonic_time_ns()))
      throw std::runtime_error("FPGA programming prerequisites changed or became unavailable during timing observation");
    observe_identity(before);
    status.mutable_afe_global()->set_identity_bracket_verified(true);
    if (supports_live_timestamp(before.abi)) endpoint->mutable_live_timestamp()->set_identity_bracket_verified(true);
    if (supports_protocol_error_history(before.abi)) endpoint->mutable_protocol_errors()->set_identity_bracket_verified(true);
    id->set_message("Matching complete admitted identity samples bracket timing/native diagnostics and AFE global reads; not a hardware latch or protection against identical reloads");
    return true;
  } catch (const std::exception&) {
    if (mmio_started && runtime) runtime->invalidate("FPGA status could not confirm a stable admitted fabric observation");
    // Retain a positively observed profile mismatch as a failed health check.
    // Otherwise partial identity data must not look like a completed bracket.
    if (!id->has_matches_admitted_profile() || id->matches_admitted_profile()) {
      id->set_quality(daphne::MEASUREMENT_ERROR);
      id->clear_matches_admitted_profile();
      id->set_message("Stable admitted identity observation was not completed");
    }
    endpoint->set_observation_quality(daphne::MEASUREMENT_ERROR);
    invalidate_afe_global(*status.mutable_afe_global(), daphne::MEASUREMENT_ERROR,
        "AFE global readback not qualified across FPGA admission/programming checks");
    if (endpoint->has_live_timestamp()) {
      invalidate_native_timestamp(*endpoint->mutable_live_timestamp(), daphne::MEASUREMENT_ERROR,
          "Native timestamp not qualified across FPGA admission/programming/timing checks");
      endpoint->set_live_timestamp_quality(daphne::MEASUREMENT_ERROR);
    }
    if (endpoint->has_protocol_errors()) {
      invalidate_protocol_error_history(*endpoint->mutable_protocol_errors(), daphne::MEASUREMENT_ERROR,
          "Parser history not qualified across FPGA admission/programming checks");
    }
    endpoint->set_ready(false);
    endpoint->set_message("Timing observation not qualified across FPGA admission checks");
    status.set_message("FPGA status collection failed; inspect programming, identity and timing qualities");
    return false;
  }
}
}
