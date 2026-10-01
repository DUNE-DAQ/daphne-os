#include "server_controller/runtime_registers.hpp"
#include <iostream>
#include <map>
#include <stdexcept>
using namespace daphne_sc;
class Fake final : public Mmio32 {
 public:
  std::map<uint64_t,uint32_t> registers;
  unsigned writes=0;
  uint32_t read32(uint64_t address) override { return registers[address]; }
  void write32(uint64_t address,uint32_t value) override { ++writes; registers[address]=value; }
};
int main() {
  Fake io;
  for (uint64_t address : {0xA0010F00ULL,0xA0010F0CULL}) {
    if (access_runtime_register(io,address,true,0x80000081)!=0x80000081) return 1;
    if (access_runtime_register(io,address,false,0)!=0x80000081) return 1;
  }
  for (uint64_t address : {0xA0010F04ULL,0xA0010F08ULL,0xA0010F10ULL,0xA0010F14ULL,0x94000020ULL,0x94000024ULL,0x94000028ULL,0x88000034ULL}) {
    io.registers[address]=7;
    if (access_runtime_register(io,address,false,0)!=7) return 1;
    try { access_runtime_register(io,address,true,9); return 1; } catch (const std::invalid_argument&) {}
  }
  for (bool write : {false,true}) {
    try { access_runtime_register(io,0x88000008,write,1); return 1; } catch (const std::invalid_argument&) {}
    for (uint64_t address : {0x88000020ULL,0x88000024ULL,0x88000028ULL}) {
      try { access_runtime_register(io,address,write,1); return 1; } catch (const std::invalid_argument&) {}
    }
  }
  if (io.writes!=2) return 1;
  std::cout<<"PASS stateless runtime register bridge\n";
}
