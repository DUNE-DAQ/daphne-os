#include "server_controller/fpga_health.hpp"
#include "server_controller/afe_global.hpp"
#include "server_controller/board_monitor.hpp"
#include "server_controller/native_timestamp.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <unistd.h>

namespace {
using namespace daphne_sc;
namespace fs = std::filesystem;
constexpr uint64_t now = 10000000000;
void require(bool ok) { if (!ok) throw std::runtime_error("FPGA health test failed"); }
daphne::FpgaProgrammingStatus good_programming() {
  daphne::FpgaProgrammingStatus p;
  p.set_manager_quality(daphne::MEASUREMENT_GOOD);
  p.set_manager_state("operating");
  p.set_manager_observed_monotonic_ns(now);
  p.set_configuration_quality(daphne::MEASUREMENT_GOOD);
  p.set_configuration_status_raw(0x16907ffc); // Observed board STAT, not a fabricated all-ones word.
  p.set_configuration_observed_monotonic_ns(now);
  return p;
}
daphne::SystemStatusSnapshot good_status() {
  daphne::SystemStatusSnapshot s;
  s.set_success(true);
  *s.mutable_fpga_programming() = good_programming();
  s.mutable_fpga_programming()->set_acquisition_started_monotonic_ns(now - 200);
  auto* id = s.mutable_gateware_identity();
  id->set_magic(kGatewareIdentityMagic); id->set_abi(kGatewareAbiV2);
  id->set_variant(1); id->set_build_id(0x3f17f1b);
  id->set_acquisition_started_monotonic_ns(now - 1000);
  id->set_quality(daphne::MEASUREMENT_GOOD);
  id->set_matches_admitted_profile(true);
  id->set_observed_monotonic_ns(now);
  auto* afe = s.mutable_afe_global();
  afe->set_quality(daphne::MEASUREMENT_GOOD);
  afe->set_global_control_raw(2); afe->set_bias_enable_raw(1);
  afe->set_power_state_bit(true); afe->set_reset_asserted(false);
  afe->set_busy_afe0(false); afe->set_busy_afe12(false); afe->set_busy_afe34(false);
  afe->set_bias_enabled(true); afe->set_identity_bracket_verified(true);
  afe->set_source(kAfeGlobalSource); afe->set_message("private-must-not-be-exported");
  afe->set_maximum_acquisition_ms(kAfeGlobalMaximumAcquisitionMs);
  afe->set_acquisition_started_monotonic_ns(now - 500); afe->set_observed_monotonic_ns(now - 400);
  auto* ep = s.mutable_endpoint();
  ep->set_observation_quality(daphne::MEASUREMENT_GOOD);
  ep->set_observed_monotonic_ns(now);
  ep->set_mmcm0_locked(true);
  ep->set_mmcm1_locked(true);
  ep->set_ready(true);
  auto* runtime = s.mutable_server_state();
  runtime->set_success(true);
  runtime->set_observed_monotonic_ns(now);
  runtime->set_applied_configuration_valid(true);
  runtime->set_applied_configuration_hash(std::string(64, 'a'));
  auto* temp = s.add_temperatures();
  temp->set_name("Temp_PL");
  temp->set_quality(daphne::MEASUREMENT_GOOD);
  temp->set_valid(true);
  temp->set_temperature_c(40);
  temp->set_observed_monotonic_ns(now);
  temp->mutable_alarm()->set_state(daphne::TEMPERATURE_ALARM_GOOD);
  s.mutable_board_identity()->set_binding_state(daphne::IDENTITY_BINDING_MATCH);
  s.mutable_board_identity()->set_observed_monotonic_ns(now);
  return s;
}
daphne::ManagementNetworkObservation good_network() {
  daphne::ManagementNetworkObservation n;
  n.set_quality(daphne::MEASUREMENT_GOOD);
  n.set_observed_monotonic_ns(now);
  n.set_present(true);
  n.set_interface_up(true);
  n.set_running_flag(true);
  n.set_interface_index(3);
  n.set_acquisition_started_monotonic_ns(now - 100);
  auto* link = n.mutable_link();
  link->set_quality(daphne::MEASUREMENT_GOOD); link->set_interface_index(3);
  link->set_acquisition_started_monotonic_ns(now - 90); link->set_observed_monotonic_ns(now - 10);
  link->set_link_state_bracket_verified(true);
  auto* state = link->add_observations();
  state->set_metric(daphne::MANAGEMENT_LINK_OPERSTATE); state->set_text_value("up");
  auto* carrier = link->add_observations();
  carrier->set_metric(daphne::MANAGEMENT_LINK_CARRIER); carrier->set_flag_value(true);
  for (auto& item : *link->mutable_observations()) {
    item.set_quality(daphne::MEASUREMENT_GOOD);
    item.set_acquisition_started_monotonic_ns(now - 80); item.set_observed_monotonic_ns(now - 70);
  }
  n.set_mac_address("private-must-not-be-exported");
  return n;
}
void native_progress(daphne::SystemStatusSnapshot& status, bool advancing = true) {
  status.mutable_gateware_identity()->set_abi(kGatewareAbiV21);
  status.mutable_gateware_identity()->set_acquisition_started_monotonic_ns(now - 2000);
  status.mutable_endpoint()->set_observed_monotonic_ns(now - 1500);
  status.mutable_fpga_programming()->set_acquisition_started_monotonic_ns(now);
  status.mutable_endpoint()->set_endpoint_clock_selected(true);
  status.mutable_endpoint()->set_endpoint_clock_control_raw(4);
  auto* live = status.mutable_endpoint()->mutable_live_timestamp();
  live->set_quality(daphne::MEASUREMENT_GOOD);
  live->set_feature_abi(kNativeTimestampAbi); live->set_feature_abi_after(kNativeTimestampAbi);
  live->set_timeout_cycles(1024); live->set_timeout_cycles_after(1024);
  live->set_maximum_attempts_per_sample(kNativeTimestampMaximumAttempts);
  live->set_maximum_acquisition_ms(kNativeTimestampMaximumAcquisitionMs);
  live->set_acquisition_started_monotonic_ns(now - 1000);
  live->set_observed_monotonic_ns(now);
  live->set_identity_bracket_verified(true);
  live->set_delta_ticks(advancing ? 100 : 0); live->set_advancing(advancing);
  for (unsigned i = 0; i < 2; ++i) {
    auto* sample = live->add_samples();
    sample->set_quality(daphne::MEASUREMENT_GOOD);
    sample->set_request_status_raw(0x13); sample->set_status_raw(0x13);
    sample->set_sequence_before(i); sample->set_sequence_first(i + 1); sample->set_sequence_after(i + 1);
    sample->set_low_raw(i && advancing ? 200 : 100); sample->set_high_raw(0);
    sample->set_timestamp_ticks(sample->low_raw()); sample->set_source(daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS);
    sample->set_acquisition_started_monotonic_ns(now - 800 + i * 300);
    sample->set_observed_monotonic_ns(now - 600 + i * 300);
    sample->set_sample_index(i); sample->set_attempt_index(1);
  }
}
daphne::HealthCheckState check(const daphne::FpgaHealthAssessment& health, const std::string& name) {
  for (const auto& c : health.checks()) if (c.name() == name) return c.state();
  throw std::runtime_error("Missing health check");
}
void afe_reset_tests() {
  for (auto abi : {kGatewareAbiV2, kGatewareAbiV21, kGatewareAbiV22})
    for (uint32_t variant : {1U, 2U}) for (uint32_t raw = 0; raw < 32; ++raw)
      for (uint32_t bias : {0U, 1U}) {
        auto s = good_status();
        s.mutable_gateware_identity()->set_abi(abi); s.mutable_gateware_identity()->set_variant(variant);
        auto* r = s.mutable_afe_global();
        r->set_global_control_raw(raw); r->set_bias_enable_raw(bias);
        r->set_reset_asserted(raw & 1); r->set_power_state_bit(raw & 2);
        r->set_busy_afe0(raw & 4); r->set_busy_afe12(raw & 8); r->set_busy_afe34(raw & 16);
        r->set_bias_enabled(bias);
        const auto health = assess_fpga_health(s, good_network(), now);
        require(check(health, "afe_reset_released") ==
            ((raw & 1) ? daphne::HEALTH_CHECK_FAIL : daphne::HEALTH_CHECK_PASS));
        require(health.state() == ((raw & 1) ? daphne::FPGA_HEALTH_NOT_READY : daphne::FPGA_HEALTH_UNKNOWN));
        for (const auto& c : health.checks()) if (c.name() == "afe_reset_released")
          require(c.observed_monotonic_ns() == r->observed_monotonic_ns());
        require(health.SerializeAsString().find("private-must-not-be-exported") == std::string::npos);
      }
  for (unsigned mutation = 0; mutation < 40; ++mutation) {
    auto s = good_status();
    auto* r = s.mutable_afe_global(); auto* id = s.mutable_gateware_identity();
    auto* p = s.mutable_fpga_programming();
    switch (mutation) {
      case 0: s.clear_afe_global(); break;
      case 1: r->clear_reset_asserted(); break;
      case 2: r->clear_global_control_raw(); break;
      case 3: r->clear_bias_enable_raw(); break;
      case 4: r->clear_bias_enabled(); break;
      case 5: r->clear_busy_afe0(); break;
      case 6: r->clear_busy_afe12(); break;
      case 7: r->clear_busy_afe34(); break;
      case 8: r->clear_power_state_bit(); break;
      case 9: r->set_reset_asserted(true); break;
      case 10: r->set_global_control_raw(34); break;
      case 11: r->set_bias_enable_raw(3); break;
      case 12: r->set_quality(daphne::MEASUREMENT_ERROR); break;
      case 13: r->set_quality(daphne::MEASUREMENT_STALE); break;
      case 14: r->set_quality(daphne::MEASUREMENT_UNAVAILABLE); break;
      case 15: r->set_identity_bracket_verified(false); break;
      case 16: r->set_source("private-invalid-source"); break;
      case 17: r->clear_message(); break;
      case 18: r->set_maximum_acquisition_ms(101); break;
      case 19: r->set_acquisition_started_monotonic_ns(0); break;
      case 20: r->set_acquisition_started_monotonic_ns(now - 1001); break;
      case 21: r->set_acquisition_started_monotonic_ns(now - 399); break;
      case 22: r->set_observed_monotonic_ns(now - 199); break;
      case 23: id->clear_acquisition_started_monotonic_ns(); break;
      case 24: id->set_matches_admitted_profile(false); break;
      case 25: id->clear_matches_admitted_profile(); break;
      case 26: id->set_quality(daphne::MEASUREMENT_ERROR); break;
      case 27: id->set_magic(0); break;
      case 28: id->set_abi(0x20003); break;
      case 29: id->set_variant(3); break;
      case 30: id->set_build_id(0xf1234567); break;
      case 31: id->set_observed_monotonic_ns(now + 1); break;
      case 32: p->set_manager_state("write"); break;
      case 33: p->set_manager_error_raw(0); break;
      case 34: p->set_configuration_status_raw(0x16907ffd); break;
      case 35: p->clear_configuration_status_raw(); break;
      case 36: p->set_manager_observed_monotonic_ns(now - 201); break;
      case 37: p->set_configuration_observed_monotonic_ns(now - 1); break;
      case 38: p->set_configuration_observed_monotonic_ns(now + 1); break;
      case 39: s.set_success(false); break;
    }
    const auto health = assess_fpga_health(s, good_network(), now);
    require(check(health, "afe_reset_released") == daphne::HEALTH_CHECK_UNKNOWN);
    require(health.SerializeAsString().find("private-invalid-source") == std::string::npos);
  }
  auto s = good_status();
  const auto sample = s.afe_global().observed_monotonic_ns();
  require(check(assess_fpga_health(s, {}, sample + 5000000000), "afe_reset_released") == daphne::HEALTH_CHECK_PASS);
  require(check(assess_fpga_health(s, {}, sample + 5000000001), "afe_reset_released") == daphne::HEALTH_CHECK_UNKNOWN);
  s.mutable_gateware_identity()->set_acquisition_started_monotonic_ns(now - 200000000);
  s.mutable_afe_global()->set_acquisition_started_monotonic_ns(sample - 100000000);
  require(check(assess_fpga_health(s, {}, now), "afe_reset_released") == daphne::HEALTH_CHECK_PASS);
  s.mutable_afe_global()->set_acquisition_started_monotonic_ns(sample - 100000001);
  require(check(assess_fpga_health(s, {}, now), "afe_reset_released") == daphne::HEALTH_CHECK_UNKNOWN);
}
void write(const fs::path& path, const std::string& bytes) {
  fs::create_directories(path.parent_path());
  std::ofstream f(path, std::ios::binary);
  f << bytes;
  require(bool(f));
}
void fixture(const fs::path& manager) {
  write(manager / "name", "Xilinx ZynqMP FPGA Manager\n");
  write(manager / "state", "operating\n");
  write(manager / "device/status", "0x16907ffc\n");
  write(manager / "device/of_node/compatible", std::string("xlnx,zynqmp-pcap-fpga") + '\0');
  write(manager / "status", ""); // Empty class status must NOT turn into a measured zero.
}
void collector_tests() {
  char name[] = "/tmp/daphne-fpga-health-XXXXXX";
  require(mkdtemp(name) != nullptr);
  const fs::path root(name), manager = root / "fpga7";
  struct Cleanup { fs::path path; ~Cleanup() { fs::remove_all(path); } } cleanup{root};
  auto p = read_fpga_programming_status(root);
  require(p.manager_quality() == daphne::MEASUREMENT_UNAVAILABLE && !p.has_configuration_status_raw());
  fixture(manager);
  p = read_fpga_programming_status(root);
  require(p.configuration_status_raw() == 0x16907ffc && p.configuration_quality() == daphne::MEASUREMENT_GOOD);
  require(fpga_status_mmio_prerequisites(p, monotonic_time_ns()));
  for (const auto* malformed : {"", "0", "0x", "0x100000000", "0x123garbage", "0x-1", " 0x123", "0x123\ntrailing"}) {
    write(manager / "device/status", malformed);
    p = read_fpga_programming_status(root);
    require(p.configuration_quality() == daphne::MEASUREMENT_ERROR && !p.has_configuration_status_raw());
  }
  write(manager / "device/status", "0x0\n");
  p = read_fpga_programming_status(root);
  require(p.has_configuration_status_raw() && p.configuration_status_raw() == 0 && fpga_programming_known_bad(p, monotonic_time_ns()));
  for (const auto* state : {"write", "reset", "power off", "unknown"}) {
    write(manager / "state", state);
    p = read_fpga_programming_status(root);
    require(p.manager_quality() == daphne::MEASUREMENT_GOOD && !p.has_configuration_status_raw());
    require(!fpga_status_mmio_prerequisites(p, monotonic_time_ns()));
  }
  for (const auto& state : {std::string(513, 'a'), std::string("operating\nsecret")}) {
    write(manager / "state", state);
    p = read_fpga_programming_status(root);
    require(p.manager_quality() == daphne::MEASUREMENT_ERROR && p.manager_state().empty());
  }
  fixture(manager);
  write(manager / "state", "write error: 0xffffffea\n");
  p = read_fpga_programming_status(root);
  require(p.manager_state() == "write error" && p.manager_error_raw() == 0xffffffea &&
          fpga_programming_known_bad(p, monotonic_time_ns()) && !p.has_configuration_status_raw());
  fixture(manager);
  fixture(root / "fpga9");
  p = read_fpga_programming_status(root);
  require(p.manager_quality() == daphne::MEASUREMENT_ERROR && !p.has_configuration_status_raw());
}
}

