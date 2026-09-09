#include <cmath>
#include <iostream>
#include <stdexcept>
#include <thread>

#include "server_controller/telemetry_protocol.hpp"

namespace {
void require(bool ok) {
  if (!ok) throw std::runtime_error("board monitor assertion failed");
}
template <typename Function>
void rejects(Function function) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  require(rejected);
}
}

int main() {
  using namespace daphne_sc;
  BoardMonitor monitor;
  auto initial = make_general_info(monitor.snapshot());
  require(std::isnan(initial.v_bias_0()) && std::isnan(initial.temperature()));
  require(initial.board_voltage_status().quality() == daphne::MEASUREMENT_UNAVAILABLE);
  require(initial.board_voltage_status().observed_monotonic_ns() == 0);
  monitor.invalidate("ADC missing");
  require(monitor.snapshot().detail == "ADC missing");
  rejects([&] { monitor.publish({1}, {1, 2, 3}, 10, 20); });
  rejects([&] { monitor.publish({1, 2, 3, 4, 5, 6, 7}, {1, 2, NAN}, 10, 20); });
  require(monitor.snapshot().quality == MonitorQuality::kUnavailable);
  monitor.publish({1, 2, 3, 4, 5, 6, 7}, {8, 9, 10}, 10, 20);
  auto valid = make_general_info(monitor.snapshot(20));
  require(valid.board_voltage_status().quality() == daphne::MEASUREMENT_GOOD);
  require(valid.power_minus5v() == -20 && valid.power_plus2p5v() == 2 && valid.power_ce() == 16);
  require(valid.v_bias_0() == 3 * 39.314 && valid.v_bias_4() == 7 * 39.314);
  require(valid.board_voltage_status().named_voltages_size() == 10);
  require(valid.board_voltage_status().named_voltages(8).name() == "3V3A");
  require(valid.board_voltage_status().named_voltages(8).volts() == 18);
  require(valid.board_voltage_status().observed_host_unix_ns() == 10);
  require(std::isnan(valid.temperature()));
  require(monitor.snapshot(5'000'000'020ULL).quality == MonitorQuality::kGood);
  require(monitor.snapshot(5'000'000'021ULL).quality == MonitorQuality::kStale);
  require(std::isnan(monitor.snapshot(19).valid_voltage(0)));
  monitor.invalidate("read failed");
  auto failed = make_general_info(monitor.snapshot(30));
  require(failed.board_voltage_status().quality() == daphne::MEASUREMENT_ERROR);
  require(failed.board_voltage_status().observed_monotonic_ns() == 20);
  require(std::isnan(failed.v_bias_0()));
  daphne::GeneralInfo decoded;
  require(decoded.ParseFromString(failed.SerializeAsString()));
  require(std::isnan(decoded.v_bias_0()) && std::isnan(decoded.temperature()));
  // Real zero is valid, distinct from missing data.
  monitor.publish(std::vector<double>(7, 0), std::vector<double>(3, 0), 40, 50);
  require(make_general_info(monitor.snapshot(50)).v_bias_0() == 0);
  // Concurrent producer and consumer cannot mix voltage/time generations.
  std::thread producer([&] {
    for (uint64_t i = 1; i < 2000; ++i)
      monitor.publish(std::vector<double>(7, i), std::vector<double>(3, i), i, i);
  });
  for (unsigned i = 0; i < 2000; ++i) {
    auto snapshot = monitor.snapshot(2000);
    if (snapshot.host_unix_ns != 40) {
      require(snapshot.volts[0] == snapshot.host_unix_ns * 2.0);
      require(snapshot.volts[9] == snapshot.host_unix_ns * -2.0);
    }
  }
  producer.join();
  std::cout << "Telemetry default, quality, scaling, timestamps, wire and concurrency tests passed\n";
}
