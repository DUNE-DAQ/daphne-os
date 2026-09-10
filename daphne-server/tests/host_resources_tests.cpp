#include "server_controller/host_resources.hpp"
#include <iostream>
#include <map>
#include <stdexcept>
#include <system_error>

using namespace daphne_sc;
void require(bool ok, const char* message = "Host resource test failed") {
  if (!ok) throw std::runtime_error(message);
}
struct Fake final : HostResourceIo {
  std::map<std::string, std::string> files{
      {"/proc/uptime", "100.25 350.00\n"}, // Combined idle time may be larger.
      {"/proc/loadavg", "1.75 2.00 3.00 1/200 9999\n"},
      {"/proc/meminfo", "MemFree: 3 kB\nMemAvailable: 123456 kB\nCached: 400 kB\n"}};
  RootFilesystemSpace fs{4096, 1000, 500, 450, false};
  uint64_t tick = 100;
  unsigned calls = 0, fs_calls = 0;
  int failed_time_call = -1;
  bool reverse_time = false;
  bool fs_error = false;
  std::string io_error_path;
  std::string read_file(const char* path, size_t maximum) override {
    require(maximum == (std::string(path) == "/proc/meminfo" ? 16384 : 4096));
    if (io_error_path == path) throw std::system_error(std::make_error_code(std::errc::io_error));
    if (!files.count(path)) throw std::system_error(std::make_error_code(std::errc::no_such_file_or_directory));
    return files.at(path);
  }
  RootFilesystemSpace root_filesystem() override {
    ++fs_calls;
    if (fs_error) throw std::system_error(std::make_error_code(std::errc::io_error));
    return fs;
  }
  HostResourceTime now() override {
    ++calls;
    tick += 10;
    if (static_cast<int>(calls) == failed_time_call) return {9000, reverse_time ? 1U : 0U};
    return {9000 + tick, tick};
  }
};
void bad(const daphne::HostResourceObservation& value, daphne::MeasurementQuality quality = daphne::MEASUREMENT_ERROR) {
  require(value.quality() == quality);
  require(value.value_case() == daphne::HostResourceObservation::VALUE_NOT_SET);
  require(value.observed_monotonic_ns() == 0 && value.observed_host_unix_ns() == 0);
}
int main() {
  Fake io;
  const auto values = read_host_resources(io);
  require(values.size() == 6 && io.fs_calls == 1 && io.calls == 8);
  for (size_t i = 0; i != values.size(); ++i) {
    const auto& value = values[i];
    require(static_cast<int>(value.metric()) == static_cast<int>(i + 1));
    require(value.quality() == daphne::MEASUREMENT_GOOD);
    require(value.observed_monotonic_ns() >= value.acquisition_started_monotonic_ns());
    require(value.acquisition_started_monotonic_ns() > 0 && value.observed_host_unix_ns() > 0);
    require(!value.source().empty() && !value.detail().empty() && !value.unit().empty());
    daphne::HostResourceObservation decoded;
    require(decoded.ParseFromString(value.SerializeAsString()));
    require(decoded.value_case() == value.value_case());
  }
  require(values[0].has_scalar_value() && values[0].scalar_value() == 100.25);
  require(values[1].scalar_value() == 1.75 && values[1].unit() == "1");
  require(values[2].has_bytes_value() && values[2].bytes_value() == 123456ULL * 1024);
  require(values[3].bytes_value() == 500 * 4096 && values[4].bytes_value() == 450 * 4096);
  require(values[5].has_flag_value() && !values[5].flag_value());
  require(values[3].observed_monotonic_ns() == values[4].observed_monotonic_ns());
  require(values[3].observed_monotonic_ns() == values[5].observed_monotonic_ns());
  for (const auto& invalid : {"", "NaN 0", "inf 0", "-1 0", "+1 0", "1e3 0", "1,2 0", "1.2.3 0", ".2 0", "1. 0", "1 0 extra"}) {
    Fake test; test.files["/proc/uptime"] = invalid;
    const auto result = read_host_resources(test);
    bad(result[0]); require(result[1].quality() == daphne::MEASUREMENT_GOOD);
  }
  for (const auto& invalid : {"", "1 2 3", "1 2 3 4 5", "NaN 2 3 1/2 1", "1 2 3 1/2/3 1", "1 2 3 1/2 -1"}) {
    Fake test; test.files["/proc/loadavg"] = invalid;
    bad(read_host_resources(test)[1]);
  }
  for (const auto& invalid : {"MemAvailable: -1 kB", "MemAvailable: 1 MB", "MemAvailable: 1 kB extra",
       "MemAvailable: 1 kB\nMemAvailable: 2 kB", "MemAvailable: 18014398509481984 kB",
       "MemAvailable: 18446744073709551616 kB", "MemAvailable: 1.5 kB"}) {
    Fake test; test.files["/proc/meminfo"] = invalid;
    bad(read_host_resources(test)[2]);
  }
  for (const char* path : {"/proc/uptime", "/proc/loadavg", "/proc/meminfo"}) {
    const size_t index = std::string(path) == "/proc/uptime" ? 0 : std::string(path) == "/proc/loadavg" ? 1 : 2;
    Fake missing; missing.files.erase(path);
    bad(read_host_resources(missing)[index], daphne::MEASUREMENT_UNAVAILABLE);
    Fake failure; failure.io_error_path = path;
    bad(read_host_resources(failure)[index]);
    Fake oversized; oversized.files[path] = std::string(16385, '9');
    bad(read_host_resources(oversized)[index]);
    Fake nul; nul.files[path].push_back('\0');
    bad(read_host_resources(nul)[index]);
  }
  Fake old_kernel; old_kernel.files["/proc/meminfo"] = "MemFree: 10000 kB\n";
  bad(read_host_resources(old_kernel)[2], daphne::MEASUREMENT_UNAVAILABLE); // Do not substitute MemFree.
  Fake maximum; maximum.files["/proc/meminfo"] = "MemAvailable: 18014398509481983 kB\n";
  require(read_host_resources(maximum)[2].bytes_value() == UINT64_MAX - 1023);
  Fake zero; zero.files["/proc/uptime"] = "0 0"; zero.files["/proc/loadavg"] = "0 0 0 0/1 0";
  zero.files["/proc/meminfo"] = "MemAvailable: 0 kB\n"; zero.fs = {4096, 100, 0, 0, true};
  const auto empty = read_host_resources(zero);
  require(empty[0].has_scalar_value() && empty[0].scalar_value() == 0);
  require(empty[2].has_bytes_value() && empty[2].bytes_value() == 0);
  require(empty[3].has_bytes_value() && empty[3].bytes_value() == 0 && empty[5].flag_value());
  for (const auto space : {RootFilesystemSpace{0, 100, 50, 40, false},
       RootFilesystemSpace{4096, 1, 2, 0, false}, RootFilesystemSpace{4096, 10, 1, 2, false},
       RootFilesystemSpace{UINT64_MAX, 10, 2, 1, false}}) {
    Fake test; test.fs = space;
    const auto failed = read_host_resources(test);
    for (size_t i : {3, 4, 5}) bad(failed[i]);
  }
  Fake syscall; syscall.fs_error = true;
  const auto failed_fs = read_host_resources(syscall);
  for (size_t i : {3, 4, 5}) bad(failed_fs[i]);
  for (int call : {1, 2, 7, 8}) {
    for (bool reverse : {false, true}) {
      // Invalid first time (zero), or backwards completion, must discard values.
      if ((call == 1 || call == 7) && reverse) continue;
      Fake clock; clock.failed_time_call = call; clock.reverse_time = reverse;
      const auto failed = read_host_resources(clock);
      if (call <= 2) bad(failed[0]);
      else for (size_t i : {3, 4, 5}) bad(failed[i]);
    }
  }
  io.files["/proc/uptime"] = "corrupted";
  bad(read_host_resources(io)[0]); // A new error never reuses the previous valid observation.
  daphne::SystemStatusSnapshot wire;
  wire.set_hostname("retained");
  for (const auto& v : values) *wire.add_host_resources() = v;
  daphne::SystemStatusSnapshot decoded;
  require(decoded.ParseFromString(wire.SerializeAsString()));
  require(decoded.hostname() == "retained" && decoded.host_resources_size() == 6);
  std::cout << "Host resource parsing, units, zero presence, bounds, failures, clocks, root grouping and protobuf passed\n";
}
