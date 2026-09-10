#include "server_controller/host_software.hpp"
#include "server_controller/board_monitor.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <fcntl.h>
#include <map>
#include <sstream>
#include <stdexcept>
#include <system_error>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

namespace daphne_sc {
namespace {
using Observation = daphne::HostSoftwareObservation;
constexpr size_t kMaximumFileBytes = 16384;
constexpr std::array<const char*, 6> kKeys{{
    "PRETTY_NAME", "ID", "VERSION_ID", "BUILD_ID", "IMAGE_ID", "IMAGE_VERSION"}};

bool printable_utf8(const std::string& value) {
  for (size_t i = 0; i < value.size();) {
    const auto first = static_cast<unsigned char>(value[i++]);
    uint32_t code = first;
    unsigned tail = 0;
    uint32_t minimum = 0;
    if (first >= 0xc2 && first <= 0xdf) { code &= 0x1f; tail = 1; minimum = 0x80; }
    else if (first >= 0xe0 && first <= 0xef) { code &= 0x0f; tail = 2; minimum = 0x800; }
    else if (first >= 0xf0 && first <= 0xf4) { code &= 7; tail = 3; minimum = 0x10000; }
    else if (first >= 0x80) return false;
    if (i + tail > value.size()) return false;
    for (unsigned n = 0; n < tail; ++n) {
      const auto c = static_cast<unsigned char>(value[i++]);
      if ((c & 0xc0) != 0x80) return false;
      code = (code << 6) | (c & 0x3f);
    }
    if (code < minimum || code < 32 || (code >= 127 && code <= 159) ||
        (code >= 0xd800 && code <= 0xdfff) || code > 0x10ffff) return false;
  }
  return true;
}

std::string assignment_value(const std::string& raw) {
  if (raw.empty()) return {};
  std::string value;
  const char quote = (raw.front() == '\'' || raw.front() == '"') ? raw.front() : 0;
  const size_t end = quote ? raw.size() - 1 : raw.size();
  if (quote && (raw.size() < 2 || raw.back() != quote))
    throw std::runtime_error("Unclosed release value");
  for (size_t i = quote ? 1 : 0; i < end; ++i) {
    char c = raw[i];
    if (quote == '\'') {
      if (c == '\'') throw std::runtime_error("Concatenated release value");
    } else if (c == '\\') {
      if (++i >= end) throw std::runtime_error("Incomplete release escape");
      c = raw[i];
      // In double quotes, shell backslashes only escape these four characters.
      // Other backslashes are literal; no expansion or command substitution.
      if (quote == '"' && c != '$' && c != '`' && c != '"' && c != '\\') value += '\\';
    } else if (c == '$' || c == '`' || c == '"' || c == '\'' ||
               (!quote && (static_cast<unsigned char>(c) <= 32 || c == ';' ||
                            c == '&' || c == '|' || c == '<' || c == '>' || c == '(' || c == ')'))) {
      throw std::runtime_error("Unsupported release assignment syntax");
    }
    value += c;
  }
  if (value.size() > 256 || !printable_utf8(value)) throw std::runtime_error("Invalid release text");
  return value;
}

std::map<std::string, std::string> selected_assignments(const std::string& file) {
  if (file.size() > kMaximumFileBytes || file.find('\0') != std::string::npos)
    throw std::runtime_error("Invalid release file");
  std::map<std::string, std::string> selected;
  std::istringstream stream(file);
  std::string line;
  while (std::getline(stream, line)) {
    if (line.empty() || line.front() == '#') continue;
    const auto equal = line.find('=');
    if (equal == std::string::npos || !equal ||
        line.substr(0, equal).find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_") != std::string::npos ||
        (line.front() >= '0' && line.front() <= '9'))
      throw std::runtime_error("Malformed release assignment");
    const auto key = line.substr(0, equal);
    if (std::find(kKeys.begin(), kKeys.end(), key) != kKeys.end())
      selected[key] = line.substr(equal + 1); // Last assignment wins, as os-release specifies.
  }
  return selected; // No unrelated values, comments, URLs or environment export.
}

void fail(Observation& item, daphne::MeasurementQuality quality, const char* detail) {
  item.clear_value();
  item.clear_observed_monotonic_ns();
  item.clear_observed_host_unix_ns();
  item.set_quality(quality);
  item.set_detail(detail);
}
void finish(Observation& item, const HostSoftwareTime& end) {
  if (!item.acquisition_started_monotonic_ns() || end.monotonic_ns < item.acquisition_started_monotonic_ns())
    throw std::runtime_error("Invalid host software acquisition clock");
  item.set_observed_monotonic_ns(end.monotonic_ns);
  item.set_observed_host_unix_ns(end.host_unix_ns);
  item.set_quality(daphne::MEASUREMENT_GOOD);
  item.set_detail("Local OS metadata observation, not authenticated provenance, current rootfs integrity, server version or verified UTC");
}
bool missing(const std::system_error& error) {
  return error.code() == std::errc::no_such_file_or_directory || error.code() == std::errc::permission_denied;
}

class LinuxHostSoftware final : public HostSoftwareIo {
 public:
  std::string kernel_release() override {
    utsname data{};
    if (uname(&data) != 0) throw std::system_error(errno, std::generic_category());
    return data.release;
  }
  std::string read_file(const char* path, size_t maximum) override {
    // O_NONBLOCK prevents opening a substituted FIFO from waiting for a writer;
    // fstat then rejects non-regular inputs before reading. Follow the standard
    // /etc -> /usr/lib symlink; the selected path is fixed, never client supplied.
    const int fd = open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) throw std::system_error(errno, std::generic_category());
    std::string data;
    try {
      struct stat before{}, after{};
      if (fstat(fd, &before) != 0) throw std::system_error(errno, std::generic_category());
      if (!S_ISREG(before.st_mode) || before.st_size < 0 || static_cast<uint64_t>(before.st_size) > maximum)
        throw std::runtime_error("Invalid release file type or size");
      char buffer[4096];
      for (;;) {
        const auto count = read(fd, buffer, std::min(sizeof(buffer), maximum + 1 - data.size()));
        if (count < 0) { if (errno == EINTR) continue; throw std::system_error(errno, std::generic_category()); }
        if (!count) break;
        data.append(buffer, static_cast<size_t>(count));
        if (data.size() > maximum) throw std::runtime_error("Oversized release file");
      }
      if (fstat(fd, &after) != 0) throw std::system_error(errno, std::generic_category());
      if (before.st_size != after.st_size || data.size() != static_cast<uint64_t>(after.st_size) ||
          before.st_mtim.tv_sec != after.st_mtim.tv_sec || before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
          before.st_ctim.tv_sec != after.st_ctim.tv_sec || before.st_ctim.tv_nsec != after.st_ctim.tv_nsec)
        throw std::runtime_error("Release file changed during read");
    } catch (...) { close(fd); throw; }
    close(fd);
    return data;
  }
  HostSoftwareTime now() override { return {host_unix_time_ns(), monotonic_time_ns()}; }
};
}  // namespace

