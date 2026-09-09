#pragma once

#include <filesystem>
#include <string>

// Schematic 177020, sheets 6/13: ADS7138 and MCP9808 use PS I2C1 on
// MIO24/25. Linux adapter numbers are NOT hardware controller identities.
std::string board_ps_i2c_adapter(
    const std::filesystem::path& devices = "/sys/bus/i2c/devices",
    const std::filesystem::path& dev = "/dev");
