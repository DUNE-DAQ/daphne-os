#include "server_controller/fpga_status.hpp"
#include "server_controller/readonly_mmio.hpp"
#include "server_controller/timing_status.hpp"
#include "server_controller/board_monitor.hpp"
#include <stdexcept>

namespace daphne_sc {
FpgaStatusReaders default_fpga_status_readers() {
  return {
    [] { return read_fpga_programming_status(); },
    [] { ReadOnlyMmio mmio(kGatewareIdentityMagicAddress, 16); return probe_gateware_identity(mmio); },
    [] { ReadOnlyMmio mmio(kTimingRegisterBase, 16); return read_timing_status(mmio); }
  };
}

bool collect_fpga_status(daphne::SystemStatusSnapshot& status, GatewareMode mode,
    std::optional<GatewareIdentity> admitted, RuntimeState* runtime, const FpgaStatusReaders& read) {
  status.clear_endpoint();
  status.clear_gateware_identity();
  status.clear_fpga_programming();
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
    id->set_acquisition_started_monotonic_ns(monotonic_time_ns());
    auto observe_identity = [&](std::optional<uint32_t> expected) {
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
      validate_runtime_gateware(value, mode, expected, runtime);
      id->set_matches_admitted_profile(true);
      id->set_message("Sampled identity matches admitted ABI/mode/build");
      return value;
    };
    const auto before = observe_identity(admitted ? std::optional<uint32_t>(admitted->build_id) : std::nullopt);
    *endpoint = read.timing();
    if (endpoint->observation_quality() != daphne::MEASUREMENT_GOOD)
      throw std::runtime_error("Timing observation unavailable");
    // Check host programming state before the second MMIO access as well.
    *p = read.programming();
    if (!fpga_status_mmio_prerequisites(*p, monotonic_time_ns()))
      throw std::runtime_error("FPGA programming prerequisites changed or became unavailable during timing observation");
    observe_identity(before.build_id);
    id->set_message("Matching admitted identity samples bracket timing reads; not a hardware latch or protection against external reloads");
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
    endpoint->set_ready(false);
    endpoint->set_message("Timing observation not qualified across FPGA admission checks");
    status.set_message("FPGA status collection failed; inspect programming, identity and timing qualities");
    return false;
  }
}
}
