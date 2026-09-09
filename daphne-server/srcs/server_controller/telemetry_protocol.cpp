#include "server_controller/telemetry_protocol.hpp"

namespace daphne_sc {
daphne::GeneralInfo make_general_info(const BoardMonitorSnapshot& sample) {
  daphne::GeneralInfo result;
  result.set_v_bias_0(sample.valid_voltage(2));
  result.set_v_bias_1(sample.valid_voltage(3));
  result.set_v_bias_2(sample.valid_voltage(4));
  result.set_v_bias_3(sample.valid_voltage(5));
  result.set_v_bias_4(sample.valid_voltage(6));
  // Preserve the legacy mappings, documenting their actual physical quantities.
  result.set_power_minus5v(sample.valid_voltage(9));
  result.set_power_plus2p5v(sample.valid_voltage(0));
  result.set_power_ce(sample.valid_voltage(7));
  result.set_temperature(kUnavailableVoltage);
  result.set_temperature_quality(daphne::MEASUREMENT_UNAVAILABLE);
  result.set_temperature_detail("No qualified temperature sensor is bound to GeneralInfo.temperature");
  auto* status = result.mutable_board_voltage_status();
  switch (sample.quality) {
    case MonitorQuality::kUnavailable: status->set_quality(daphne::MEASUREMENT_UNAVAILABLE); break;
    case MonitorQuality::kGood: status->set_quality(daphne::MEASUREMENT_GOOD); break;
    case MonitorQuality::kStale: status->set_quality(daphne::MEASUREMENT_STALE); break;
    case MonitorQuality::kError: status->set_quality(daphne::MEASUREMENT_ERROR); break;
  }
  status->set_detail(sample.detail);
  status->set_observed_host_unix_ns(sample.host_unix_ns);
  status->set_observed_monotonic_ns(sample.monotonic_ns);
  const char* names[] = {"3V3PDS", "1V8PDS", "VBIAS0", "VBIAS1", "VBIAS2",
                         "VBIAS3", "VBIAS4", "1V8A", "3V3A", "Minus5VA"};
  for (size_t i = 0; i < sample.volts.size(); ++i) {
    auto* voltage = status->add_named_voltages();
    voltage->set_name(names[i]);
    voltage->set_volts(sample.valid_voltage(i));
    voltage->set_source(std::string("ADS7138 /dev/i2c-1 ") +
                        (i < 7 ? "0x10 channel " : "0x17 channel ") +
                        std::to_string(i < 7 ? i : i - 7));
  }
  return result;
}
}  // namespace daphne_sc
