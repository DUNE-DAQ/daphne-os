#pragma once
#include "server_controller/gateware.hpp"
namespace daphne_sc {
// Stateless access to the runtime trigger controls and their hardware status.
uint32_t access_runtime_register(Mmio32& mmio, uint64_t address, bool write, uint32_t value);
}
