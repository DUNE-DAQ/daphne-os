#include "server_controller/timing_status.hpp"

#include <stdexcept>
#include "server_controller/board_monitor.hpp"

namespace daphne_sc {
daphne::EndpointStatus read_timing_status(Mmio32& mmio) {
  auto read = [&] {
    std::array<uint32_t, 4> words;
    for (size_t i = 0; i < words.size(); ++i)
      words[i] = mmio.read32(kTimingRegisterBase + 4 * i);
    return words;
  };
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    const auto words = read();
    if (words != read()) continue;
    // Mapping verified against dual-ABI ep_axi.vhd at 3f17f1b, not the
    // overlapping identity addresses or captured timestamp words in v8 code.
    daphne::EndpointStatus status;
    status.set_endpoint_clock_control_raw(words[0]);
    status.set_endpoint_clock_status_raw(words[1]);
    status.set_endpoint_control_raw(words[2]);
    status.set_endpoint_status_raw(words[3]);
    status.set_endpoint_clock_selected((words[0] & 4) != 0);
    status.set_mmcm0_reset((words[0] & 1) != 0);
    status.set_mmcm1_reset((words[0] & 2) != 0);
    status.set_mmcm0_locked((words[1] & 1) != 0);
    status.set_mmcm1_locked((words[1] & 2) != 0);
    status.set_mmcm_locked((words[1] & 3) == 3);
    status.set_endpoint_reset((words[2] & 0x10000) != 0);
    status.set_fsm_state(words[3] & 15);
    status.set_timestamp_valid((words[3] & 16) != 0);
    status.set_ready(status.endpoint_clock_selected() && status.mmcm_locked() &&
                     !status.mmcm0_reset() && !status.mmcm1_reset() && !status.endpoint_reset() &&
                     status.fsm_state() == 8 && status.timestamp_valid());
    status.set_observation_quality(daphne::MEASUREMENT_GOOD);
    status.set_live_timestamp_quality(daphne::MEASUREMENT_UNAVAILABLE);
    status.set_observed_host_unix_ns(host_unix_time_ns());
    status.set_observed_monotonic_ns(monotonic_time_ns());
    status.set_message("Two matching sampled reads, not a hardware latch or continuous health guarantee. "
                       "Live timestamp is unavailable in this ABI; host wall clock is unverified");
    return status;
  }
  throw std::runtime_error("Timing registers changed across all three read attempts; retry");
}

void add_register_capabilities(daphne::SystemStatusSnapshot& status, GatewareMode mode) {
  auto add = [&](const char* name, bool supported, const char* reason) {
    auto* capability = status.add_capabilities();
    capability->set_name(name);
    capability->set_supported(supported);
    capability->set_reason(reason);
  };
  add("GatewareIdentity", true, "Common ABI-2 identity block at 0x940000F0..FC");
  add("TimingStatus", true, "Clock source, locks, resets, FSM and timestamp-valid at 0x84000000..0C");
  add("TriggerCounters", supports_trigger_counters(mode),
      supports_trigger_counters(mode) ? "Use request 320; 40 self-trigger channels" : "Not present in full-stream mode");
  add("LiveTimingTimestamp", false, "I273/TI001: capture-buffer words are not a coherent live timestamp");
  add("CommandDecoderMap", false, "I277: optical decoder wrapper output is not implemented");
  add("ProtocolErrorCount", false, "I281: optical register is hardwired zero, not a measured counter");
  add("CrateSlotDetectorReadback", false, "I058/I059/I061: legacy addresses overlap ABI-2 self-trigger controls");
  add("ChannelConfig.gain", true,
      "I315/C013: offset DAC x1/x2 -> AD5327 bit 13 = 0/1; 0 retains legacy x1. "
      "Explicit x1/x2 offset limits 2700/1500. Command support, not DAC readback or analog qualification");
  add("AMSTemperatures", true,
      "Read-only Linux IIO xilinx-ams Temp_LPD/Temp_FPD/Temp_PL; consult each reading's quality. "
      "SoC die sensors, not board ambient; host observation times, not conversion timestamps");
}
}
