#include "server_controller/fpga_status.hpp"
#include "server_controller/board_monitor.hpp"
#include <iostream>
#include <stdexcept>

namespace {
using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("FPGA status test failed"); }
struct Fixture {
  RuntimeState runtime{"instance", "boot", [] { return ObservationTime{monotonic_time_ns(), 1}; }};
  daphne::SystemStatusSnapshot status;
  GatewareIdentity identity{kGatewareIdentityMagic, kGatewareAbiV2, 1, 0x03f17f1b};
  unsigned programs = 0, ids = 0, timings = 0;
  unsigned fail_program = 0, change_id = 0, throw_id = 0;
  bool fail_timing = false, unknown_program = false;
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
      return value;
    };
    readers.timing = [&] {
      ++timings;
      if (fail_timing) throw std::runtime_error("injected timing read error");
      daphne::EndpointStatus ep;
      ep.set_observation_quality(daphne::MEASUREMENT_GOOD);
      ep.set_observed_monotonic_ns(monotonic_time_ns());
      // Local clock, endpoint not ready: collection may still succeed.
      return ep;
    };
  }
  bool collect() {
    return collect_fpga_status(status, static_cast<GatewareMode>(identity.variant), identity, &runtime, readers);
  }
};
}

int main() {
  for (unsigned mode : {1, 2}) {
    Fixture f;
    f.identity.variant = mode;
    require(f.collect());
    require(f.programs == 2 && f.ids == 2 && f.timings == 1);
    require(f.runtime.snapshot().applied_configuration_valid());
    require(f.status.gateware_identity().matches_admitted_profile());
    require(f.status.gateware_identity().observed_monotonic_ns() >= f.status.endpoint().observed_monotonic_ns());
    require(!f.status.endpoint().ready());
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
  {
    Fixture f;
    validate_runtime_gateware(f.identity, GatewareMode::kSelfTrigger, f.identity.build_id, &f.runtime);
    require(f.runtime.snapshot().applied_configuration_valid());
    bool rejected = false;
    try { validate_runtime_gateware(f.identity, GatewareMode::kFullStream, f.identity.build_id, &f.runtime); }
    catch (const std::exception&) { rejected = true; }
    require(rejected && !f.runtime.snapshot().applied_configuration_valid());
  }
  std::cout << "Both ABI variants, lazy admission, before/after failures, known invalidation and ADC-shared guard passed\n";
}
