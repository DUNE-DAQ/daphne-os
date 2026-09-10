#include "server_controller/fpga_health.hpp"
#include "server_controller/native_timestamp.hpp"
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
daphne::HealthCheckState management_health(const daphne::ManagementNetworkObservation& n, uint64_t now) {
  if (!fresh(n.quality(), n.observed_monotonic_ns(), now) || !n.has_present()) return daphne::HEALTH_CHECK_UNKNOWN;
  if (!n.present() || (n.has_interface_up() && !n.interface_up()) || (n.has_running_flag() && !n.running_flag()))
    return daphne::HEALTH_CHECK_FAIL;
  if (!n.has_interface_up() || !n.has_running_flag()) return daphne::HEALTH_CHECK_UNKNOWN;
  const auto& link = n.link();
  if (!n.has_interface_index() || !link.has_interface_index() || !n.interface_index() ||
      link.interface_index() != n.interface_index() || !link.link_state_bracket_verified() ||
      !fresh(link.quality(), link.observed_monotonic_ns(), now) || !n.acquisition_started_monotonic_ns() ||
      link.acquisition_started_monotonic_ns() < n.acquisition_started_monotonic_ns() ||
      link.acquisition_started_monotonic_ns() > link.observed_monotonic_ns() ||
      link.observed_monotonic_ns() > n.observed_monotonic_ns()) return daphne::HEALTH_CHECK_UNKNOWN;
  const daphne::ManagementLinkObservation *state = nullptr, *carrier = nullptr;
  for (const auto& item : link.observations()) {
    auto** destination = item.metric() == daphne::MANAGEMENT_LINK_OPERSTATE ? &state :
                         item.metric() == daphne::MANAGEMENT_LINK_CARRIER ? &carrier : nullptr;
    if (!destination) continue;
    if (*destination || !fresh(item.quality(), item.observed_monotonic_ns(), now) ||
        item.acquisition_started_monotonic_ns() < link.acquisition_started_monotonic_ns() ||
        item.acquisition_started_monotonic_ns() > item.observed_monotonic_ns() ||
        item.observed_monotonic_ns() > link.observed_monotonic_ns()) return daphne::HEALTH_CHECK_UNKNOWN;
    *destination = &item;
  }
  if (!state || !carrier || !state->has_text_value() || !carrier->has_flag_value()) return daphne::HEALTH_CHECK_UNKNOWN;
  const auto& value = state->text_value();
  if (value != "unknown" && value != "notpresent" && value != "down" && value != "lowerlayerdown" &&
      value != "testing" && value != "dormant" && value != "up") return daphne::HEALTH_CHECK_UNKNOWN;
  if (!carrier->flag_value()) return daphne::HEALTH_CHECK_FAIL;
  if (value == "unknown") return daphne::HEALTH_CHECK_UNKNOWN;
  return value == "up" ? daphne::HEALTH_CHECK_PASS : daphne::HEALTH_CHECK_FAIL;
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
  const auto management = management_health(network, now);
  add("management_interface", management != daphne::HEALTH_CHECK_UNKNOWN, management == daphne::HEALTH_CHECK_PASS,
      "Selected interface present/admin-up/running with matching carrier-up and operational-up samples; unknown operstate is not a pass. No reachability or Hermes inference",
      network.observed_monotonic_ns());
  const auto& binding = s.board_identity();
  add("management_identity", fresh(daphne::MEASUREMENT_GOOD, binding.observed_monotonic_ns(), now) &&
      (binding.binding_state() == daphne::IDENTITY_BINDING_MATCH || binding.binding_state() == daphne::IDENTITY_BINDING_MISMATCH),
      binding.binding_state() == daphne::IDENTITY_BINDING_MATCH,
      "Observed controller/MAC/IPv4 match protected baseline; not assignment authentication or proof of network connectivity", binding.observed_monotonic_ns());
  const auto& live = ep.live_timestamp();
  const bool external_source = (ep.endpoint_clock_control_raw() & 4) != 0;
  bool source_context_ok = ep.endpoint_clock_selected() == external_source;
  for (const auto& sample : live.samples()) {
    if (sample.quality() == daphne::MEASUREMENT_GOOD &&
        sample.source() != (external_source ? daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS : daphne::NATIVE_TIMESTAMP_LOCAL_COUNTER))
      source_context_ok = false;
  }
  const bool host_bracket_ok = id.acquisition_started_monotonic_ns() != 0 &&
      id.acquisition_started_monotonic_ns() <= ep.observed_monotonic_ns() &&
      ep.observed_monotonic_ns() <= live.acquisition_started_monotonic_ns() &&
      live.observed_monotonic_ns() <= p.acquisition_started_monotonic_ns() &&
      p.acquisition_started_monotonic_ns() <= p.configuration_observed_monotonic_ns() &&
      p.configuration_observed_monotonic_ns() <= id.observed_monotonic_ns();
  const bool live_available = supports_live_timestamp(id.abi()) &&
      fresh(id.quality(), id.observed_monotonic_ns(), now) && id.has_matches_admitted_profile() && id.matches_admitted_profile() &&
      timing && source_context_ok && host_bracket_ok && live.identity_bracket_verified() &&
      fresh(live.quality(), live.observed_monotonic_ns(), now) && native_timestamp_pair_consistent(live);
  add("live_timestamp_progress", live_available, live.advancing(),
      "Two coherent same-source native samples must advance; local bench progress is not external timing readiness, frequency, epoch or acquisition alignment", live.observed_monotonic_ns());
  add("hermes_data_path", false, false, "SFP EEPROM/optical levels and configured identities do not prove PCS/link health, packet progress or receiver delivery");
  add("external_reset_epoch", false, false, "ABI-2 has no persistent reset/programming epoch; identical image reloads between samples can evade detection");
  result.set_state(failed ? daphne::FPGA_HEALTH_NOT_READY : unknown ? daphne::FPGA_HEALTH_UNKNOWN : daphne::FPGA_HEALTH_OBSERVED_OK);
  result.set_message(failed ? "One or more acquisition prerequisites fail; inspect named checks. This can be expected on the local-clock bench" :
      unknown ? "No failed observed prerequisite, but missing/stale evidence prevents a complete health conclusion" : "Declared sampled checks passed; not a continuous health guarantee");
  return result;
}
}
