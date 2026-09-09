#pragma once

#include <cstdint>
#include <stdexcept>
#include <vector>

#include "server_controller/gateware.hpp"

namespace daphne_sc {

inline void validate_counter_request(uint32_t base, const std::vector<uint32_t>& channels) {
  if (base != kSelfTriggerBaseAddress) {
    throw std::invalid_argument("Counter base must be the ABI-2 address 0xA0010000");
  }
  for (uint32_t channel : channels) {
    if (channel >= 40) throw std::invalid_argument("Counter channel out of range (0..39)");
  }
}

// Adapted from daphneZMQ feature/slow-control-emulator (c262397).
// Unlike its fallback, never return a potentially torn value after exhaustion.
// This protects one running counter against rollover, not against concurrent
// counter resets, nor does it latch all counters at a common instant.
template <typename Read32>
uint64_t read_stable_counter64(Read32&& read, uint32_t low, uint32_t high) {
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    const uint32_t before = read(high);
    const uint32_t value = read(low);
    const uint32_t after = read(high);
    if (before == after) return (static_cast<uint64_t>(after) << 32) | value;
  }
  throw std::runtime_error("Counter changed across all three read attempts; retry the request");
}

}  // namespace daphne_sc
