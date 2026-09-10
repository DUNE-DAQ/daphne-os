#pragma once
#include <functional>
#include "server_controller/fpga_health.hpp"
#include "server_controller/runtime_state.hpp"
#include "server_controller/fan_monitor.hpp"

namespace daphne_sc {
// Lazy readers let admission finish before any fabric MMIO is opened, and make
// failure paths testable without touching a board or constructing Daphne.
struct FpgaStatusReaders {
  std::function<daphne::FpgaProgrammingStatus()> programming;
  std::function<GatewareIdentity()> identity;
  std::function<daphne::EndpointStatus()> timing;
  std::function<daphne::NativeTimestampObservation(const GatewareIdentity&)> timestamp;
  std::function<daphne::ProtocolErrorObservation(const GatewareIdentity&)> protocol_errors;
  std::function<daphne::AfeGlobalObservation(const GatewareIdentity&)> afe_global;
  std::function<FanObservations(const GatewareIdentity&)> fans;
};
FpgaStatusReaders default_fpga_status_readers();
bool collect_fpga_status(daphne::SystemStatusSnapshot&, GatewareMode,
    std::optional<GatewareIdentity> admitted, RuntimeState*,
    const FpgaStatusReaders& = default_fpga_status_readers());
}
