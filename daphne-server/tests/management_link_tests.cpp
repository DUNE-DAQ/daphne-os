#include "server_controller/management_link.hpp"

#include <functional>
#include <iostream>
#include <map>
#include <stdexcept>
#include <system_error>
#include <vector>

namespace {
using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("Management link test failed"); }
struct Fake : ManagementLinkIo {
  std::map<std::string, std::string> files{{"ifindex", "2\n"}, {"operstate", "up\n"}, {"carrier", "1\n"},
      {"speed", "1000\n"}, {"duplex", "full\n"}, {"mtu", "1500\n"}, {"carrier_changes", "7\n"},
      {"statistics/rx_bytes", "18446744073709551615\n"}, {"statistics/rx_packets", "4294967296\n"},
      {"statistics/rx_errors", "0\n"}, {"statistics/rx_dropped", "3\n"}, {"statistics/tx_bytes", "1234\n"},
      {"statistics/tx_packets", "42\n"}, {"statistics/tx_errors", "0\n"}, {"statistics/tx_dropped", "0\n"}};
  std::map<std::string, unsigned> calls;
  std::function<void(Fake&, const std::string&)> on_read;
  std::string error_path;
  std::errc error = std::errc::permission_denied;
  uint64_t ticks = 100;
  bool reverse_clock = false;
  std::string read_file(const char* path, size_t maximum) override {
    require(maximum == 64);
    ++calls[path];
    if (on_read) on_read(*this, path);
    if (error_path == path) throw std::system_error(std::make_error_code(error), "PRIVATE-error-path-address");
    if (!files.count(path)) throw std::system_error(std::make_error_code(std::errc::no_such_file_or_directory));
    return files.at(path);
  }
  ManagementLinkTime now() override { return {123456789, reverse_clock ? --ticks : ++ticks}; }
};
const daphne::ManagementLinkObservation& metric(const daphne::ManagementLinkStatus& status, int n) {
  return status.observations(n - 1);
}
void no_values(const daphne::ManagementLinkStatus& status) {
  require(!status.has_interface_index() && !status.observed_monotonic_ns() && !status.link_state_bracket_verified());
  for (const auto& item : status.observations())
    require(item.quality() != daphne::MEASUREMENT_GOOD && item.value_case() == item.VALUE_NOT_SET &&
            !item.observed_monotonic_ns() && !item.observed_host_unix_ns());
}
}

