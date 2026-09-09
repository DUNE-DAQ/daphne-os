#pragma once

#include <filesystem>

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {

// Read existing Linux IIO attributes only. No device creation, bus probing,
// writes, guessed channel numbers, or substitution of board-ambient sensors.
void add_ams_temperatures(daphne::SystemStatusSnapshot& status,
                         const std::filesystem::path& root = "/sys/bus/iio/devices");

}  // namespace daphne_sc
