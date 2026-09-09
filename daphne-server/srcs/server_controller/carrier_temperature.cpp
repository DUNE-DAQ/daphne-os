#include "server_controller/carrier_temperature.hpp"

#include <limits>

#include "BoardI2C.hpp"
#include "I2CDevice.hpp"
#include "server_controller/board_monitor.hpp"

namespace daphne_sc {
daphne::TemperatureStatus read_carrier_temperature() {
  daphne::TemperatureStatus result;
  result.set_name("Carrier_U9_MCP9808");
  result.set_temperature_c(std::numeric_limits<double>::quiet_NaN());
  result.set_quality(daphne::MEASUREMENT_UNAVAILABLE);
  result.set_source("Carrier U9 MCP9808 / PS I2C1 ff030000 / address 0x18");
  try {
    const auto path = board_ps_i2c_adapter();
    result.set_source(result.source() + " / " + path + " / register 0x05");
    I2CDevice sensor(path, 0x18);
    const auto value = read_mcp9808_celsius([&](uint8_t address) {
      const auto little_endian_word = sensor.readWordSMBus(address);
      return static_cast<uint16_t>((little_endian_word >> 8) | (little_endian_word << 8));
    });
    result.set_temperature_c(value);
    result.set_valid(true);
    result.set_quality(daphne::MEASUREMENT_GOOD);
    result.set_observed_host_unix_ns(host_unix_time_ns());
    result.set_observed_monotonic_ns(monotonic_time_ns());
    result.set_message("Identified carrier sensor, not SoC die or mezzanine. "
                       "Host observation times, not conversion time or verified UTC; no alarm thresholds applied");
  } catch (const std::exception& e) {
    result.set_quality(daphne::MEASUREMENT_ERROR);
    result.set_message(e.what());
  }
  return result;
}

void set_general_info_temperature(daphne::GeneralInfo& info,
                                  const daphne::TemperatureStatus& temperature) {
  info.set_temperature(temperature.temperature_c());
  info.set_temperature_quality(temperature.quality());
  info.set_temperature_detail(temperature.source() + ": " + temperature.message());
  *info.mutable_temperature_status() = temperature;
}
}  // namespace daphne_sc
