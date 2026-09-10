#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <unistd.h>
#include "server_controller/readonly_mmio.hpp"
#include "server_controller/timing_status.hpp"

namespace {
void require(bool ok) {
  if (!ok) throw std::runtime_error("timing status assertion failed");
}
template <typename Function>
void rejects(Function function) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  require(rejected);
}
class FakeTiming : public daphne_sc::Mmio32 {
 public:
  std::array<uint32_t, 4> words{{4, 3, 0, 24}};
  bool changing = false;
  unsigned reads = 0;
  uint32_t read32(uint64_t address) override {
    require(address >= daphne_sc::kTimingRegisterBase && address <= daphne_sc::kTimingRegisterBase + 12);
    const unsigned index = (address - daphne_sc::kTimingRegisterBase) / 4;
    ++reads;
    return words.at(index) + (changing ? reads : 0);
  }
  void write32(uint64_t, uint32_t) override {
    throw std::runtime_error("Unexpected hardware write");
  }
};
}

int main() {
  using namespace daphne_sc;
  FakeTiming mmio;
  unsigned cases = 0;
  for (unsigned control = 0; control < 8; ++control)
    for (unsigned locks = 0; locks < 4; ++locks)
      for (unsigned fsm = 0; fsm < 16; ++fsm)
        for (unsigned valid = 0; valid < 2; ++valid)
          for (unsigned reset = 0; reset < 2; ++reset) {
            mmio.words = {{control, locks, 0x1234u | reset << 16, fsm | valid << 4}};
            auto result = read_timing_status(mmio);
            require(result.ready() == (control == 4 && locks == 3 && fsm == 8 && valid && !reset));
            require(result.endpoint_control_raw() == mmio.words[2]);
            require(result.has_endpoint_address() && result.endpoint_address() == 0x1234);
            require(result.fsm_state() == fsm);
            require(result.observation_quality() == daphne::MEASUREMENT_GOOD);
            require(result.live_timestamp_quality() == daphne::MEASUREMENT_UNAVAILABLE);
            require(result.last_timing_timestamp() == 0);
            daphne::EndpointStatus decoded;
            require(decoded.ParseFromString(result.SerializeAsString()));
            require(decoded.ready() == result.ready());
            ++cases;
          }
  mmio.changing = true;
  mmio.reads = 0;
  rejects([&] { read_timing_status(mmio); });
  require(mmio.reads == 24);
  for (auto mode : {GatewareMode::kSelfTrigger, GatewareMode::kFullStream}) {
    daphne::SystemStatusSnapshot status;
    add_register_capabilities(status, mode);
    require(status.capabilities_size() == 16);
    require(status.capabilities(2).supported() == supports_trigger_counters(mode));
    for (int i = 3; i < 7; ++i)
      require(!status.capabilities(i).supported() && !status.capabilities(i).reason().empty());
    require(status.capabilities(7).name() == "ChannelConfig.gain");
    require(status.capabilities(7).supported() && !status.capabilities(7).reason().empty());
    require(status.capabilities(8).name() == "AMSTemperatures" && status.capabilities(8).supported());
    require(status.capabilities(9).name() == "CarrierTemperature" && status.capabilities(9).supported());
    require(status.capabilities(10).name() == "RuntimeServices" && status.capabilities(10).supported());
    require(status.capabilities(11).name() == "ServerBookkeeping" && status.capabilities(11).supported());
    require(status.capabilities(12).name() == "TemperatureAlarms" && status.capabilities(12).supported());
    require(status.capabilities(13).name() == "CurrentMonitorRaw" && status.capabilities(13).supported());
    require(status.capabilities(14).name() == "SFPDiagnostics" && status.capabilities(14).supported());
    require(status.capabilities(15).name() == "DatabaseIdentityAssignments" && status.capabilities(15).supported());
  }
  char filename[] = "/tmp/daphne-readonly-mmio-XXXXXX";
  const int fd = mkstemp(filename);
  require(fd >= 0);
  const uint32_t values[] = {11, 22, 33, 44};
  require(write(fd, values, sizeof(values)) == sizeof(values));
  close(fd);
  {
    ReadOnlyMmio memory(4, 8, filename);
    require(memory.read32(4) == 22 && memory.read32(8) == 33);
    rejects([&] { memory.read32(0); });
    rejects([&] { memory.read32(5); });
    rejects([&] { memory.read32(12); });
    rejects([&] { memory.write32(4, 99); });
    require(memory.read32(4) == 22);
  }
  require(unlink(filename) == 0);
  rejects([&] { ReadOnlyMmio bad(1, 4); });
  rejects([&] { ReadOnlyMmio bad(0, 0); });
  std::cout << cases << " timing combinations, unstable reads, capabilities and read-only bounds passed\n";
}