int main() {
  afe_reset_tests();
  using namespace daphne_sc;
  collector_tests();
  require(fpga_status_mmio_prerequisites(good_programming(), now));
  require(!fpga_programming_known_bad(good_programming(), now));
  for (unsigned bit = 0; bit < 32; ++bit) {
    auto p = good_programming();
    if (kFpgaConfigurationErrorMask & (1u << bit)) {
      p.set_configuration_status_raw(p.configuration_status_raw() | (1u << bit));
      require(!fpga_status_mmio_prerequisites(p, now) && fpga_programming_known_bad(p, now));
    }
    if (kFpgaStartupRequiredMask & (1u << bit)) {
      p.set_configuration_status_raw(p.configuration_status_raw() & ~(1u << bit));
      require(!fpga_status_mmio_prerequisites(p, now) && fpga_programming_known_bad(p, now));
    }
  }
  for (auto timestamp : {uint64_t(0), now + 1, now - 5000000001}) {
    auto p = good_programming();
    p.set_configuration_observed_monotonic_ns(timestamp);
    require(!fpga_status_mmio_prerequisites(p, now) && !fpga_programming_known_bad(p, now));
  }
  auto status = good_status();
  const auto network = good_network();
  auto health = assess_fpga_health(status, network, now);
  require(health.checks_size() == 16 && health.state() == daphne::FPGA_HEALTH_UNKNOWN);
  unsigned passes = 0, unknowns = 0;
  for (const auto& c : health.checks()) {
    passes += c.state() == daphne::HEALTH_CHECK_PASS;
    unknowns += c.state() == daphne::HEALTH_CHECK_UNKNOWN;
  }
  require(passes == 13 && unknowns == 3);
  for (auto abi : {kGatewareAbiV21, kGatewareAbiV22}) for (bool advancing : {false, true}) {
    auto native = good_status(); native_progress(native, advancing);
    native.mutable_gateware_identity()->set_abi(abi);
    const auto measured = assess_fpga_health(native, network, now);
    require(check(measured, "live_timestamp_progress") == (advancing ? daphne::HEALTH_CHECK_PASS : daphne::HEALTH_CHECK_FAIL));
    require(measured.state() != daphne::FPGA_HEALTH_OBSERVED_OK); // Hermes and reset epoch remain unknown.
    // Historical parser events are reported separately, not inferred to be a
    // current failure (and a zero history is not a proof of current health).
    for (uint32_t count : {0U, 7U, UINT32_MAX}) {
      auto* history = native.mutable_endpoint()->mutable_protocol_errors();
      history->set_quality(daphne::MEASUREMENT_GOOD); history->set_count(count);
      require(assess_fpga_health(native, network, now).SerializeAsString() == measured.SerializeAsString());
    }
  }
  for (unsigned mutation = 0; mutation < 11; ++mutation) {
    auto native = good_status(); native_progress(native);
    auto* live = native.mutable_endpoint()->mutable_live_timestamp();
    switch (mutation) {
      case 0: live->set_identity_bracket_verified(false); break;
      case 1: live->set_observed_monotonic_ns(now - 5000000001); break;
      case 2: live->set_quality(daphne::MEASUREMENT_ERROR); break;
      case 3: live->set_delta_ticks(999); break;
      case 4: native.mutable_gateware_identity()->set_abi(kGatewareAbiV2); break;
      case 5: native.mutable_endpoint()->set_endpoint_clock_selected(false); break;
      case 6: live->mutable_samples(0)->clear_timestamp_ticks(); break;
      case 7: native.mutable_endpoint()->set_endpoint_clock_control_raw(0); break;
      case 8: native.mutable_gateware_identity()->set_acquisition_started_monotonic_ns(now); break;
      case 9: native.mutable_fpga_programming()->set_acquisition_started_monotonic_ns(now - 1); break;
      case 10: native.mutable_endpoint()->set_observed_monotonic_ns(now); break;
    }
    require(check(assess_fpga_health(native, network, now), "live_timestamp_progress") == daphne::HEALTH_CHECK_UNKNOWN);
  }
  require(health.SerializeAsString().find("private-must-not-be-exported") == std::string::npos);
  require(assess_fpga_health({}, {}, now).state() == daphne::FPGA_HEALTH_UNKNOWN);
  status.mutable_endpoint()->set_ready(false);
  health = assess_fpga_health(status, network, now);
  require(health.state() == daphne::FPGA_HEALTH_NOT_READY && check(health, "external_timing_ready") == daphne::HEALTH_CHECK_FAIL);
  status = good_status();
  status.mutable_gateware_identity()->set_matches_admitted_profile(false);
  require(check(assess_fpga_health(status, network, now), "admitted_gateware") == daphne::HEALTH_CHECK_FAIL);
  status.mutable_gateware_identity()->set_quality(daphne::MEASUREMENT_ERROR);
  require(check(assess_fpga_health(status, network, now), "admitted_gateware") == daphne::HEALTH_CHECK_UNKNOWN);
  status = good_status();
  status.mutable_server_state()->set_applied_configuration_valid(false);
  require(check(assess_fpga_health(status, network, now), "front_end_configuration") == daphne::HEALTH_CHECK_FAIL);
  status = good_status();
  status.mutable_temperatures(0)->mutable_alarm()->set_state(daphne::TEMPERATURE_ALARM_WARNING);
  require(check(assess_fpga_health(status, network, now), "pl_die_temperature") == daphne::HEALTH_CHECK_FAIL);
  status.mutable_temperatures(0)->set_temperature_c(std::numeric_limits<double>::quiet_NaN());
  require(check(assess_fpga_health(status, network, now), "pl_die_temperature") == daphne::HEALTH_CHECK_UNKNOWN);
  auto absent = network;
  absent.set_present(false);
  absent.clear_interface_up();
  absent.clear_running_flag();
  require(check(assess_fpga_health(good_status(), absent, now), "management_interface") == daphne::HEALTH_CHECK_FAIL);
  for (unsigned mutation = 0; mutation < 13; ++mutation) {
    auto n = network;
    auto* link = n.mutable_link();
    switch (mutation) {
      case 0: n.clear_link(); break;
      case 1: link->set_link_state_bracket_verified(false); break;
      case 2: link->set_interface_index(4); break;
      case 3: link->set_quality(daphne::MEASUREMENT_ERROR); break;
      case 4: link->mutable_observations(0)->set_text_value("unknown"); break;
      case 5: link->mutable_observations(0)->set_text_value("PRIVATE-invalid-state"); break;
      case 6: link->mutable_observations(1)->clear_value(); break;
      case 7: *link->add_observations() = link->observations(0); break;
      case 8: link->mutable_observations(0)->set_quality(daphne::MEASUREMENT_UNAVAILABLE); break;
      case 9: link->set_observed_monotonic_ns(now + 1); break;
      case 10: link->mutable_observations(1)->set_observed_monotonic_ns(now); break;
      case 11: n.clear_acquisition_started_monotonic_ns(); break;
      case 12: link->mutable_observations(0)->set_acquisition_started_monotonic_ns(now); break;
    }
    const auto h = assess_fpga_health(good_status(), n, now);
    require(check(h, "management_interface") == daphne::HEALTH_CHECK_UNKNOWN);
    require(h.SerializeAsString().find("PRIVATE") == std::string::npos);
  }
  for (unsigned mutation = 0; mutation < 4; ++mutation) {
    auto n = network;
    if (mutation == 0) n.set_interface_up(false);
    if (mutation == 1) n.set_running_flag(false);
    if (mutation == 2) n.mutable_link()->mutable_observations(1)->set_flag_value(false);
    if (mutation == 3) n.mutable_link()->mutable_observations(0)->set_text_value("dormant");
    require(check(assess_fpga_health(good_status(), n, now), "management_interface") == daphne::HEALTH_CHECK_FAIL);
  }
  auto stale = assess_fpga_health(good_status(), network, now + 5000000001);
  for (const auto& c : stale.checks()) require(c.state() == daphne::HEALTH_CHECK_UNKNOWN);
  daphne::FpgaHealthAssessment decoded;
  require(decoded.ParseFromString(health.SerializeAsString()) && decoded.SerializeAsString() == health.SerializeAsString());
  std::cout << "FPGA discovery, raw presence, fail-closed prerequisites, masks, freshness, checklist and redaction passed\n";
}
