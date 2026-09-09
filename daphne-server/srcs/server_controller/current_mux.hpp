#pragma once
#include <cstdint>
#include <stdexcept>
#include "server_controller/gateware.hpp"
#include "ADS1261.hpp"

namespace daphne_sc {
struct CurrentChannelSelection {
  uint32_t physical_channel, afe, local_channel, enable, address;
  uint8_t adc_mux;
};
inline CurrentChannelSelection current_channel_selection(uint32_t channel) {
  if (channel >= 40) throw std::invalid_argument("Current monitor physical channel outside 0..39");
  const auto afe = channel / 8, local = channel % 8;
  return {channel, afe, local, 1u << (local / 4), local % 4, ads1261_afe_mux(afe)};
}

// Shared by all five AFE blocks. Only these two ABI-2 monitor-selector registers
// may be written. Break before make; never enable both ADG1609 banks together.
class CurrentMuxTransaction {
 public:
  static constexpr uint64_t enable_address = 0x94000010, select_address = 0x94000014;
  explicit CurrentMuxTransaction(Mmio32& mmio) : mmio_(mmio),
      original_enable_(mmio.read32(enable_address)), original_address_(mmio.read32(select_address)) {
    if (original_enable_ > 2 || original_address_ > 3)
      throw std::runtime_error("Unsafe or incompatible existing current-monitor mux state; no selection written");
  }
  ~CurrentMuxTransaction() {
    if (!armed_) return;
    try { restore(); } catch (...) {
      // If restoration itself fails, best effort to disconnect the monitor.
      try { mmio_.write32(enable_address, 0); } catch (...) {}
    }
  }
  CurrentMuxTransaction(const CurrentMuxTransaction&) = delete;
  CurrentMuxTransaction& operator=(const CurrentMuxTransaction&) = delete;
  void select(uint32_t physical_channel) {
    const auto plan = current_channel_selection(physical_channel);
    armed_ = true;
    checked_write(enable_address, 0);
    checked_write(select_address, plan.address);
    checked_write(enable_address, plan.enable);
  }
  void verify(uint32_t physical_channel) {
    const auto plan = current_channel_selection(physical_channel);
    if (mmio_.read32(enable_address) != plan.enable || mmio_.read32(select_address) != plan.address)
      throw std::runtime_error("Carrier current mux changed during conversion");
  }
  void restore() {
    if (!armed_) return;
    checked_write(enable_address, 0);
    checked_write(select_address, original_address_);
    checked_write(enable_address, original_enable_);
    armed_ = false;
  }
 private:
  void checked_write(uint64_t address, uint32_t value) {
    mmio_.write32(address, value);
    if (mmio_.read32(address) != value) throw std::runtime_error("Current mux write/readback mismatch");
  }
  Mmio32& mmio_;
  uint32_t original_enable_, original_address_;
  bool armed_ = false;
};
}  // namespace daphne_sc
