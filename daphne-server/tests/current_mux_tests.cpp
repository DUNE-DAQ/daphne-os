#include <array>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "server_controller/current_monitor.hpp"

using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("Current mux/protocol test failed"); }
template <typename F> void rejects(F f) { bool failed = false; try { f(); } catch (...) { failed = true; } require(failed); }
struct Mux : Mmio32 {
  uint32_t enable = 0, address = 0;
  unsigned writes = 0, fail_at = 0;
  std::vector<std::pair<uint64_t, uint32_t>> trace;
  uint32_t read32(uint64_t a) override {
    if (a == CurrentMuxTransaction::enable_address) return enable;
    require(a == CurrentMuxTransaction::select_address);
    return address;
  }
  void write32(uint64_t a, uint32_t v) override {
    trace.emplace_back(a, v);
    if (++writes == fail_at) throw std::runtime_error("Injected mux write failure");
    if (a == CurrentMuxTransaction::enable_address) { require(v < 3); enable = v; }
    else { require(a == CurrentMuxTransaction::select_address && enable == 0 && v < 4); address = v; }
  }
};
int main() {
  for (uint32_t channel = 0; channel < 40; ++channel) {
    const auto plan = current_channel_selection(channel);
    require(plan.afe == channel / 8 && plan.local_channel == channel % 8);
    require(plan.enable == (channel % 8 < 4 ? 1u : 2u) && plan.address == channel % 4);
    require(plan.adc_mux == 0x21 + 0x22 * (channel / 8));
    daphne::cmd_readCurrentMonitor req;
    req.set_physical_channel(channel);
    require(current_request_selection(req).physical_channel == channel);
    for (uint32_t old_en = 0; old_en < 3; ++old_en) for (uint32_t old_a = 0; old_a < 4; ++old_a) {
      Mux m; m.enable = old_en; m.address = old_a;
      { CurrentMuxTransaction t(m); require(m.writes == 0); t.select(channel); t.verify(channel);
        require(m.enable == plan.enable && m.address == plan.address); t.restore(); }
      require(m.enable == old_en && m.address == old_a && m.writes == 6);
    }
  }
  daphne::cmd_readCurrentMonitor req;
  rejects([&] { current_request_selection(req); }); // Explicit physical channel required, including zero.
  req.set_physical_channel(40);
  rejects([&] { current_request_selection(req); });
  req.set_physical_channel(0); req.set_currentmonitorchannel(1);
  rejects([&] { current_request_selection(req); });
  for (unsigned fail = 1; fail <= 6; ++fail) {
    Mux m; m.enable = 2; m.address = 3; m.fail_at = fail;
    rejects([&] { CurrentMuxTransaction t(m); t.select(0); t.restore(); });
    require(m.enable == 2 && m.address == 3); // Restoration retried after a transient failure.
  }
  { Mux m; m.enable = 3; rejects([&] { CurrentMuxTransaction t(m); }); require(m.writes == 0); }
  { Mux m; m.address = 4; rejects([&] { CurrentMuxTransaction t(m); }); require(m.writes == 0); }
  { Mux m; rejects([&] { CurrentMuxTransaction t(m); t.select(40); }); require(m.writes == 0); }
  { Mux m; rejects([&] { CurrentMuxTransaction t(m); t.select(5); throw std::runtime_error("ADC failed"); });
    require(m.enable == 0 && m.address == 0); }
  { Mux m; CurrentMuxTransaction t(m); t.select(0); m.address = 1;
    rejects([&] { t.verify(0); }); t.restore(); }

  ADS1261Sample sample; sample.id = 0x81; sample.status = 4; sample.input_mux = 0x21;
  sample.raw_code = -1; sample.differential_volts = -2.5 / 8388608; sample.observed_monotonic_ns = 123;
  daphne::cmd_readCurrentMonitor_response response, decoded;
  set_current_sample(response, sample);
  require(response.success() && response.quality() == daphne::CURRENT_MONITOR_GOOD);
  require(response.raw_code() == -1 && response.currentvalue() == 0xffffffff && response.has_differential_volts());
  require(!response.has_current_amperes() && response.current_quality() == daphne::CURRENT_MONITOR_UNAVAILABLE);
  require(decoded.ParseFromString(response.SerializeAsString()) && decoded.raw_code() == -1);
  for (const auto flags : {0u, 1u, 2u, 8u, 16u, 32u, 64u, 128u}) {
    sample.status = flags == 0 ? 0 : uint8_t(4 | flags);
    set_current_sample(response, sample);
    require(!response.success() && response.quality() == daphne::CURRENT_MONITOR_ERROR);
    require(response.has_raw_code() && !response.has_differential_volts() && response.currentvalue() == 0);
  }
  sample.status = 4; sample.saturated = true;
  set_current_sample(response, sample);
  require(response.quality() == daphne::CURRENT_MONITOR_SATURATED && !response.has_differential_volts());
  sample.saturated = false; sample.raw_code = 0; sample.differential_volts = 0;
  set_current_sample(response, sample);
  require(response.has_raw_code() && response.has_differential_volts() && response.differential_volts() == 0);
  std::cout << "40-channel selection, 480 restoration cases, failures, explicit addressing and ADC-quality wire tests passed\n";
}
