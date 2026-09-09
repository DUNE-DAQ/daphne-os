#pragma once

#include "server_controller/board_monitor.hpp"

namespace daphne_sc {

// ADS7138::readData takes complete scans, not the number of enabled channels.
// Keep the same acquisition path usable with fake ADCs in hardware-free tests.
template <typename Adc10, typename Adc17>
void acquire_board_voltages(BoardMonitor& monitor, Adc10& adc10, Adc17& adc17) {
  const auto values10 = adc10.readData(1);  // One scan of seven enabled channels.
  const auto values17 = adc17.readData(1);  // One scan of three enabled channels.
  monitor.publish(values10, values17, host_unix_time_ns(), monotonic_time_ns());
}

}  // namespace daphne_sc
