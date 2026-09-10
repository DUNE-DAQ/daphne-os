#include "server_controller/sfp_monitor.hpp"
#include "server_controller/board_monitor.hpp"
#include "BoardI2C.hpp"
#include "I2CDevice.hpp"
#include <chrono>
#include <mutex>
#include <thread>

namespace daphne_sc {
void add_sfp_status(daphne::SystemStatusSnapshot& snapshot, const TemperatureAlarmPolicy& policy) {
  const std::string source = "Carrier U32 TCA9548A / PL I2C 9c000000 / mux 0x72 / SFF-8472 A0/A2 lower memory";
  static std::mutex transaction_mutex;
  std::lock_guard<std::mutex> lock(transaction_mutex);
  snapshot.clear_sfps();
  auto empty = [&](unsigned channel, const std::string& reason, daphne::MeasurementQuality quality) -> daphne::SFPMonitor& {
    auto& r = *snapshot.add_sfps();
    r.set_name(sfp_connector(channel)); r.set_mux_address(0x72); r.set_mux_channel(channel);
    r.set_a0_address(0x50); r.set_a2_address(0x51); r.set_source(source);
    r.set_identity_quality(quality); r.set_diagnostic_quality(daphne::MEASUREMENT_UNAVAILABLE);
    r.set_message(reason);
    return r;
  };
  try {
    const auto path = board_pl_i2c_adapter();
    I2CDevice mux(path, 0x72); // I2C_SLAVE refuses an already kernel-owned mux.
    mux.lockAdapter(); // Advisory process ownership held across all routes and restoration.
    SfpIO io;
    io.read_mux = [&] { uint8_t value; mux.readSingleByte(value); return value; };
    io.write_mux = [&](uint8_t value) {
      if ((value & 0xc0) || (value && (value & (value - 1)))) throw std::invalid_argument("Unsafe SFP mux route");
      mux.writeSingleByte(value); // STOP before downstream access.
    };
    io.read_eeprom = [&](uint8_t address, uint8_t offset, size_t length) {
      if ((address != 0x50 && address != 0x51) || !length || length > 32 || offset + length > 128)
        throw std::invalid_argument("SFP EEPROM read outside allowed region");
      I2CDevice device(path, address);
      std::vector<uint8_t> bytes;
      device.readBytes(offset, bytes, length);
      return bytes;
    };
    io.now = monotonic_time_ns;
    io.wait = [](uint64_t ns) { std::this_thread::sleep_for(std::chrono::nanoseconds(ns)); };
    bool restoration_failed = false;
    for (unsigned channel = 0; channel < 6; ++channel) {
      if (restoration_failed) {
        empty(channel, "Not attempted after mux-restoration failure; no reset/recovery writes", daphne::MEASUREMENT_UNAVAILABLE);
        continue;
      }
      auto& r = *snapshot.add_sfps();
      r = collect_sfp_port(channel, io, source + " / " + path);
      restoration_failed = r.has_mux_restored() && !r.mux_restored();
      r.set_bus(std::stoul(path.substr(path.rfind('-') + 1)));
      r.set_observed_host_unix_ns(host_unix_time_ns());
    }
  } catch (const std::exception& e) {
    snapshot.clear_sfps();
    for (unsigned channel = 0; channel < 6; ++channel)
      empty(channel, std::string("SFP collector unavailable: ") + e.what(), daphne::MEASUREMENT_ERROR);
  }
  for (auto& r : *snapshot.mutable_sfps()) evaluate_sfp_temperature_alarm(r, policy, monotonic_time_ns());
}
} // namespace daphne_sc
