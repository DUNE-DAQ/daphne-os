#pragma once

#include <array>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"

namespace daphne_sc {
constexpr uint64_t kTimingRegisterBase = 0x84000000ULL;
daphne::EndpointStatus read_timing_status(Mmio32& mmio);
void add_register_capabilities(daphne::SystemStatusSnapshot& status, GatewareMode mode,
                              std::optional<uint32_t> admitted_abi = std::nullopt);
}
