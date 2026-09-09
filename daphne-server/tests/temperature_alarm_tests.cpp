#include <cmath>
#include <iostream>
#include <stdexcept>
#include "server_controller/temperature_alarm.hpp"

void require(bool ok) { if (!ok) throw std::runtime_error("Temperature alarm test failed"); }
int main() {
  using namespace daphne_sc;
  TemperatureAlarmPolicy policy;
  constexpr uint64_t now = 10000000000ULL;
  auto reading = [](double value) {
    daphne::TemperatureStatus t;
    t.set_temperature_c(value);
    t.set_valid(true);
    t.set_quality(daphne::MEASUREMENT_GOOD);
    t.set_observed_monotonic_ns(now - 100);
    t.set_observed_host_unix_ns(1); // Wall time does not participate in age calculations.
    return t;
  };
  auto check = [&](daphne::TemperatureStatus t, daphne::TemperatureAlarmState expected) {
    auto original = t;
    evaluate_temperature_alarm(t, policy, now);
    require(t.alarm().state() == expected);
    require(t.alarm().warning_c() == 85 && t.alarm().high_c() == 95 && t.alarm().critical_c() == 105);
    require(t.alarm().evaluated_monotonic_ns() == now && t.alarm().maximum_age_ms() == 5000);
    require(!t.alarm().message().empty() && !t.alarm().policy_source().empty());
    daphne::TemperatureStatus decoded;
    require(decoded.ParseFromString(t.SerializeAsString()) && decoded.alarm().state() == expected);
    t.clear_alarm();
    require(t.SerializeAsString() == original.SerializeAsString());
    return decoded;
  };
  for (const auto v : {-273.15, -1.0, 0.0, std::nextafter(85.0, 0.0)})
    check(reading(v), daphne::TEMPERATURE_ALARM_GOOD);
  for (const auto v : {85.0, std::nextafter(95.0, 0.0)})
    check(reading(v), daphne::TEMPERATURE_ALARM_WARNING);
  for (const auto v : {95.0, std::nextafter(105.0, 0.0)})
    check(reading(v), daphne::TEMPERATURE_ALARM_HIGH);
  for (const auto v : {105.0, 200.0}) check(reading(v), daphne::TEMPERATURE_ALARM_CRITICAL);
  for (const auto v : {double(NAN), double(INFINITY), -274.0})
    require(!check(reading(v), daphne::TEMPERATURE_ALARM_INVALID).alarm().has_observation_age_ns());
  auto stale = reading(110);
  stale.set_observed_monotonic_ns(now - 5000000000ULL);
  require(check(stale, daphne::TEMPERATURE_ALARM_CRITICAL).alarm().observation_age_ns() == 5000000000ULL);
  stale.set_observed_monotonic_ns(stale.observed_monotonic_ns() - 1);
  check(stale, daphne::TEMPERATURE_ALARM_STALE);
  for (const uint64_t time : {uint64_t(0), now + 1}) {
    auto invalid = reading(20);
    invalid.set_observed_monotonic_ns(time);
    check(invalid, daphne::TEMPERATURE_ALARM_INVALID);
  }
  auto missing = reading(NAN);
  missing.set_valid(false);
  missing.set_quality(daphne::MEASUREMENT_UNAVAILABLE);
  missing.set_observed_monotonic_ns(0);
  missing.set_observed_host_unix_ns(0);
  check(missing, daphne::TEMPERATURE_ALARM_MISSING);
  missing.set_temperature_c(0); // Unavailable zero must not masquerade as a measurement.
  check(missing, daphne::TEMPERATURE_ALARM_INVALID);
  missing.set_temperature_c(NAN);
  missing.set_quality(daphne::MEASUREMENT_ERROR);
  check(missing, daphne::TEMPERATURE_ALARM_INVALID);
  auto invalid = reading(20);
  invalid.set_valid(false);
  check(invalid, daphne::TEMPERATURE_ALARM_INVALID);
  evaluate_temperature_alarm(invalid, policy, 0);
  require(invalid.alarm().state() == daphne::TEMPERATURE_ALARM_INVALID);
  for (int i = 0; i < 7; ++i) {
    auto bad = policy;
    if (i == 0) bad.warning_c = NAN;
    if (i == 1) bad.high_c = INFINITY;
    if (i == 2) bad.high_c = bad.warning_c;
    if (i == 3) bad.critical_c = 1001;
    if (i == 4) bad.warning_c = -274;
    if (i == 5) bad.maximum_age_ms = 0;
    if (i == 6) bad.maximum_age_ms = 60001;
    bool rejected = false;
    try { validate_temperature_alarm_policy(bad); } catch (const std::invalid_argument&) { rejected = true; }
    require(rejected);
  }
  auto custom = reading(50);
  policy = {40, 45, 50, 1};
  evaluate_temperature_alarm(custom, policy, now);
  require(custom.alarm().state() == daphne::TEMPERATURE_ALARM_CRITICAL && custom.alarm().critical_c() == 50);
  custom.set_temperature_c(20);
  evaluate_temperature_alarm(custom, policy, now);
  require(custom.alarm().state() == daphne::TEMPERATURE_ALARM_GOOD); // Deliberately not latched.
  std::cout << "Temperature thresholds, boundaries, missing/invalid/stale, policy and wire checks passed\n";
}
