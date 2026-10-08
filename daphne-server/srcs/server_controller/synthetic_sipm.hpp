#pragma once

#include <cstdint>
#include <functional>

#include "server_controller/gateware.hpp"

namespace daphne_sc {

constexpr uint64_t kSyntheticConfigAddress = 0x94000050ULL;
constexpr uint32_t kSyntheticAmplitudeMask = 0x003FFFFFU;
constexpr uint32_t kSyntheticModelBit = 0x00400000U;
constexpr uint32_t kSyntheticEnableBit = 0x00800000U;
constexpr uint32_t kSyntheticConfigMask = 0x00FFFFFFU;

uint32_t encode_synthetic_config(uint32_t amplitude_q8, uint32_t model, bool enable);
uint32_t read_synthetic_config(Mmio32& mmio);

// Every call disables and clears filter history, including repeated settings.
// Readback verifies AXI storage; settle must wait at least 80 ns per write.
// An empty settle callback uses a conservative one-microsecond delay.
uint32_t configure_synthetic_sipm(
    Mmio32& mmio, uint32_t amplitude_q8, uint32_t model, bool enable,
    const std::function<void()>& settle = {});

}  // namespace daphne_sc
