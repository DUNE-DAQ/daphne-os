#pragma once

#include <filesystem>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
// UG570 STAT, NOT the PCAP status word used by the driver's .state callback.
inline constexpr uint32_t kFpgaConfigurationErrorMask =
    (1u << 29) | (1u << 27) | (1u << 22) | (1u << 17) |
    (1u << 16) | (1u << 15) | 1u;
inline constexpr uint32_t kFpgaStartupRequiredMask =
    (1u << 14) | (1u << 13) | (1u << 12) | (1u << 11) |
    (1u << 7) | (1u << 6) | (1u << 5) | (1u << 4);
inline constexpr uint64_t kFpgaHealthMaximumAgeMs = 5000;

daphne::FpgaProgrammingStatus read_fpga_programming_status(
    const std::filesystem::path& root = "/sys/class/fpga_manager");
// Conservative prerequisite for the status collector's MMIO reads only.
// Not a lock against external reprogramming or a general hardware-access guard.
bool fpga_status_mmio_prerequisites(const daphne::FpgaProgrammingStatus&, uint64_t now);
bool fpga_programming_known_bad(const daphne::FpgaProgrammingStatus&, uint64_t now);
daphne::FpgaHealthAssessment assess_fpga_health(
    const daphne::SystemStatusSnapshot&,
    const daphne::ManagementNetworkObservation&, uint64_t now);
}
