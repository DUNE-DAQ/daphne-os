#pragma once
#include "daphneV3_low_level_confs.pb.h"
#include "server_controller/gateware.hpp"
#include "server_controller/current_mux.hpp"

namespace daphne_sc {
class RuntimeState;
CurrentChannelSelection current_request_selection(const daphne::cmd_readCurrentMonitor& request);
// Explicit measurement operation: ADC configuration + temporary carrier mux
// writes, never a bus scan or power/BIAS operation. The request must identify
// a physical channel; legacy ADC-input requests are rejected before hardware.
daphne::cmd_readCurrentMonitor_response read_current_monitor(
    const daphne::cmd_readCurrentMonitor& request, GatewareMode mode,
    std::optional<GatewareIdentity> admitted_identity, bool mezzanines_enabled,
    RuntimeState* runtime = nullptr);
void set_current_sample(daphne::cmd_readCurrentMonitor_response& response,
                        const struct ADS1261Sample& sample);
}  // namespace daphne_sc
