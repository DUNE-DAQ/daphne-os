#include "server_controller/synthetic_sipm.hpp"

#include <chrono>
#include <stdexcept>
#include <string>
#include <thread>

namespace daphne_sc {

uint32_t encode_synthetic_config(uint32_t amplitude_q8, uint32_t model, bool enable) {
  if (amplitude_q8 < 256U || amplitude_q8 > 2560000U) {
    throw std::invalid_argument("amplitude_q8 out of range (256..2560000; A=1..10000)");
  }
  if (model > 1U) {
    throw std::invalid_argument("model must be FBK (0) or HPK (1)");
  }
  return amplitude_q8 | (model << 22U) | (enable ? kSyntheticEnableBit : 0U);
}

uint32_t read_synthetic_config(Mmio32& mmio) {
  const uint32_t value = mmio.read32(kSyntheticConfigAddress);
  if (value == 0U) {
    throw std::runtime_error(
        "SYN_CONFIG reads zero: synthetic generator unavailable or configuration invalid");
  }
  return value;
}

uint32_t configure_synthetic_sipm(
    Mmio32& mmio, uint32_t amplitude_q8, uint32_t model, bool enable,
    const std::function<void()>& settle) {
  const uint32_t requested = encode_synthetic_config(amplitude_q8, model, enable);
  const uint32_t previous = mmio.read32(kSyntheticConfigAddress);
  const uint32_t previous_disabled = previous & kSyntheticConfigMask & ~kSyntheticEnableBit;
  const auto wait = [&] {
    if (settle) settle();
    else std::this_thread::sleep_for(std::chrono::microseconds(1));
  };
  const auto write_and_wait = [&](uint32_t value) {
    mmio.write32(kSyntheticConfigAddress, value);
    uint32_t observed = 0;
    try {
      observed = mmio.read32(kSyntheticConfigAddress);
    } catch (...) {
      wait();
      throw;
    }
    // Also wait after failed verification: the write may have reached hardware.
    wait();
    if (observed != value) {
      throw std::runtime_error(
          "SYN_CONFIG readback mismatch (generator unavailable or write failed): expected " +
          std::to_string(value) + ", read " + std::to_string(observed));
    }
  };

  try {
    write_and_wait(previous_disabled);
    write_and_wait(requested & ~kSyntheticEnableBit);
    if (enable) write_and_wait(requested);
    return requested;
  } catch (const std::exception& error) {
    std::string message = error.what();
    try {
      write_and_wait(previous_disabled);
    } catch (const std::exception& disable_error) {
      message += "; could not verify disabled state: ";
      message += disable_error.what();
    }
    throw std::runtime_error(message);
  }
}

}  // namespace daphne_sc
