#pragma once

#include <functional>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"

namespace daphne_sc {
inline constexpr uint32_t kNativeTimestampAbi = 0x54530100U;
inline constexpr size_t kNativeTimestampWindowLength = 0x2c;
inline constexpr uint32_t kNativeTimestampMaximumAttempts = 3;
inline constexpr uint64_t kNativeTimestampMaximumAcquisitionMs = 100;
using TimestampClock = std::function<uint64_t()>;

// Read-to-capture affects only diagnostic shadow registers. No write32 calls,
// clock controls, spy captures or acquisition changes. Caller must admit/bracket
// the fabric before mapping this window; ABI 2.0/unknown causes ZERO MMIO reads.
daphne::NativeTimestampObservation read_native_timestamp(
    Mmio32&, uint32_t admitted_abi, const TimestampClock& clock);
void invalidate_native_timestamp(daphne::NativeTimestampObservation&,
    daphne::MeasurementQuality, const char* reason);
// Structural consistency only; caller must separately check freshness and the
// completed outer identity/programming bracket before using a health result.
bool native_timestamp_pair_consistent(const daphne::NativeTimestampObservation&) noexcept;
}
