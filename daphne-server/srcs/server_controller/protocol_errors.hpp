#pragma once
#include <functional>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"

namespace daphne_sc {
inline constexpr uint32_t kProtocolErrorAbi = 0x50450100U;
inline constexpr size_t kProtocolErrorWindowLength = 0x4c;
inline constexpr uint32_t kProtocolErrorMaximumAttempts = 3;
inline constexpr uint64_t kProtocolErrorMaximumAcquisitionMs = 100;
using ProtocolErrorClock = std::function<uint64_t()>;

// Caller must perform exact admission and bracket MMIO with programming/identity
// checks. Only ABI 2.2 may probe this window; all other ABIs perform ZERO reads.
// Read-to-capture touches diagnostic shadows only. No hardware writes or clears.
daphne::ProtocolErrorObservation read_protocol_error_history(
    Mmio32&, uint32_t admitted_abi, const ProtocolErrorClock&);
void invalidate_protocol_error_history(daphne::ProtocolErrorObservation&,
    daphne::MeasurementQuality, const char* reason);
// Structural consistency only; caller also checks identity bracket/freshness.
bool protocol_error_history_consistent(const daphne::ProtocolErrorObservation&) noexcept;
}
