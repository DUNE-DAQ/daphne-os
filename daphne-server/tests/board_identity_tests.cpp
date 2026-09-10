#include <cstdio>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>
#include "server_controller/board_identity.hpp"
#include "server_controller/configuration_fingerprint.hpp"

namespace {
void require(bool ok) { if (!ok) throw std::runtime_error("Board identity assertion failed"); }
template <typename F> void rejects(F function) {
  bool failed = false;
  try { function(); } catch (const std::exception& e) {
    failed = true;
    require(std::string(e.what()).find("192.0.2.") == std::string::npos);
    require(std::string(e.what()).find("02:aa:") == std::string::npos);
  }
  require(failed);
}
daphne::BoardIdentityAssignmentFile fixture() {
  using namespace daphne_sc;
  daphne::BoardIdentityAssignmentFile f;
  f.set_format_version(1);
  auto* a = f.mutable_assignments();
  a->set_application_object_id("application"); a->set_board_object_id("board");
  auto* source = a->add_sources();
  source->set_file("identity.xml"); source->set_bytes(7); source->set_sha256(sha256_hex("fixture"));
  a->set_source_revision_sha256(sha256_hex("[{\"bytes\":7,\"file\":\"identity.xml\",\"sha256\":\"" + source->sha256() + "\"}]"));
  auto provenance = [&](auto* value, const char* attribute) {
    auto* p = value->mutable_source();
    p->set_file(source->file()); p->set_sha256(source->sha256());
    p->set_object_class("Fixture"); p->set_object_id("board"); p->set_attribute(attribute);
  };
  a->mutable_crate_id()->set_value(0); provenance(a->mutable_crate_id(), "crate_id");
  a->mutable_slot_id()->set_value(1); provenance(a->mutable_slot_id(), "slot_id");
  a->mutable_detector_id()->set_value(8); provenance(a->mutable_detector_id(), "detector_id");
  a->mutable_timing_endpoint_address()->set_unavailable_reason("No assignment source");
  a->mutable_management_address()->set_value("board.example"); provenance(a->mutable_management_address(), "address");
  a->mutable_management_mac_address()->set_unavailable_reason("No MAC assignment source");
  auto* h = a->add_hermes_interfaces();
  h->set_connection_object_id("connection"); h->set_sender_object_id("sender"); h->set_interface_object_id("hermes");
  h->add_stream_object_ids("stream0"); h->add_geo_object_ids("geo0");
  h->mutable_control_host()->set_value("board.example"); provenance(h->mutable_control_host(), "control_host");
  h->mutable_mac_address()->set_value("02:aa:bb:00:00:15"); provenance(h->mutable_mac_address(), "mac_address");
  h->mutable_ip_addresses()->add_values("192.0.2.15"); provenance(h->mutable_ip_addresses(), "ip_address");
  h->mutable_hermes_link_id()->set_unavailable_reason("No approved link map");
  h->mutable_physical_connector()->set_unavailable_reason("No approved connector map");
  a->add_limitations("Explicit-field assignments, not hardware readback or schema defaults");
  auto* b = f.mutable_binding();
  b->set_interface_name("eth0"); b->set_controller_node("ethernet@ff0b0000");
  b->set_expected_mac_address("02:aa:bb:00:00:15"); b->add_expected_ipv4_cidrs("192.0.2.20/24");
  *b->mutable_approved_link_file() = *source; b->mutable_approved_link_file()->set_file("10-approved.link");
  *b->mutable_approved_network_file() = *source; b->mutable_approved_network_file()->set_file("20-approved.network");
  return f;
}
}

