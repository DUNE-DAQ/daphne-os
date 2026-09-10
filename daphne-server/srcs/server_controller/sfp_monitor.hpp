#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/temperature_alarm.hpp"

namespace daphne_sc {
// The only write API is the SFP mux's one-byte route register. EEPROM access
// is a bounded pointer+read; there is no module-control, page, GPIO or reset API.
struct SfpIO {
  std::function<uint8_t()> read_mux;
  std::function<void(uint8_t)> write_mux;
  std::function<std::vector<uint8_t>(uint8_t, uint8_t, size_t)> read_eeprom;
  std::function<uint64_t()> now;
  std::function<void(uint64_t)> wait;
};
const char* sfp_connector(unsigned channel);
daphne::SFPMonitor collect_sfp_port(unsigned channel, const SfpIO& io, const std::string& source);
void evaluate_sfp_temperature_alarm(daphne::SFPMonitor& port, const TemperatureAlarmPolicy& policy, uint64_t now);
void add_sfp_status(daphne::SystemStatusSnapshot& snapshot, const TemperatureAlarmPolicy& policy);
} // namespace daphne_sc
