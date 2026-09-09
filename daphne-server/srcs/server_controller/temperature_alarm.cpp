#include "server_controller/temperature_alarm.hpp"

#include <cmath>
#include <stdexcept>

namespace daphne_sc {
void validate_temperature_alarm_policy(const TemperatureAlarmPolicy& p) {
  if (!std::isfinite(p.warning_c) || !std::isfinite(p.high_c) || !std::isfinite(p.critical_c) ||
      p.warning_c < -273.15 || p.critical_c > 1000 ||
      !(p.warning_c < p.high_c && p.high_c < p.critical_c) ||
      p.maximum_age_ms == 0 || p.maximum_age_ms > 60000)
    throw std::invalid_argument("Temperature policy requires finite -273.15 <= warning < high < critical <= 1000 C "
                                "and maximum age 1..60000 ms; observation only, not an interlock");
}

void evaluate_temperature_alarm(daphne::TemperatureStatus& t, const TemperatureAlarmPolicy& p,
                                uint64_t now) {
  validate_temperature_alarm_policy(p);
  auto* alarm = t.mutable_alarm();
  alarm->Clear();
  alarm->set_warning_c(p.warning_c);
  alarm->set_high_c(p.high_c);
  alarm->set_critical_c(p.critical_c);
  alarm->set_maximum_age_ms(p.maximum_age_ms);
  alarm->set_evaluated_monotonic_ns(now);
  alarm->set_policy_source("Server startup policy; provisional monitoring limits, not safe operating ratings or an interlock");
  auto set = [&](daphne::TemperatureAlarmState state, const char* message) {
    alarm->set_state(state);
    alarm->set_message(message);
  };
  if (t.quality() == daphne::MEASUREMENT_UNAVAILABLE && !t.valid() &&
      std::isnan(t.temperature_c()) && !t.observed_monotonic_ns() && !t.observed_host_unix_ns()) {
    set(daphne::TEMPERATURE_ALARM_MISSING, "Sensor observation unavailable; never treat missing as cool");
    return;
  }
  if (t.quality() != daphne::MEASUREMENT_GOOD || !t.valid() ||
      !std::isfinite(t.temperature_c()) || t.temperature_c() < -273.15 ||
      !now || !t.observed_monotonic_ns() || t.observed_monotonic_ns() > now) {
    set(daphne::TEMPERATURE_ALARM_INVALID, "Invalid sensor value, quality or monotonic observation time");
    return;
  }
  const auto age = now - t.observed_monotonic_ns();
  alarm->set_observation_age_ns(age);
  if (age > p.maximum_age_ms * 1000000ULL)
    set(daphne::TEMPERATURE_ALARM_STALE, "Observation is too old to evaluate temperature severity");
  else if (t.temperature_c() >= p.critical_c)
    set(daphne::TEMPERATURE_ALARM_CRITICAL, "At or above critical monitoring threshold; no automatic control action");
  else if (t.temperature_c() >= p.high_c)
    set(daphne::TEMPERATURE_ALARM_HIGH, "At or above high monitoring threshold; no automatic control action");
  else if (t.temperature_c() >= p.warning_c)
    set(daphne::TEMPERATURE_ALARM_WARNING, "At or above warning monitoring threshold; no automatic control action");
  else
    set(daphne::TEMPERATURE_ALARM_GOOD, "Fresh value below warning threshold; not an overall hardware-health decision");
}
}  // namespace daphne_sc
