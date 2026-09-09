#pragma once

#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace daphne_sc {

inline uint64_t monotonic_time_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline uint64_t host_unix_time_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}
constexpr double kUnavailableVoltage = std::numeric_limits<double>::quiet_NaN();
enum class MonitorQuality { kUnavailable, kGood, kStale, kError };

struct BoardMonitorSnapshot {
  // 3V3PDS, 1V8PDS, VBIAS0..4, 1V8A, 3V3A, Minus5VA.
  std::array<double, 10> volts{{
      kUnavailableVoltage, kUnavailableVoltage, kUnavailableVoltage, kUnavailableVoltage,
      kUnavailableVoltage, kUnavailableVoltage, kUnavailableVoltage, kUnavailableVoltage,
      kUnavailableVoltage, kUnavailableVoltage}};
  MonitorQuality quality = MonitorQuality::kUnavailable;
  std::string detail = "No complete ADS7138 sample has been acquired";
  uint64_t host_unix_ns = 0;  // Host wall clock; NOT certified timing-endpoint time.
  uint64_t monotonic_ns = 0;

  double valid_voltage(size_t index) const {
    return quality == MonitorQuality::kGood ? volts.at(index) : kUnavailableVoltage;
  }
};

// Adapt the original slow-control-emulator's cached quality/time design, but
// publish values and metadata under one mutex: no mixed-generation snapshots.
class BoardMonitor {
 public:
  void publish(const std::vector<double>& adc10, const std::vector<double>& adc17,
               uint64_t unix_ns, uint64_t mono_ns) {
    if (adc10.size() != 7 || adc17.size() != 3) {
      throw std::runtime_error("Incomplete ADS7138 sample (expected 7 + 3 channels)");
    }
    BoardMonitorSnapshot next;
    next.volts = {{adc10[0] * 2, adc10[1] * 2,
                   adc10[2] * 39.314, adc10[3] * 39.314, adc10[4] * 39.314,
                   adc10[5] * 39.314, adc10[6] * 39.314,
                   adc17[0] * 2, adc17[1] * 2, adc17[2] * -2}};
    for (double value : next.volts) {
      if (!std::isfinite(value)) throw std::runtime_error("Non-finite ADS7138 sample");
    }
    if (mono_ns == 0) throw std::runtime_error("Missing acquisition timestamp");
    next.host_unix_ns = unix_ns;
    next.monotonic_ns = mono_ns;
    next.quality = MonitorQuality::kGood;
    next.detail = "Cached ADS7138 voltages; host wall clock is unverified";
    std::lock_guard<std::mutex> lock(mutex_);
    sample_ = next;
  }

  void invalidate(const std::string& reason) {
    std::lock_guard<std::mutex> lock(mutex_);
    sample_.quality = sample_.monotonic_ns ? MonitorQuality::kError : MonitorQuality::kUnavailable;
    sample_.detail = reason;
  }

  BoardMonitorSnapshot snapshot(uint64_t now = monotonic_time_ns()) const {
    std::lock_guard<std::mutex> lock(mutex_);
    auto result = sample_;
    if (result.quality == MonitorQuality::kGood &&
        (now < result.monotonic_ns || now - result.monotonic_ns > 5'000'000'000ULL)) {
      result.quality = MonitorQuality::kStale;
      result.detail = "ADS7138 sample is stale (5 s limit) or monotonic clock is invalid";
    }
    return result;
  }

 private:
  mutable std::mutex mutex_;
  BoardMonitorSnapshot sample_;
};

}  // namespace daphne_sc
