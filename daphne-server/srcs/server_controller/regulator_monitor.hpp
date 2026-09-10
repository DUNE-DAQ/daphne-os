#pragma once

#include <array>
#include <functional>
#include <string>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/temperature_alarm.hpp"

namespace daphne_sc {
struct RegulatorRoute { const char* name; const char* reference; uint8_t address; };
inline constexpr std::array<RegulatorRoute, 4> kRegulatorRoutes{{
    {"+3.3VD", "U39", 0x12}, {"+2.1V analog intermediate", "U42", 0x16},
    {"+3.6V analog intermediate", "U33", 0x32}, {"+1.8VD", "U36", 0x36}}};
inline constexpr uint64_t kRegulatorMaximumAcquisitionNs = 5'000'000'000ULL;

// Read-only interface. Implementations must use SMBus with mandatory PEC and
// hold adapter ownership across this module's bracketed acquisition.
struct RegulatorIO {
  std::function<uint8_t(uint8_t)> read_byte;
  std::function<uint16_t(uint8_t)> read_word;
  std::function<uint64_t()> now;
  std::function<uint64_t()> unix_now;
};
bool regulator_read_allowed(uint8_t command, unsigned width);
daphne::RegulatorMonitor unavailable_regulator(unsigned index, const std::string& reason);
daphne::RegulatorMonitor collect_regulator(unsigned index, const RegulatorIO& io);
void add_regulator_status(daphne::SystemStatusSnapshot& status, const TemperatureAlarmPolicy& policy,
                          bool fabric_access_allowed);
} // namespace daphne_sc
