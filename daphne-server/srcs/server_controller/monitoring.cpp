#include "server_controller/monitoring.hpp"

#include <chrono>
#include <iostream>
#include <mutex>
#include <thread>

#include "Daphne.hpp"
#include "server_controller/board_voltage_acquisition.hpp"

namespace daphne_sc {
namespace {

void i2c_2_monitor_thread(Daphne& daphne, std::chrono::milliseconds period) {
  while (true) {
    try {
      std::unique_lock<std::mutex> i2c2_lock(daphne.i2c_2_mutex, std::try_to_lock);
      if (!i2c2_lock.owns_lock()) {
        std::this_thread::sleep_for(period);
        continue;
      }

      auto* hd = daphne.getHDMezzDriver();
      if (hd) {
        for(size_t i = 0; i < 5; i++){
          try {
            // The driver serializes/publishes a whole cycle, including errors.
            // Disabled/unconfigured blocks perform no I/O; protective actions stay in the driver.
            const auto sample = hd->pollMonitoring(i);
            if (sample.alerts[0].latched || sample.alerts[1].latched) {
              if (daphne.runtime) daphne.runtime->invalidate("Mezzanine alert observed; configuration no longer qualified");
              std::cerr << "Alert on AFE block " << i << ": "
                        << (sample.alerts[0].latched ? "5V alert " : "")
                        << (sample.alerts[1].latched ? "CE alert " : "")
                        << (sample.protectiveActionAttempted ? "power-removal requested" : "retained history; no action in this cycle")
                        << std::endl;
            }
            if (sample.quality == I2CMezzDrivers::HDMezzDriver::MonitorQuality::Error ||
                sample.quality == I2CMezzDrivers::HDMezzDriver::MonitorQuality::Invalid)
              std::cerr << "I2C_2 monitor AFE " << i << ": " << sample.detail << std::endl;
          } catch (const std::exception& e) {
            std::cerr << "I2C_2 monitor AFE " << i << " error: "
                      << e.what() << std::endl;
          }
        }
      }
    } catch (const std::exception& e) {
      std::cerr << "I2C_2 monitor error: " << e.what() << std::endl;
    }

    std::this_thread::sleep_for(period);
  }
}

void i2c_1_monitor_thread(Daphne& daphne, std::chrono::milliseconds period) {
  bool warned_missing_adc = false;
  while (true) {
    try {
      std::unique_lock<std::mutex> i2c1_lock(daphne.i2c_1_mutex, std::try_to_lock);
      if (!i2c1_lock.owns_lock()) {
        std::this_thread::sleep_for(period);
        continue;
      }
      if (!daphne.isI2C_1_device_configuring.load() && !daphne.user_vbias_voltage_request.load()) {
        auto* adc0x10 = daphne.getADS7138_Driver_addr_0x10();
        auto* adc0x17 = daphne.getADS7138_Driver_addr_0x17();
        if (!adc0x10 || !adc0x17) {
          daphne.board_monitor.invalidate("Required ADS7138 drivers are unavailable");
          if (!warned_missing_adc) {
            std::cerr << "ADS7138 drivers not available; skipping I2C_1 monitor." << std::endl;
            warned_missing_adc = true;
          }
          std::this_thread::sleep_for(std::chrono::seconds(1));
          continue;
        }

        daphne.is_vbias_voltage_monitor_reading.store(true);
        acquire_board_voltages(daphne.board_monitor, *adc0x10, *adc0x17);
        daphne.is_vbias_voltage_monitor_reading.store(false);
      }
    } catch (const std::exception& e) {
      daphne.is_vbias_voltage_monitor_reading.store(false);
      daphne.board_monitor.invalidate(e.what());
      std::cerr << "I2C_1 monitor error: " << e.what() << std::endl;
    }

    std::this_thread::sleep_for(period);
  }
}

}  // namespace

std::vector<std::thread> start_monitoring(Daphne& daphne, const MonitoringOptions& options) {
  std::vector<std::thread> threads;
  threads.emplace_back(i2c_1_monitor_thread, std::ref(daphne), options.period);
  threads.emplace_back(i2c_2_monitor_thread, std::ref(daphne), options.period);
  return threads;
}

}  // namespace daphne_sc
