// Diagnostic: ID read only (SPI-controller configuration is required for reads).
// No ADC reset, conversion start, carrier mux, BIAS or power command.
#include <chrono>
#include <iomanip>
#include <iostream>
#include <thread>
#include "ADS1261.hpp"
#include "BoardSPI.hpp"
#include "SpiDevice.hpp"

int main() {
  try {
    const auto path = board_current_spi_device();
    SpiDevice spi(path, 1000000, 1, 8);
    daphne_sc::ADS1261 adc([&](const auto& tx) { return spi.transfer(tx); },
      [] { return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
          std::chrono::steady_clock::now().time_since_epoch()).count()); },
      [](uint64_t ns) { std::this_thread::sleep_for(std::chrono::nanoseconds(ns)); });
    const auto id = adc.probe();
    std::cout << "ADS1261 at " << path << ", ID=0x" << std::hex << unsigned(id)
              << ", CRC mode=" << adc.crc_enabled() << "; no ADC reset or carrier mux command\n";
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
