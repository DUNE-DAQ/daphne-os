#include "server_controller/regulator_monitor.hpp"
#include "server_controller/board_monitor.hpp"
#include "BoardI2C.hpp"
#include "I2CDevice.hpp"
#include <mutex>

namespace daphne_sc {
void add_regulator_status(daphne::SystemStatusSnapshot& status, const TemperatureAlarmPolicy& policy,
                          bool fabric_access_allowed) {
  static std::mutex transaction_mutex;
  std::lock_guard<std::mutex> lock(transaction_mutex);
  status.clear_regulators();
  std::string path;
  if (fabric_access_allowed) {
    try { path = board_pl_i2c_adapter(); } catch (const std::exception&) {}
  }
  for (unsigned index = 0; index < kRegulatorRoutes.size(); ++index) {
    auto& result = *status.add_regulators();
    result = unavailable_regulator(index, fabric_access_allowed ?
        "Unique PL I2C controller unavailable; no alternate bus, scan or recovery writes" :
        "FPGA observation prerequisites failed; no PL I2C access attempted");
    if (!path.empty()) try {
      I2CDevice device(path, kRegulatorRoutes[index].address, 1); // Mandatory PEC; I2C_SLAVE, never FORCE.
      device.lockAdapter(); // Held through this module's complete bracket; no multi-module atomicity claim.
      RegulatorIO io{
        [&](uint8_t command) {
          if (!regulator_read_allowed(command, 8)) throw std::invalid_argument("Unqualified PMBus byte read");
          return device.readByteSMBus(command);
        },
        [&](uint8_t command) {
          if (!regulator_read_allowed(command, 16)) throw std::invalid_argument("Unqualified PMBus word read");
          return device.readWordSMBus(command);
        }, monotonic_time_ns, host_unix_time_ns};
      result = collect_regulator(index, io);
      result.set_source(result.source() + " / " + path);
    } catch (const std::exception&) {
      result = unavailable_regulator(index, "Regulator adapter ownership/PEC transport unavailable; no fallback, force, configuration or recovery writes");
      result.set_identity_quality(daphne::MEASUREMENT_ERROR);
    }
    evaluate_temperature_alarm(*result.mutable_temperature(), policy, monotonic_time_ns());
  }
}
} // namespace daphne_sc
