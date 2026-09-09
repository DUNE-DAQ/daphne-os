#pragma once

#include <cstdint>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
// Provisional commissioning policy, not component ratings or a safety interlock.
struct TemperatureAlarmPolicy {
  double warning_c = 85;
  double high_c = 95;
  double critical_c = 105;
  uint64_t maximum_age_ms = 5000;
};

// Validate before constructing any hardware drivers.
void validate_temperature_alarm_policy(const TemperatureAlarmPolicy& policy);
// Annotates without changing the sensor value, acquisition quality or timestamps.
void evaluate_temperature_alarm(daphne::TemperatureStatus& temperature,
                                const TemperatureAlarmPolicy& policy,
                                uint64_t now_monotonic_ns);
}  // namespace daphne_sc