int main() {
  Fake io;
  auto status = read_management_link(io, 2);
  require(status.quality() == daphne::MEASUREMENT_GOOD && status.interface_index() == 2 &&
          status.observations_size() == 14 && status.link_state_bracket_verified());
  unsigned reads = 0;
  for (const auto& [path, count] : io.calls) reads += count;
  require(reads == 18 && io.calls.at("ifindex") == 2 && io.calls.at("carrier") == 2 && io.calls.at("operstate") == 2);
  for (int n = 1; n <= 14; ++n) {
    const auto& item = metric(status, n);
    require(item.metric() == n && item.quality() == daphne::MEASUREMENT_GOOD && !item.detail().empty() &&
            !item.source().empty() && !item.unit().empty() && item.value_case() != item.VALUE_NOT_SET &&
            status.acquisition_started_monotonic_ns() <= item.acquisition_started_monotonic_ns() &&
            item.acquisition_started_monotonic_ns() <= item.observed_monotonic_ns() &&
            item.observed_monotonic_ns() <= status.observed_monotonic_ns());
  }
  require(metric(status, 1).text_value() == "up" && metric(status, 2).flag_value());
  require(metric(status, 3).unsigned_value() == 1000 && metric(status, 4).text_value() == "full");
  require(metric(status, 6).unsigned_value() == UINT64_MAX && metric(status, 6).counter_width_bits() == 64);
  require(metric(status, 7).unsigned_value() == uint64_t{4294967296});
  require(metric(status, 8).has_unsigned_value() && metric(status, 8).unsigned_value() == 0);
  require(metric(status, 14).counter_width_bits() == 32);
  daphne::ManagementLinkStatus roundtrip;
  require(roundtrip.ParseFromString(status.SerializeAsString()) && roundtrip.SerializeAsString() == status.SerializeAsString());
  for (const auto* state : {"unknown", "notpresent", "down", "lowerlayerdown", "testing", "dormant", "up"}) {
    Fake f; f.files["operstate"] = state;
    const auto result = read_management_link(f, 2);
    require(metric(result, 1).quality() == daphne::MEASUREMENT_GOOD && metric(result, 1).text_value() == state);
    require(metric(result, 3).has_unsigned_value() == (std::string(state) == "up"));
  }
  for (const auto* speed : {"-1", "4294967295"}) {
    Fake f; f.files["speed"] = speed;
    const auto result = read_management_link(f, 2);
    require(metric(result, 3).quality() == daphne::MEASUREMENT_UNAVAILABLE && !metric(result, 3).has_unsigned_value());
    require(metric(result, 6).quality() == daphne::MEASUREMENT_GOOD);
  }
  for (const auto* duplex : {"half", "full", "unknown"}) {
    Fake f; f.files["duplex"] = duplex;
    const auto result = read_management_link(f, 2);
    require(metric(result, 4).has_text_value() == (std::string(duplex) != "unknown"));
  }
  Fake down; down.files["carrier"] = "0\n"; down.files["operstate"] = "down\n";
  status = read_management_link(down, 2);
  require(status.link_state_bracket_verified() && metric(status, 2).has_flag_value() && !metric(status, 2).flag_value());
  for (int n : {3, 4}) require(metric(status, n).quality() == daphne::MEASUREMENT_UNAVAILABLE);
  const std::vector<std::pair<std::string, std::string>> invalid{
      {"speed", "0"}, {"speed", "4294967296"}, {"mtu", "0"}, {"mtu", "4294967296"}, {"carrier", "2"},
      {"operstate", "ready"}, {"duplex", "auto"}, {"statistics/rx_bytes", "18446744073709551616"},
      {"carrier_changes", "4294967296"}};
  for (const auto& [path, value] : invalid) {
    Fake f; f.files[path] = value;
    const auto result = read_management_link(f, 2);
    bool rejected = false;
    for (const auto& item : result.observations()) if (item.source() == path)
      rejected = item.quality() == daphne::MEASUREMENT_ERROR && item.value_case() == item.VALUE_NOT_SET;
    require(rejected);
  }
  for (const auto& value : {std::string(), std::string(" 1"), std::string("+1"), std::string("-1"), std::string("1\n2"),
                           std::string("1\r\n"), std::string("1\0", 2), std::string(65, '1')}) {
    Fake f; f.files["statistics/rx_errors"] = value;
    const auto result = read_management_link(f, 2);
    require(metric(result, 8).quality() == daphne::MEASUREMENT_ERROR && !metric(result, 8).has_unsigned_value());
  }
  for (auto error : {std::errc::no_such_file_or_directory, std::errc::no_such_device, std::errc::permission_denied,
                     std::errc::operation_not_supported, std::errc::invalid_argument, std::errc::io_error}) {
    Fake f; f.error_path = "carrier"; f.error = error;
    const auto result = read_management_link(f, 2);
    require(result.quality() == daphne::MEASUREMENT_GOOD && !result.link_state_bracket_verified());
    require(metric(result, 2).quality() == (error == std::errc::io_error ? daphne::MEASUREMENT_ERROR : daphne::MEASUREMENT_UNAVAILABLE));
    require(!metric(result, 2).has_flag_value() && metric(result, 6).quality() == daphne::MEASUREMENT_GOOD);
    require(result.SerializeAsString().find("PRIVATE") == std::string::npos);
  }
  for (const auto* path : {"carrier", "operstate"}) {
    Fake f;
    f.on_read = [path](Fake& self, const std::string& name) {
      if (name == path && self.calls[name] == 2) self.files[name] = name == "carrier" ? "0" : "down";
    };
    const auto result = read_management_link(f, 2);
    require(!result.link_state_bracket_verified() && !metric(result, 3).has_unsigned_value() &&
            metric(result, 6).quality() == daphne::MEASUREMENT_GOOD);
  }
  for (auto index : {uint32_t{0}, uint32_t{3}, UINT32_MAX}) {
    Fake f; status = read_management_link(f, index);
    require(status.quality() == daphne::MEASUREMENT_ERROR); no_values(status);
  }
  Fake replaced;
  replaced.on_read = [](Fake& self, const std::string& path) {
    if (path == "ifindex" && self.calls[path] == 2) self.files[path] = "3";
  };
  status = read_management_link(replaced, 2);
  require(status.quality() == daphne::MEASUREMENT_ERROR); no_values(status);
  Fake gone; gone.error_path = "ifindex";
  status = read_management_link(gone, 2);
  require(status.quality() == daphne::MEASUREMENT_UNAVAILABLE); no_values(status);
  Fake reversed; reversed.reverse_clock = true;
  status = read_management_link(reversed, 2);
  require(status.quality() == daphne::MEASUREMENT_ERROR); no_values(status);
  for (const auto* interface : {"", ".", "..", "../eth0", "eth0/address", "eth0;secret", "1234567890123456"}) {
    status = read_management_link_linux(interface, 2);
    require(status.quality() == daphne::MEASUREMENT_ERROR); no_values(status);
  }
  std::cout << "management_link_tests passed\n";
}
