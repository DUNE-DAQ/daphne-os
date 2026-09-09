#pragma once
#include <filesystem>
#include <string>

// Resolve the carrier current ADC by OF controller identity + chip select, never
// by dynamic spi bus number. Device identity is separately checked by ADS1261.
std::string board_current_spi_device(
    const std::filesystem::path& devices = "/sys/bus/spi/devices",
    const std::filesystem::path& dev = "/dev");
