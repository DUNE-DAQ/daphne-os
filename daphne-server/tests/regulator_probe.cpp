// Read-only opt-in probe: kernel FPGA status gate, then fixed-address SMBus PEC
// reads. No MMIO, mux, regulator configuration, fault clear, BIAS or network writes.
#include "server_controller/regulator_monitor.hpp"
#include "server_controller/fpga_health.hpp"
#include "server_controller/board_monitor.hpp"
#include <iostream>

int main(int argc, char** argv) {
  try {
    if (argc != 2 || std::string(argv[1]) != "--read-onboard-regulators")
      throw std::invalid_argument("Usage: regulator_probe --read-onboard-regulators");
    const auto programming = daphne_sc::read_fpga_programming_status();
    if (!daphne_sc::fpga_status_mmio_prerequisites(programming, daphne_sc::monotonic_time_ns()))
      throw std::runtime_error("FPGA programming prerequisites not verified; no PL I2C access");
    daphne::SystemStatusSnapshot result;
    daphne_sc::add_regulator_status(result, {}, true);
    std::cout << result.DebugString();
    for (const auto& r : result.regulators())
      if (!r.identity_bracket_verified() || r.voltage_quality() != daphne::MEASUREMENT_GOOD ||
          r.current_quality() != daphne::MEASUREMENT_GOOD || !r.temperature().valid()) return 2;
    return result.regulators_size() == 4 ? 0 : 3;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
