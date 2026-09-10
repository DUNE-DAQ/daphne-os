#include "server_controller/regulator_monitor.hpp"
#include <cmath>
#include <iostream>
#include <map>
#include <stdexcept>
#include <vector>

using namespace daphne_sc;
void check(bool ok) { if (!ok) throw std::runtime_error("Regulator test assertion failed"); }
struct Fake {
  std::map<unsigned, uint16_t> values{{0xd0,0x0056},{0x98,0x11},{0x19,0xb0},{0x20,0x17},
      {0x7e,0},{0x79,0},{0x8b,0x069c},{0x8c,0xe005},{0x8e,35},{0x38,0x886d},
      {0x39,0xe7ff},{0x7a,0},{0x7b,0},{0x7d,0}};
  unsigned calls = 0, fail_at = 0, mutate_at = 0, mutate_command = 0xd0;
  uint16_t mutation = 0;
  uint64_t clock = 1'000'000'000ULL, delay = 100;
  bool rollback = false;
  std::vector<unsigned> commands;
  uint16_t read(uint8_t command, unsigned width) {
    check(regulator_read_allowed(command, width));
    ++calls; commands.push_back(command); clock += delay;
    if (rollback && calls == 10) clock -= 300;
    if (calls == fail_at) throw std::runtime_error("Synthetic PEC failure");
    if (calls == mutate_at) values.at(mutate_command) = mutation;
    return values.at(command);
  }
  daphne::RegulatorMonitor run(unsigned index = 0) {
    return collect_regulator(index, {[&](uint8_t c) { return uint8_t(read(c,8)); },
        [&](uint8_t c) { return read(c,16); }, [&] { return ++clock; }, [] { return 2'000'000'000ULL; }});
  }
};
const daphne::PMBusReadout& field(const daphne::RegulatorMonitor& r, const std::string& name) {
  for (const auto& v : r.registers()) if (v.name() == name) return v;
  throw std::runtime_error("Missing named PMBus read");
}
void good(const daphne::RegulatorMonitor& r) {
  check(r.identity_quality() == daphne::MEASUREMENT_GOOD && r.identity_bracket_verified());
  check(r.pec_required() && r.registers_size() == 21);
  check(r.voltage_quality() == daphne::MEASUREMENT_GOOD && r.has_output_voltage_v());
  check(r.current_quality() == daphne::MEASUREMENT_GOOD && r.has_output_current_a());
  check(r.temperature().valid() && r.temperature().quality() == daphne::MEASUREMENT_GOOD);
  check(r.has_status_changed() && !r.status_changed());
  check(!field(r,"STATUS_MFR_SPECIFIC").has_raw());
  check(field(r,"STATUS_MFR_SPECIFIC").quality() == daphne::MEASUREMENT_UNAVAILABLE);
  check(r.observed_monotonic_ns() > r.acquisition_started_monotonic_ns());
}
int main() {
  for (unsigned i = 0; i < 4; ++i) {
    Fake f; auto r = f.run(i); good(r);
    check(r.address() == kRegulatorRoutes[i].address && r.name() == kRegulatorRoutes[i].name);
    check(r.output_voltage_v() == 3.3046875 && r.output_current_a() == .3125);
    check(r.temperature().temperature_c() == 35. && f.calls == 20);
    check(r.asserted_status_flags_size() == 0);
    daphne::RegulatorMonitor copy; check(copy.ParseFromString(r.SerializeAsString())); good(copy);
  }
  { Fake f; bool failed = false; try { f.run(4); } catch (const std::out_of_range&) { failed = true; }
    check(failed && f.calls == 0); }
  for (unsigned command = 0; command < 256; ++command) {
    const std::vector<unsigned> bytes{0x19,0x20,0x7a,0x7b,0x7d,0x7e,0x98};
    const std::vector<unsigned> words{0x38,0x39,0x79,0x8b,0x8c,0x8e,0xd0};
    auto has = [&](const auto& v) { for (auto x : v) if (x == command) return true; return false; };
    check(regulator_read_allowed(command,8) == has(bytes));
    check(regulator_read_allowed(command,16) == has(words));
    check(!regulator_read_allowed(command,32));
  }
  for (auto bad : std::map<unsigned,uint16_t>{{0xd0,0x005a},{0x98,0x12},{0x19,0x30},{0x20,0x16}}) {
    Fake f; f.values.at(bad.first) = bad.second; const auto r = f.run();
    check(f.calls == 4 && !r.identity_bracket_verified() && !r.has_output_voltage_v());
    check(r.identity_quality() == daphne::MEASUREMENT_ERROR && !r.temperature().valid());
  }
  for (unsigned fail = 1; fail <= 20; ++fail) {
    Fake f; f.fail_at = fail; const auto r = f.run();
    bool raw_failure = false;
    for (const auto& v : r.registers()) if (v.quality() == daphne::MEASUREMENT_ERROR) {
      check(!v.has_raw() && !v.observed_monotonic_ns()); raw_failure = true;
    }
    check(raw_failure);
    if (fail <= 4 || fail >= 17) check(!r.identity_bracket_verified() && !r.has_output_voltage_v() && !r.has_output_current_a());
    else {
      check(r.identity_bracket_verified());
      check(r.has_output_voltage_v() == (fail != 7));
      check(r.has_output_current_a() == (fail != 8));
      check(r.temperature().valid() == (fail != 9));
    }
  }
  for (unsigned command : {0xd0,0x98,0x19,0x20}) {
    Fake f; f.mutate_at = 16; f.mutate_command = command; f.mutation = f.values[command] ^ 1;
    auto r = f.run(); check(!r.identity_bracket_verified() && !r.has_output_voltage_v());
    check(field(r,"READ_VOUT").has_raw() && !r.temperature().valid());
  }
  { Fake f; f.values[0x8b] = 0x8000; auto r = f.run();
    check(r.identity_bracket_verified() && !r.has_output_voltage_v() && r.voltage_quality() == daphne::MEASUREMENT_ERROR);
    check(field(r,"READ_VOUT").raw() == 0x8000); }
  for (uint16_t raw : {0xe7ff,0xe061,0x0005}) {
    Fake f; f.values[0x8c] = raw; const auto r = f.run();
    check(r.identity_bracket_verified() && !r.has_output_current_a() && r.current_quality() == daphne::MEASUREMENT_ERROR);
  }
  { Fake f; f.values[0x8b] = 0; f.values[0x8c] = 0xe000; f.values[0x8e] = 0;
    const auto r = f.run(); good(r); check(r.has_output_voltage_v() && r.output_voltage_v() == 0);
    check(r.has_output_current_a() && r.output_current_a() == 0 && r.temperature().temperature_c() == 0); }
  { Fake f; f.values[0x8e] = 0x07fb; auto r = f.run(); good(r); check(r.temperature().temperature_c() == -5); }
  { Fake f; f.values[0x8e] = 0x8001; const auto r = f.run(); check(!r.temperature().valid() && std::isnan(r.temperature().temperature_c())); }
  { Fake f; f.values[0x7e] = 2; f.values[0x79] = 2; const auto r = f.run(); good(r);
    check(r.asserted_status_flags_size() == 4 && !r.status_changed()); }
  { Fake f; f.mutate_at = 12; f.mutate_command = 0x7e; f.mutation = 0x22;
    const auto r = f.run(); check(r.status_changed() && r.asserted_status_flags_size() == 2); }
  for (auto reg : std::map<unsigned,uint16_t>{{0x79,0xffff},{0x7a,0xff},{0x7b,0xff},{0x7d,0xff},{0x7e,0xff}}) {
    Fake f; f.values.at(reg.first) = reg.second; auto r = f.run(); good(r); check(r.asserted_status_flags_size() > 0);
  }
  for (bool rollback : {false,true}) {
    Fake f; f.rollback = rollback; if (!rollback) f.delay = kRegulatorMaximumAcquisitionNs;
    const auto r = f.run(); check(r.identity_quality() == daphne::MEASUREMENT_STALE);
    check(!r.identity_bracket_verified() && !r.has_output_current_a() && !r.temperature().valid() && f.calls < 20);
  }
  // No PL access is possible through the disabled path, even on an ordinary host.
  daphne::SystemStatusSnapshot unavailable;
  add_regulator_status(unavailable, {}, false);
  check(unavailable.regulators_size() == 4);
  for (const auto& r : unavailable.regulators()) {
    check(r.identity_quality() == daphne::MEASUREMENT_UNAVAILABLE && !r.has_output_voltage_v());
    check(r.temperature().alarm().state() == daphne::TEMPERATURE_ALARM_MISSING);
  }
  Fake f; auto thermal = f.run();
  for (auto sample : std::map<double,daphne::TemperatureAlarmState>{{84,daphne::TEMPERATURE_ALARM_GOOD},
       {85,daphne::TEMPERATURE_ALARM_WARNING},{95,daphne::TEMPERATURE_ALARM_HIGH},{105,daphne::TEMPERATURE_ALARM_CRITICAL}}) {
    thermal.mutable_temperature()->set_temperature_c(sample.first);
    evaluate_temperature_alarm(*thermal.mutable_temperature(), {}, f.clock);
    check(thermal.temperature().alarm().state() == sample.second);
  }
  std::cout << "Regulator identity/PEC allowlist, complete/partial/invalid/stale reads, flags, optional zeros and alarms passed\n";
}