std::vector<Observation> read_host_software(HostSoftwareIo& io) {
  std::vector<Observation> result(7);
  for (size_t i = 0; i < result.size(); ++i) {
    result[i].set_metric(static_cast<daphne::HostSoftwareMetric>(i + 1));
    result[i].set_source(i ? std::string("/etc/os-release:") + kKeys[i - 1] : "uname:release");
  }
  auto& kernel = result[0];
  try {
    kernel.set_acquisition_started_monotonic_ns(io.now().monotonic_ns);
    const auto value = io.kernel_release();
    if (value.empty() || value.size() > 256 || !printable_utf8(value)) throw std::runtime_error("Invalid kernel release");
    kernel.set_value(value);
    finish(kernel, io.now());
  } catch (const std::system_error&) {
    fail(kernel, daphne::MEASUREMENT_ERROR, "Kernel release query failed");
  } catch (const std::exception&) {
    fail(kernel, daphne::MEASUREMENT_ERROR, "Invalid kernel release or acquisition clock");
  }
  try {
    const auto start = io.now().monotonic_ns;
    for (size_t i = 1; i < result.size(); ++i) result[i].set_acquisition_started_monotonic_ns(start);
    std::string input;
    try { input = io.read_file("/etc/os-release", kMaximumFileBytes); }
    catch (const std::system_error& error) {
      if (error.code() != std::errc::no_such_file_or_directory) throw;
      for (size_t i = 1; i < result.size(); ++i) result[i].set_source(std::string("/usr/lib/os-release:") + kKeys[i - 1]);
      input = io.read_file("/usr/lib/os-release", kMaximumFileBytes);
    }
    const auto values = selected_assignments(input);
    const auto end = io.now();
    if (!start || end.monotonic_ns < start) throw std::runtime_error("Invalid release acquisition clock");
    for (size_t i = 1; i < result.size(); ++i) {
      auto& item = result[i];
      try {
        const auto raw = values.find(kKeys[i - 1]);
        const auto value = raw == values.end() ? std::string{} : assignment_value(raw->second);
        if (value.empty()) { fail(item, daphne::MEASUREMENT_UNAVAILABLE, "OS release field not supplied; no default substituted"); continue; }
        if ((i == 2 || i == 5) && value.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789._-") != std::string::npos)
          throw std::runtime_error("Invalid OS identifier");
        if (i == 3 && value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-~^+") != std::string::npos)
          throw std::runtime_error("Invalid OS version identifier");
        item.set_value(value);
        finish(item, end);
      } catch (const std::exception&) { fail(item, daphne::MEASUREMENT_ERROR, "Invalid selected OS release field"); }
    }
  } catch (const std::system_error& error) {
    for (size_t i = 1; i < result.size(); ++i)
      fail(result[i], missing(error) ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR,
           missing(error) ? "OS release source unavailable" : "OS release read failed");
  } catch (const std::exception&) {
    for (size_t i = 1; i < result.size(); ++i) fail(result[i], daphne::MEASUREMENT_ERROR, "Invalid OS release file or acquisition clock");
  }
  return result;
}

void add_host_software(daphne::SystemStatusSnapshot& status) {
  LinuxHostSoftware io;
  status.clear_host_software();
  status.clear_kernel_release();
  status.clear_petalinux_version();
  for (const auto& item : read_host_software(io)) {
    *status.add_host_software() = item;
    if (item.quality() != daphne::MEASUREMENT_GOOD) continue;
    if (item.metric() == daphne::HOST_KERNEL_RELEASE) status.set_kernel_release(item.value());
    if (item.metric() == daphne::HOST_OS_PRETTY_NAME) status.set_petalinux_version(item.value());
  }
}
}  // namespace daphne_sc
