#pragma once
#include <functional>
#include "server_controller/fpga_health.hpp"
#include "server_controller/runtime_state.hpp"

namespace daphne_sc {
// Lazy readers let admission finish before any fabric MMIO is opened, and make
// failure paths testable without touching a board or constructing Daphne.
struct FpgaStatusReaders {
  std::function<daphne::FpgaProgrammingStatus()> programming;
  std::function<GatewareIdentity()> identity;
  std::function<daphne::EndpointStatus()> timing;
  std::function<daphne::NativeTimestampObservation(const GatewareIdentity&)> timestamp;
};
FpgaStatusReaders default_fpga_status_readers();
bool collect_fpga_status(daphne::SystemStatusSnapshot&, GatewareMode,
    std::optional<GatewareIdentity> admitted, RuntimeState*,
    const FpgaStatusReaders& = default_fpga_status_readers());
}
