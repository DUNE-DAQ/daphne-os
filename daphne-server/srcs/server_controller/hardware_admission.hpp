#pragma once
#include "server_controller/gateware.hpp"

namespace daphne_sc {
// No MMIO is used to check that dynamic PL exists. Called before mapping
// identity or constructing drivers, and before raw-DMA worker operations.
void require_applied_overlay();
void require_live_gateware(const GatewareIdentity&, GatewareMode);
void set_raw_dma_register_policy(bool enabled);
void validate_legacy_register_address(uint64_t address);
} // namespace daphne_sc
