#pragma once

#include <array>
#include <functional>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"

namespace daphne_sc {
constexpr uint64_t kFanControlAddress = 0x94000000ULL;
constexpr uint64_t kFanTach0Address = 0x94000004ULL;
constexpr uint64_t kFanTach1Address = 0x94000008ULL;
constexpr uint32_t kFanMaximumAcquisitionMs = 100;
constexpr const char* kFanSource = "FPGA:0x94000000,0x94000004,0x94000008;sequential-read-only";
using FanObservations = std::array<daphne::FanStatus, 2>;

bool supports_fan_registers(const GatewareIdentity&) noexcept;
FanObservations unavailable_fan_observations();
// Establish programming/admission BEFORE mapping; close the complete identity
// bracket afterwards. No read-to-clear registers, PWM writes or I2C operations.
FanObservations read_fan_registers(Mmio32&, const GatewareIdentity&,
    const std::function<uint64_t()>& monotonic_clock);
bool fan_registers_consistent(const daphne::FanStatus&, unsigned index) noexcept;
bool fan_observations_consistent(const FanObservations&) noexcept;
void invalidate_fan_registers(daphne::FanStatus&, daphne::MeasurementQuality, const char* reason);
}
