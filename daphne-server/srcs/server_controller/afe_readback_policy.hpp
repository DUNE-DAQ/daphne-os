#pragma once

#include <cstdint>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <algorithm>

namespace daphne_sc {

// This policy concerns ADC SPI value mismatches only. Exceptions from SPI,
// FPGA admission, clocks, DMA bounds and physical data validation still fail.
enum class AfeReadbackPolicy { kStrict, kWarn };

inline AfeReadbackPolicy parse_afe_readback_policy(const std::string& value) {
  if (value == "strict") return AfeReadbackPolicy::kStrict;
  if (value == "warn") return AfeReadbackPolicy::kWarn;
  throw std::invalid_argument("Invalid DMA AFE readback policy: expected strict or warn");
}

inline std::string afe_readback_notice(AfeReadbackPolicy policy) {
  return policy == AfeReadbackPolicy::kWarn
      ? "WARNING: DMA AFE readback policy=warn; ADC SPI value mismatches are tolerated; "
        "AFE register configuration is not guaranteed by readback."
      : "";
}

inline std::string with_afe_readback_notice(const std::string& message, AfeReadbackPolicy policy) {
  const auto notice = afe_readback_notice(policy);
  return notice.empty() ? message : notice + (message.empty() ? "" : "\n" + message);
}

// Shared instances may be used by the router and the DMA worker. Deduplicate
// the bounded set of AFE/field observations so waveform loops do not flood logs.
class AfeReadbackVerifier {
 public:
  explicit AfeReadbackVerifier(AfeReadbackPolicy policy, std::string stage,
                               std::ostream& log = std::cerr)
      : policy_(policy), stage_(std::move(stage)), log_(log) {}

  bool check(uint32_t afe, const std::string& field, uint32_t expected, uint32_t actual,
             const std::string& error) {
    if (expected == actual) return true;
    const auto detail = "AFE" + std::to_string(afe) + " " + field +
        " expected=" + std::to_string(expected) + " actual=" + std::to_string(actual);
    if (policy_ == AfeReadbackPolicy::kStrict) throw std::runtime_error(error + ": " + detail);
    const auto warning = "DMA_AFE_READBACK_WARNING [" + stage_ + "] " + detail;
    std::lock_guard<std::mutex> lock(mutex_);
    if (std::find(warnings_.begin(), warnings_.end(), warning) == warnings_.end()) {
      // Values may change continuously on a defective bus. Keep logging bounded.
      if (warnings_.size() < 256) { warnings_.push_back(warning); log_ << warning << std::endl; }
      else if (!overflow_) {
        overflow_ = true;
        log_ << "DMA_AFE_READBACK_WARNING [" << stage_ << "] further distinct mismatches suppressed" << std::endl;
      }
    }
    return false;
  }

  std::string summary() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::string result = afe_readback_notice(policy_);
    if (!result.empty()) result += '\n';
    for (const auto& warning : warnings_) result += warning + '\n';
    if (overflow_) result += "Further distinct AFE readback mismatches suppressed.\n";
    return result;
  }

 private:
  AfeReadbackPolicy policy_;
  std::string stage_;
  std::ostream& log_;
  mutable std::mutex mutex_;
  std::vector<std::string> warnings_;
  bool overflow_ = false;
};

} // namespace daphne_sc
