#include "server_controller/fpga_health.hpp"
#include <cmath>

namespace daphne_sc {
namespace {
bool fresh(daphne::MeasurementQuality quality, uint64_t observed, uint64_t now) {
  return quality == daphne::MEASUREMENT_GOOD && observed != 0 && observed <= now &&
         now - observed <= kFpgaHealthMaximumAgeMs * 1000000;
}
bool config_fresh(const daphne::FpgaProgrammingStatus& p, uint64_t now) {
  return p.has_configuration_status_raw() &&
         fresh(p.configuration_quality(), p.configuration_observed_monotonic_ns(), now);
}
}

bool fpga_status_mmio_prerequisites(const daphne::FpgaProgrammingStatus& p, uint64_t now) {
  return fresh(p.manager_quality(), p.manager_observed_monotonic_ns(), now) &&
      p.manager_state() == "operating" && !p.has_manager_error_raw() && config_fresh(p, now) &&
      (p.configuration_status_raw() & kFpgaStartupRequiredMask) == kFpgaStartupRequiredMask &&
      (p.configuration_status_raw() & kFpgaConfigurationErrorMask) == 0;
}
bool fpga_programming_known_bad(const daphne::FpgaProgrammingStatus& p, uint64_t now) {
  return (fresh(p.manager_quality(), p.manager_observed_monotonic_ns(), now) &&
          ((p.manager_state() != "operating" && p.manager_state() != "unknown") || p.has_manager_error_raw())) ||
      (config_fresh(p, now) &&
       ((p.configuration_status_raw() & kFpgaStartupRequiredMask) != kFpgaStartupRequiredMask ||
        (p.configuration_status_raw() & kFpgaConfigurationErrorMask) != 0));
}

daphne::FpgaHealthAssessment assess_fpga_health(const daphne::SystemStatusSnapshot& s,
    const daphne::ManagementNetworkObservation& network, uint64_t now) {
  daphne::FpgaHealthAssessment result;
  result.set_scope("Externally timed acquisition prerequisites, sampled evidence only; not a run permit or safety interlock");
  result.set_evaluated_monotonic_ns(now);
  result.set_maximum_observation_age_ms(kFpgaHealthMaximumAgeMs);
  bool failed = false, unknown = false;
  auto add = [&](const char* name, bool available, bool pass, const char* message, uint64_t observed = 0) {
    auto* check = result.add_checks();
    check->set_name(name);
    check->set_state(!available ? daphne::HEALTH_CHECK_UNKNOWN : pass ? daphne::HEALTH_CHECK_PASS : daphne::HEALTH_CHECK_FAIL);
    check->set_message(message);
    check->set_observed_monotonic_ns(observed);
    unknown |= !available;
    failed |= available && !pass;
  };
  const auto& p = s.fpga_programming();
  add("kernel_programming", fresh(p.manager_quality(), p.manager_observed_monotonic_ns(), now) && p.manager_state() != "unknown",
      p.manager_state() == "operating" && !p.has_manager_error_raw(), "Cached kernel programming state/error; not a live fabric heartbeat", p.manager_observed_monotonic_ns());
  const auto raw = p.configuration_status_raw();
  add("configuration_error_flags", config_fresh(p, now), !(raw & kFpgaConfigurationErrorMask),
      "STAT CRC, packet, authentication/security, IDCODE and over-temperature flags; zero flags do not prove continuous scrubbing", p.configuration_observed_monotonic_ns());
  add("configuration_startup", config_fresh(p, now), (raw & kFpgaStartupRequiredMask) == kFpgaStartupRequiredMask,
      "STAT DONE/INIT internal and pin levels, GHIGH_B, GWE, GTS_CFG_B and EOS", p.configuration_observed_monotonic_ns());
  add("fabric_clock_locks", config_fresh(p, now), (raw & 4) != 0,
      "STAT global MMCM/PLL lock indication; unused locks read as one, not a frequency or data-path measurement", p.configuration_observed_monotonic_ns());
  const auto& id = s.gateware_identity();
  add("admitted_gateware", fresh(id.quality(), id.observed_monotonic_ns(), now) && id.has_matches_admitted_profile(),
      id.matches_admitted_profile(), "Identity sampled around timing reads; ABI/mode/build must match process admission", id.observed_monotonic_ns());
  const auto& ep = s.endpoint();
  const bool timing = fresh(ep.observation_quality(), ep.observed_monotonic_ns(), now);
  add("timing_clock_locks", timing, ep.mmcm0_locked() && ep.mmcm1_locked(),
      "Both DAPHNE timing MMCM lock bits; not a clock-frequency measurement", ep.observed_monotonic_ns());
  add("timing_resets_released", timing, !ep.mmcm0_reset() && !ep.mmcm1_reset() && !ep.endpoint_reset(),
      "Three exposed reset requests; not every internal reset domain", ep.observed_monotonic_ns());
  add("external_timing_ready", timing, ep.ready(),
      "Endpoint clock source, both locks, released resets, FSM 8 and timestamp-valid required; local-clock bench operation deliberately fails this requirement", ep.observed_monotonic_ns());
  const auto& runtime = s.server_state();
  add("front_end_configuration", runtime.success() && fresh(daphne::MEASUREMENT_GOOD, runtime.observed_monotonic_ns(), now),
      runtime.applied_configuration_valid() && !runtime.configuration_in_progress() && !runtime.applied_configuration_hash().empty(),
      "Executed complete FE configuration evidence; not hardware readback or analog calibration", runtime.observed_monotonic_ns());
  const daphne::TemperatureStatus* temperature = nullptr;
  bool duplicate = false;
  for (const auto& candidate : s.temperatures()) if (candidate.name() == "Temp_PL") {
    duplicate |= temperature != nullptr;
    temperature = &candidate;
  }
  const bool thermal = temperature && !duplicate && temperature->valid() &&
      std::isfinite(temperature->temperature_c()) &&
      fresh(temperature->quality(), temperature->observed_monotonic_ns(), now) &&
      temperature->alarm().state() >= daphne::TEMPERATURE_ALARM_GOOD &&
      temperature->alarm().state() <= daphne::TEMPERATURE_ALARM_CRITICAL;
  add("pl_die_temperature", thermal, thermal && temperature->alarm().state() == daphne::TEMPERATURE_ALARM_GOOD,
      "PL die observation against provisional startup alarm thresholds; warning or above fails this conservative checklist", temperature ? temperature->observed_monotonic_ns() : 0);
  add("management_interface", fresh(network.quality(), network.observed_monotonic_ns(), now) && network.has_present() &&
      (!network.present() || (network.has_interface_up() && network.has_running_flag())),
      network.present() && network.interface_up() && network.running_flag(),
      "Selected approved management interface present/up/running; no private addresses exported, no reachability or Hermes-link inference", network.observed_monotonic_ns());
  const auto& binding = s.board_identity();
  add("management_identity", fresh(daphne::MEASUREMENT_GOOD, binding.observed_monotonic_ns(), now) &&
      (binding.binding_state() == daphne::IDENTITY_BINDING_MATCH || binding.binding_state() == daphne::IDENTITY_BINDING_MISMATCH),
      binding.binding_state() == daphne::IDENTITY_BINDING_MATCH,
      "Observed controller/MAC/IPv4 match protected baseline; not assignment authentication or proof of network connectivity", binding.observed_monotonic_ns());
  add("live_timestamp_progress", false, false, "ABI-2 lacks a coherent live timestamp export; capture timestamps are not a live heartbeat");
  add("hermes_data_path", false, false, "SFP EEPROM/optical levels and configured identities do not prove PCS/link health, packet progress or receiver delivery");
  add("external_reset_epoch", false, false, "ABI-2 has no persistent reset/programming epoch; identical image reloads between samples can evade detection");
  result.set_state(failed ? daphne::FPGA_HEALTH_NOT_READY : unknown ? daphne::FPGA_HEALTH_UNKNOWN : daphne::FPGA_HEALTH_OBSERVED_OK);
  result.set_message(failed ? "One or more acquisition prerequisites fail; inspect named checks. This can be expected on the local-clock bench" :
      unknown ? "No failed observed prerequisite, but missing/stale evidence prevents a complete health conclusion" : "Declared sampled checks passed; not a continuous health guarantee");
  return result;
}
}