int main() {
  using namespace daphne_sc;
  auto f = fixture();
  const auto loaded = parse_identity_artifact(f.SerializeAsString());
  require(loaded.artifact.assignments().crate_id().has_value() && loaded.artifact.assignments().crate_id().value() == 0);
  require(!loaded.artifact.assignments().timing_endpoint_address().has_value());
  require(loaded.artifact_sha256 == sha256_hex(f.SerializeAsString()));
  const std::vector<std::function<void(daphne::BoardIdentityAssignmentFile&)>> mutations{
    [](auto& v) { v.set_format_version(2); },
    [](auto& v) { v.clear_assignments(); },
    [](auto& v) { v.clear_binding(); },
    [](auto& v) { v.mutable_assignments()->clear_crate_id(); },
    [](auto& v) { v.mutable_assignments()->mutable_crate_id()->clear_source(); },
    [](auto& v) { v.mutable_assignments()->mutable_crate_id()->set_unavailable_reason("contradiction"); },
    [](auto& v) { v.mutable_assignments()->mutable_crate_id()->mutable_source()->set_sha256(std::string(64, '0')); },
    [](auto& v) { v.mutable_assignments()->mutable_crate_id()->mutable_source()->set_file("unlisted.xml"); },
    [](auto& v) { v.mutable_assignments()->set_source_revision_sha256(std::string(64, '0')); },
    [](auto& v) { v.mutable_assignments()->mutable_sources(0)->set_file("../identity.xml"); },
    [](auto& v) { v.mutable_assignments()->mutable_sources(0)->set_bytes(0); },
    [](auto& v) { *v.mutable_assignments()->add_sources() = v.assignments().sources(0); },
    [](auto& v) { v.mutable_assignments()->mutable_management_address()->set_value("tcp://192.0.2.20"); },
    [](auto& v) { v.mutable_assignments()->clear_limitations(); },
    [](auto& v) { v.mutable_assignments()->mutable_hermes_interfaces(0)->mutable_ip_addresses()->add_values("192.0.2.15"); },
    [](auto& v) { v.mutable_assignments()->mutable_hermes_interfaces(0)->mutable_ip_addresses()->set_values(0, "224.0.0.1"); },
    [](auto& v) { v.mutable_assignments()->mutable_hermes_interfaces(0)->mutable_ip_addresses()->set_values(0, "192.00.2.15"); },
    [](auto& v) { v.mutable_assignments()->mutable_hermes_interfaces(0)->mutable_mac_address()->set_value("01:aa:bb:00:00:15"); },
    [](auto& v) { v.mutable_assignments()->mutable_hermes_interfaces(0)->mutable_mac_address()->set_value("00:00:00:00:00:00"); },
    [](auto& v) { *v.mutable_assignments()->add_hermes_interfaces() = v.assignments().hermes_interfaces(0); },
    [](auto& v) { v.mutable_assignments()->mutable_hermes_interfaces(0)->clear_geo_object_ids(); },
    [](auto& v) { v.mutable_binding()->set_interface_name("../eth0"); },
    [](auto& v) { v.mutable_binding()->set_interface_name("lo"); },
    [](auto& v) { v.mutable_binding()->set_controller_node("../ethernet@ff0b0000"); },
    [](auto& v) { v.mutable_binding()->set_expected_mac_address("FF:FF:FF:FF:FF:FF"); },
    [](auto& v) { v.mutable_binding()->set_expected_ipv4_cidrs(0, "192.0.2.20/33"); },
    [](auto& v) { v.mutable_binding()->set_expected_ipv4_cidrs(0, "192.0.2.20/024"); },
    [](auto& v) { v.mutable_binding()->add_expected_ipv4_cidrs("192.0.2.20/24"); },
    [](auto& v) { v.mutable_binding()->clear_approved_link_file(); },
  };
  for (const auto& mutate : mutations) {
    auto bad = f; mutate(bad);
    rejects([&] { parse_identity_artifact(bad.SerializeAsString()); });
  }
  auto bad_bytes = f.SerializeAsString(); bad_bytes += std::string("\x08\x01", 2); // duplicate format version
  rejects([&] { parse_identity_artifact(bad_bytes); });
  bad_bytes = f.SerializeAsString() + std::string("\xa0\x06\x01", 3); // unknown field 100
  rejects([&] { parse_identity_artifact(bad_bytes); });
  rejects([&] { parse_identity_artifact(""); });
  rejects([&] { parse_identity_artifact(std::string(65537, 'x')); });
  rejects([&] { parse_identity_artifact(f.SerializeAsString().substr(0, 10)); });

  daphne::ManagementNetworkObservation observed;
  observed.set_quality(daphne::MEASUREMENT_GOOD); observed.set_present(true);
  observed.set_interface_name("eth0"); observed.set_controller_node("ethernet@ff0b0000");
  observed.set_mac_address("02:aa:bb:00:00:15"); observed.add_ipv4_cidrs("192.0.2.20/24");
  observed.set_acquisition_started_monotonic_ns(1); observed.set_observed_monotonic_ns(100);
  observed.set_observed_host_unix_ns(1);
  observed.set_interface_index(2); observed.set_flags_raw(0);
  observed.set_interface_up(false); observed.set_running_flag(false);
  auto status = make_board_identity_status(&loaded, observed, false, 200);
  require(status.binding_state() == daphne::IDENTITY_BINDING_MATCH); // Identity match, not operational readiness.
  require(!status.has_assignments() && !status.has_management() && !status.has_binding() && !status.details_included());
  require(status.SerializeAsString().find("192.0.2.") == std::string::npos);
  require(status.SerializeAsString().find("02:aa:") == std::string::npos);
  status = make_board_identity_status(&loaded, observed, true, 200);
  require(status.has_assignments() && status.has_management() && status.has_binding() && status.details_included());
  require(status.assignments().management_address().value() == "board.example");
  require(!status.assignments().management_mac_address().has_value());
  const std::vector<std::function<void(daphne::ManagementNetworkObservation&)>> mismatches{
    [](auto& v) { v.set_present(false); },
    [](auto& v) { v.set_interface_name("eth1"); },
    [](auto& v) { v.set_controller_node("ethernet@ff0c0000"); },
    [](auto& v) { v.set_mac_address("02:aa:bb:00:00:16"); },
    [](auto& v) { v.set_ipv4_cidrs(0, "192.0.2.21/24"); },
    [](auto& v) { v.set_ipv4_cidrs(0, "192.0.2.20/25"); },
    [](auto& v) { v.add_ipv4_cidrs("192.0.2.21/24"); },
  };
  for (const auto& mutate : mismatches) {
    auto wrong = observed; mutate(wrong);
    require(make_board_identity_status(&loaded, wrong, true, 200).binding_state() == daphne::IDENTITY_BINDING_MISMATCH);
  }
  for (auto quality : {daphne::MEASUREMENT_UNAVAILABLE, daphne::MEASUREMENT_ERROR, daphne::MEASUREMENT_STALE}) {
    auto wrong = observed; wrong.set_quality(quality);
    require(make_board_identity_status(&loaded, wrong, true, 200).binding_state() == daphne::IDENTITY_BINDING_ERROR);
  }
  for (uint64_t now : {0ULL, 99ULL, 5'000'000'101ULL})
    require(make_board_identity_status(&loaded, observed, true, now).binding_state() == daphne::IDENTITY_BINDING_ERROR);
  auto missing = observed; missing.clear_present();
  require(make_board_identity_status(&loaded, missing, true, 200).binding_state() == daphne::IDENTITY_BINDING_ERROR);
  status = make_board_identity_status(nullptr, observed, true, 200);
  require(!status.assignment_configured() && status.binding_state() == daphne::IDENTITY_BINDING_UNAVAILABLE && !status.has_assignments());

  char path[] = "/tmp/daphne-private-identity-XXXXXX";
  const int fd = mkstemp(path); require(fd >= 0);
  const auto bytes = f.SerializeAsString();
  require(write(fd, bytes.data(), bytes.size()) == static_cast<ssize_t>(bytes.size()));
  require(close(fd) == 0);
  require(load_identity_artifact(path).artifact_sha256 == loaded.artifact_sha256);
  require(chmod(path, 0644) == 0);
  rejects([&] { load_identity_artifact(path); });
  require(chmod(path, 0600) == 0);
  const auto symlink_path = std::string(path) + "-link";
  require(symlink(path, symlink_path.c_str()) == 0);
  rejects([&] { load_identity_artifact(symlink_path); });
  require(unlink(symlink_path.c_str()) == 0 && unlink(path) == 0);
  rejects([&] { load_identity_artifact(path); });
  std::cout << "Identity assignments, provenance/hash, canonical encoding, private loader, mismatch/age and default redaction passed\n";
}
