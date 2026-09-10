#include "server_controller/fpga_health.hpp"
#include "server_controller/board_monitor.hpp"
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
  *s.mutable_fpga_programming() = good_programming();
  auto* id = s.mutable_gateware_identity();
  id->set_quality(daphne::MEASUREMENT_GOOD);
  id->set_matches_admitted_profile(true);
  id->set_observed_monotonic_ns(now);
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
  n.set_mac_address("private-must-not-be-exported");
  return n;
}
daphne::HealthCheckState check(const daphne::FpgaHealthAssessment& health, const std::string& name) {
  for (const auto& c : health.checks()) if (c.name() == name) return c.state();
  throw std::runtime_error("Missing health check");
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
  require(health.checks_size() == 15 && health.state() == daphne::FPGA_HEALTH_UNKNOWN);
  unsigned passes = 0, unknowns = 0;
  for (const auto& c : health.checks()) {
    passes += c.state() == daphne::HEALTH_CHECK_PASS;
    unknowns += c.state() == daphne::HEALTH_CHECK_UNKNOWN;
  }
  require(passes == 12 && unknowns == 3);
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
  auto stale = assess_fpga_health(good_status(), network, now + 5000000001);
  for (const auto& c : stale.checks()) require(c.state() == daphne::HEALTH_CHECK_UNKNOWN);
  daphne::FpgaHealthAssessment decoded;
  require(decoded.ParseFromString(health.SerializeAsString()) && decoded.SerializeAsString() == health.SerializeAsString());
  std::cout << "FPGA discovery, raw presence, fail-closed prerequisites, masks, freshness, checklist and redaction passed\n";
}
