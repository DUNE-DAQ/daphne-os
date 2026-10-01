#include "server_controller/runtime_registers.hpp"
#include <stdexcept>
namespace daphne_sc {
uint32_t access_runtime_register(Mmio32& mmio,uint64_t address,bool write,uint32_t value) {
  const bool writable=address==0xA0010F00 || address==0xA0010F0C;
  const bool readable=writable || address==0xA0010F04 || address==0xA0010F08 ||
    address==0xA0010F10 || address==0xA0010F14 || address==0x88000020 ||
    address==0x88000024 || address==0x88000028 || address==0x88000034;
  if (!readable || (write && !writable)) throw std::invalid_argument("Unsupported runtime register access");
  if (write) mmio.write32(address,value);
  return mmio.read32(address);
}
}
