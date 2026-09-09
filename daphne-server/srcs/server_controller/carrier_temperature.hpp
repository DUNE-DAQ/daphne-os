#pragma once

#include <stdexcept>

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
// Reader returns a 16-bit, host-order MCP9808 register. Register-pointer
// transactions only: never write configuration, limits, resolution or alerts.
template <typename Reader>
double read_mcp9808_celsius(Reader read_word) {
  if (read_word(6) != 0x0054 || (read_word(7) >> 8) != 0x04)
    throw std::runtime_error("MCP9808 manufacturer/device identity mismatch");
  if (read_word(1) & 0x0100)
    throw std::runtime_error("MCP9808 is shut down; retained sample is not a fresh measurement");
  const auto raw = read_word(5);
  // Bits 15..13 are comparator flags, not temperature or health thresholds.
  const int code = (raw & 0x0fff) - ((raw & 0x1000) ? 4096 : 0);
  return code / 16.0;
}

daphne::TemperatureStatus read_carrier_temperature();
void set_general_info_temperature(daphne::GeneralInfo& info,
                                  const daphne::TemperatureStatus& temperature);
}  // namespace daphne_sc
