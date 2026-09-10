#include "server_controller/fpga_health.hpp"
#include "server_controller/board_monitor.hpp"
#include <iostream>

int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "Usage: fpga_programming_probe (read-only kernel FPGA programming observations; no MMIO)\n";
    return 2;
  }
  const auto result = daphne_sc::read_fpga_programming_status();
  std::cout << result.DebugString(); // Only fixed-source non-private programming observations.
  return daphne_sc::fpga_status_mmio_prerequisites(result, daphne_sc::monotonic_time_ns()) ? 0 : 1;
}
