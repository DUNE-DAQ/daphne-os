#pragma once

#include <functional>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"

namespace daphne_sc {
constexpr uint64_t kAfeGlobalControlAddress = 0x80000000ULL;
constexpr uint64_t kBiasEnableAddress = 0x9400000CULL;
constexpr uint32_t kAfeGlobalMaximumAcquisitionMs = 100;
constexpr const char* kAfeGlobalSource = "FPGA:0x80000000,0x9400000C;sequential-read-only";
using AfeGlobalClock = std::function<uint64_t()>;

bool supports_afe_global(const GatewareIdentity&) noexcept;
// Caller must establish programming/admission prerequisites BEFORE mapping
// either address, then bracket this observation with matching identities.
daphne::AfeGlobalObservation read_afe_global(Mmio32& afe, Mmio32& bias,
    const GatewareIdentity& admitted, const AfeGlobalClock& clock);
bool afe_global_consistent(const daphne::AfeGlobalObservation&) noexcept;
void invalidate_afe_global(daphne::AfeGlobalObservation&,
    daphne::MeasurementQuality, const char* reason);
}
