#include "server_controller/host_software.hpp"
#include <iostream>
#include <map>
#include <stdexcept>
#include <system_error>

using namespace daphne_sc;
void require(bool ok) { if (!ok) throw std::runtime_error("Host software test failed"); }
struct Fake final : HostSoftwareIo {
  std::string kernel = "6.1-test";
  std::map<std::string, std::string> files{{"/etc/os-release",
      "# fixture\nPRETTY_NAME=\"PetaLinux test\"\nID=petalinux\nVERSION_ID=2026.1-release\n"
      "BUILD_ID='base-1'\nIMAGE_ID=daphne\nIMAGE_VERSION=2\nHOME_URL=private-not-exported\n"}};
  std::map<std::string, std::errc> errors;
  unsigned clocks = 0;
  int invalid_clock = -1;
  uint64_t bad_time = 0;
  bool kernel_error = false;
  std::vector<std::string> paths;
  std::string kernel_release() override {
    if (kernel_error) throw std::system_error(std::make_error_code(std::errc::io_error));
    return kernel;
  }
  std::string read_file(const char* path, size_t maximum) override {
    require(maximum == 16384);
    paths.emplace_back(path);
    if (errors.count(path)) throw std::system_error(std::make_error_code(errors.at(path)));
    if (!files.count(path)) throw std::system_error(std::make_error_code(std::errc::no_such_file_or_directory));
    return files.at(path);
  }
  HostSoftwareTime now() override {
    ++clocks;
    return {1000 + clocks, static_cast<int>(clocks) == invalid_clock ? bad_time : 100 + clocks};
  }
};
void bad(const daphne::HostSoftwareObservation& item, daphne::MeasurementQuality quality = daphne::MEASUREMENT_ERROR) {
  require(item.quality() == quality && !item.has_value());
  require(!item.observed_monotonic_ns() && !item.observed_host_unix_ns());
  require(!item.source().empty() && !item.detail().empty());
}
void all_os_bad(const std::vector<daphne::HostSoftwareObservation>& values,
                daphne::MeasurementQuality quality = daphne::MEASUREMENT_ERROR) {
  require(values[0].quality() == daphne::MEASUREMENT_GOOD);
  for (size_t i = 1; i != values.size(); ++i) bad(values[i], quality);
}
int main() {
  Fake io;
  const auto values = read_host_software(io);
  require(values.size() == 7 && io.clocks == 4 && io.paths == std::vector<std::string>{"/etc/os-release"});
  for (size_t i = 0; i != values.size(); ++i) {
    const auto& v = values[i];
    require(v.metric() == static_cast<int>(i + 1) && v.quality() == daphne::MEASUREMENT_GOOD && v.has_value());
    require(v.acquisition_started_monotonic_ns() && v.observed_monotonic_ns() >= v.acquisition_started_monotonic_ns());
    require(v.observed_host_unix_ns() && !v.detail().empty());
    if (i > 1) require(v.observed_monotonic_ns() == values[1].observed_monotonic_ns());
    require(v.SerializeAsString().find("private-not-exported") == std::string::npos);
    daphne::HostSoftwareObservation decoded;
    require(decoded.ParseFromString(v.SerializeAsString()) && decoded.has_value() && decoded.value() == v.value());
  }
  require(values[0].value() == "6.1-test" && values[1].value() == "PetaLinux test" && values[4].value() == "base-1");
  Fake fallback; fallback.files["/usr/lib/os-release"] = fallback.files.at("/etc/os-release"); fallback.files.erase("/etc/os-release");
  const auto vendor = read_host_software(fallback);
  require(fallback.paths.size() == 2 && vendor[2].source() == "/usr/lib/os-release:ID" && vendor[2].value() == "petalinux");
  for (auto error : {std::errc::permission_denied, std::errc::io_error, std::errc::too_many_symbolic_link_levels}) {
    Fake f; f.errors["/etc/os-release"] = error; f.files["/usr/lib/os-release"] = f.files.at("/etc/os-release");
    const auto result = read_host_software(f);
    require(f.paths.size() == 1); // No fallback on a permission, I/O, or symlink-loop failure.
    all_os_bad(result, error == std::errc::permission_denied ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR);
  }
  Fake missing; missing.files.clear();
  all_os_bad(read_host_software(missing), daphne::MEASUREMENT_UNAVAILABLE);
  Fake empty; empty.files["/etc/os-release"] = "# optional fields absent\n";
  empty.files["/usr/lib/os-release"] = io.files.at("/etc/os-release");
  all_os_bad(read_host_software(empty), daphne::MEASUREMENT_UNAVAILABLE);
  require(empty.paths.size() == 1); // Never merge missing fields from vendor data.
  for (const auto& invalid : {std::string(16385, 'x'), std::string("ID=x\0", 5), std::string("no-assignment"),
                              std::string("3ID=x"), std::string("ID =x")}) {
    Fake f; f.files["/etc/os-release"] = invalid;
    all_os_bad(read_host_software(f));
  }
  for (const auto& invalid : {std::string{}, std::string(257, 'x'), std::string("x\n"), std::string("\x1b"),
                              std::string("\xc0\xaf"), std::string("\xed\xa0\x80"), std::string("\xf4\x90\x80\x80")}) {
    Fake f; f.kernel = invalid; const auto result = read_host_software(f);
    bad(result[0]); require(result[1].quality() == daphne::MEASUREMENT_GOOD);
  }
  Fake syscall; syscall.kernel_error = true; bad(read_host_software(syscall)[0]);
  for (const auto& raw : {"\"unclosed", "'unclosed", "\"a\"\"b\"", "a b", "$(no-execution)", "`no-execution`",
                        "\"$EXPANSION\"", "\"a\\\"", "x;command", "x\x1b", "\"\xc2\x85\"", "\"\xe2\x82\""}) {
    Fake f; f.files["/etc/os-release"] += std::string("PRETTY_NAME=") + raw + "\n";
    const auto result = read_host_software(f); bad(result[1]);
    require(result[2].quality() == daphne::MEASUREMENT_GOOD);
  }
  for (const auto& pair : {std::pair<std::string, std::string>{"\"a\\\"b\\\\c\\$d\\`e\"", "a\"b\\c$d`e"},
       {"'literal $HOME `text`'", "literal $HOME `text`"}, {"\"a\\qb\"", "a\\qb"},
       {"\"PetaLinux \xc3\xa9\xe2\x82\xac\xf0\x9f\x98\x80\"", "PetaLinux \xc3\xa9\xe2\x82\xac\xf0\x9f\x98\x80"},
       {"a\\ b", "a b"}, {"0", "0"}}) {
    Fake f; f.files["/etc/os-release"] += "PRETTY_NAME=" + pair.first + "\n";
    const auto value = read_host_software(f)[1]; require(value.quality() == daphne::MEASUREMENT_GOOD && value.value() == pair.second);
  }
  for (const auto& raw : {"", "\"\"", "''"}) {
    Fake f; f.files["/etc/os-release"] += std::string("BUILD_ID=") + raw;
    bad(read_host_software(f)[4], daphne::MEASUREMENT_UNAVAILABLE);
  }
  Fake duplicate; duplicate.files["/etc/os-release"] += "ID=\"invalid first\"\nID=final\n";
  require(read_host_software(duplicate)[2].value() == "final");
  for (const auto& pair : {std::pair<const char*, size_t>{"ID=Invalid", 2}, {"ID=\"two words\"", 2},
       {"VERSION_ID=\"two words\"", 3}, {"IMAGE_ID=Invalid", 5}}) {
    Fake f; f.files["/etc/os-release"] += std::string(pair.first) + "\n"; bad(read_host_software(f)[pair.second]);
  }
  Fake version; version.files["/etc/os-release"] += "VERSION_ID=1~rc^1+test\n";
  require(read_host_software(version)[3].value() == "1~rc^1+test");
  Fake bounds; bounds.files["/etc/os-release"] += "PRETTY_NAME=\"" + std::string(256, 'x') + "\"\n";
  require(read_host_software(bounds)[1].value().size() == 256);
  bounds.files["/etc/os-release"] += "PRETTY_NAME=\"" + std::string(257, 'x') + "\"\n"; bad(read_host_software(bounds)[1]);
  for (int call : {1, 2, 3, 4}) {
    for (uint64_t invalid : {uint64_t{0}, uint64_t{1}}) {
      if (invalid == 1 && call % 2) continue;
      Fake f; f.invalid_clock = call; f.bad_time = invalid; const auto result = read_host_software(f);
      if (call <= 2) bad(result[0]); else all_os_bad(result);
    }
  }
  io.files["/etc/os-release"] = "ID=\"corrupted";
  bad(read_host_software(io)[2]); // Failed reacquisition never reuses old success.
  daphne::SystemStatusSnapshot wire, decoded;
  wire.set_kernel_release("legacy");
  for (const auto& v : values) *wire.add_host_software() = v;
  require(decoded.ParseFromString(wire.SerializeAsString()) && decoded.kernel_release() == "legacy" && decoded.host_software_size() == 7);
  std::cout << "Host software precedence, isolation, UTF-8/escaping, bounds, errors, clocks and wire tests passed\n";
}
