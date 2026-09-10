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
    status.set_endpoint_address(words[2] & 0xffff);
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
                       "Live timestamp, when supported, is collected separately; host wall clock is unverified");
    return status;
  }
  throw std::runtime_error("Timing registers changed across all three read attempts; retry");
}

void add_register_capabilities(daphne::SystemStatusSnapshot& status, GatewareMode mode,
                              std::optional<uint32_t> admitted_abi) {
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
  const bool native_timestamp = admitted_abi && supports_live_timestamp(*admitted_abi);
  add("LiveTimingTimestamp", native_timestamp, native_timestamp ?
      "ABI 2.1/2.2 native-clock diagnostic snapshot/progress comparison; no acquisition alignment, epoch or frequency qualification. Inspect per-observation quality" :
      "I273/TI001: ABI 2.1/2.2 required for native snapshots; no probes of aliased ABI 2.0 offsets. Capture-buffer words are not a live timestamp");
  add("CommandDecoderMap", false, "I277: optical decoder wrapper output is not implemented");
  const bool protocol_errors = admitted_abi && supports_protocol_error_history(*admitted_abi);
  add("ProtocolErrorCount", protocol_errors, protocol_errors ?
      "ABI 2.2 PS snapshot of saturating RX-parser error episodes since an unobserved common platform reset; inspect quality/scope, not current health. Optical 0x76 remains separate" :
      "I281: exact ABI 2.2 required for PS parser history; no diagnostic probes. Legacy optical register is hardwired zero, not a measured counter");
  add("CrateSlotDetectorReadback", false, "I058/I059/I061: legacy addresses overlap ABI-2 self-trigger controls");
  add("ChannelConfig.gain", true,
      "I315/C013: offset DAC x1/x2 -> AD5327 bit 13 = 0/1; 0 retains legacy x1. "
      "Explicit x1/x2 offset limits 2700/1500. Command support, not DAC readback or analog qualification");
  add("AMSTemperatures", true,
      "Read-only Linux IIO xilinx-ams Temp_LPD/Temp_FPD/Temp_PL; consult each reading's quality. "
      "SoC die sensors, not board ambient; host observation times, not conversion timestamps");
  add("CarrierTemperature", true,
      "Schematic U9 MCP9808, PS I2C1 ff030000 address 0x18; identity and shutdown checked before data. "
      "Named reading and GeneralInfo.temperature; quality is not a thermal alarm/interlock");
  add("RuntimeServices", true,
      "Eight allow-listed systemd units, host metadata and configured population/app; no journal/env/command-line export. "
      "Service active/success does not establish hardware health");
  add("ServerBookkeeping", true,
      "Request 326 remains responsive during serialized hardware work; heartbeat, correlated configuration result and canonical successful evidence. "
      "Validity tracks known local invalidations, not all external resets or analog calibration");
  add("TemperatureAlarms", true,
      "Named temperature observations carry active startup thresholds and Good/Warning/High/Critical/Missing/Invalid/Stale evaluation. "
      "Provisional monitoring limits only; no power action, sensor comparator changes or protection permit");
  add("CurrentMonitorRaw", true,
      "Request 244 with explicit physical_channel 0..39: carrier mux + identified kernel SPI ADS1261, CRC/status/DRDY and restoration checks. "
      "Measurement performs ADC/mux writes only. Raw code and nominal differential volts; calibrated current requires an approved calibration");
  add("SFPDiagnostics", true,
      "Opt-in ReadSystemStatus.include_sfp_diagnostics: six schematic routes on PL I2C 9c000000, mux 0x72, A0/A2 EEPROM only. "
      "Checksums, calibration/status and mux restoration; no TX/module-control/reset writes. Failed I2C is not evidence of absence or a wiring diagnosis");
  add("DatabaseIdentityAssignments", true,
      "Optional private startup artifact supplies source-referenced assignments, not FPGA readback. "
      "Management controller/MAC/IPv4 are compared with a protected host baseline; private values require include_identity_details. "
      "No implicit network/analog writes, physical-link inference or assignment authentication");
  add("FpgaHealthEvidence", true,
      "Sampled ZynqMP configuration STAT, bracketed gateware identity/timing and named acquisition-prerequisite checklist. "
      "Unknown evidence cannot pass; no run permit, automatic recovery, continuous integrity or Hermes delivery claim");
  add("OnboardRegulatorTelemetry", true,
      "Opt-in include_regulator_telemetry: four fixed schematic PJT004 rails on identified PL I2C with mandatory PEC. "
      "Bracketed module/mode identity, raw and decoded VOUT/IOUT/TEMPERATURE_2, host alarms, factory calibration raw and retained status flags. "
      "No VIN, qualified manufacturer status, regulator writes, network changes or overall rail-health claim");
  add("HostResources", true,
      "I088/I101-I104: fixed proc uptime/load/MemAvailable and root statvfs; typed values with per-source quality/times. "
      "Free and unprivileged-available bytes are distinct; no memory/disk alarm, verified UTC or operational-health inference");
  add("HostClock", true,
      "I086/I087/I090: local realtime/UTC and suspend-inclusive derived boot estimate, plus read-only kernel discipline state. "
      "Separate monotonic brackets and quality; no clock setting, NTP peer/offset, verified UTC or FPGA-time inference");
}
}
