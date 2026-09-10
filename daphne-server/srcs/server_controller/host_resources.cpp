#include "server_controller/host_resources.hpp"
#include "server_controller/board_monitor.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <fcntl.h>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <system_error>
#include <sys/statvfs.h>
#include <unistd.h>

namespace daphne_sc {
namespace {
using Observation = daphne::HostResourceObservation;
class Unavailable : public std::runtime_error { using std::runtime_error::runtime_error; };

std::vector<std::string> fields(const std::string& input, size_t maximum) {
  if (input.empty() || input.size() > maximum || input.find('\0') != std::string::npos)
    throw std::runtime_error("Empty, oversized or malformed host resource input");
  std::istringstream stream(input);
  stream.imbue(std::locale::classic());
  std::vector<std::string> result;
  std::string word;
  while (stream >> word) result.push_back(word);
  return result;
}
uint64_t integer(const std::string& input) {
  if (input.empty() || input.size() > 20 || input.find_first_not_of("0123456789") != std::string::npos)
    throw std::runtime_error("Malformed unsigned host resource value");
  return std::stoull(input);
}
double decimal(const std::string& input) {
  if (input.empty() || input.size() > 64 || input.front() == '.' || input.back() == '.' ||
      input.find_first_not_of("0123456789.") != std::string::npos ||
      std::count(input.begin(), input.end(), '.') > 1)
    throw std::runtime_error("Malformed decimal host resource value");
  std::istringstream stream(input);
  stream.imbue(std::locale::classic());
  double result = 0;
  if (!(stream >> result) || !stream.eof() || !std::isfinite(result) || result < 0)
    throw std::runtime_error("Invalid decimal host resource value");
  return result;
}
uint64_t multiply(uint64_t value, uint64_t scale) {
  if (!scale || value > std::numeric_limits<uint64_t>::max() / scale)
    throw std::runtime_error("Host resource byte count overflow or invalid allocation unit");
  return value * scale;
}
Observation observation(daphne::HostResourceMetric metric, const char* source, const char* unit) {
  Observation result;
  result.set_metric(metric);
  result.set_source(source);
  result.set_unit(unit);
  return result;
}
void failed(Observation& item, daphne::MeasurementQuality quality, const char* detail) {
  item.clear_value();
  item.clear_observed_monotonic_ns();
  item.clear_observed_host_unix_ns();
  item.set_quality(quality);
  item.set_detail(detail);
}
void complete(Observation& item, const HostResourceTime& end) {
  if (!item.acquisition_started_monotonic_ns() || end.monotonic_ns < item.acquisition_started_monotonic_ns())
    throw std::runtime_error("Host resource acquisition clock is invalid");
  item.set_quality(daphne::MEASUREMENT_GOOD);
  item.set_observed_monotonic_ns(end.monotonic_ns);
  item.set_observed_host_unix_ns(end.host_unix_ns);
  item.set_detail("Fresh host observation, not an operational-health verdict or verified UTC");
}
template <typename Read>
void collect(HostResourceIo& io, Observation& item, Read read) {
  try {
    item.set_acquisition_started_monotonic_ns(io.now().monotonic_ns);
    read();
    complete(item, io.now());
  } catch (const Unavailable&) {
    failed(item, daphne::MEASUREMENT_UNAVAILABLE, "Host resource source or field is unavailable");
  } catch (const std::system_error& e) {
    const bool missing = e.code() == std::errc::no_such_file_or_directory || e.code() == std::errc::permission_denied;
    failed(item, missing ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR,
           missing ? "Host resource source is unavailable" : "Host resource read failed");
  } catch (const std::exception&) {
    failed(item, daphne::MEASUREMENT_ERROR, "Invalid host resource data or acquisition clock");
  }
}
class LinuxHostResources final : public HostResourceIo {
 public:
  std::string read_file(const char* path, size_t maximum) override {
    const int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) throw std::system_error(errno, std::generic_category());
    std::string data;
    try {
      char buffer[4096];
      for (;;) {
        const auto count = read(fd, buffer, std::min(sizeof(buffer), maximum + 1 - data.size()));
        if (count < 0) {
          if (errno == EINTR) continue;
          throw std::system_error(errno, std::generic_category());
        }
        if (!count) break;
        data.append(buffer, static_cast<size_t>(count));
        if (data.size() > maximum) throw std::runtime_error("Host resource input too large");
      }
    } catch (...) { close(fd); throw; }
    close(fd);
    return data;
  }
  RootFilesystemSpace root_filesystem() override {
    struct statvfs space{};
    if (statvfs("/", &space) != 0) throw std::system_error(errno, std::generic_category());
    return {space.f_frsize, space.f_blocks, space.f_bfree, space.f_bavail, (space.f_flag & ST_RDONLY) != 0};
  }
  HostResourceTime now() override { return {host_unix_time_ns(), monotonic_time_ns()}; }
};
}  // namespace

std::vector<Observation> read_host_resources(HostResourceIo& io) {
  std::vector<Observation> result{
      observation(daphne::HOST_UPTIME_SECONDS, "/proc/uptime:first field", "s"),
      observation(daphne::HOST_LOAD_AVERAGE_1MIN, "/proc/loadavg:first field", "1"),
      observation(daphne::HOST_MEMORY_AVAILABLE_BYTES, "/proc/meminfo:MemAvailable", "B"),
      observation(daphne::HOST_ROOT_FREE_BYTES, "statvfs(/):f_bfree*f_frsize", "B"),
      observation(daphne::HOST_ROOT_AVAILABLE_BYTES, "statvfs(/):f_bavail*f_frsize", "B"),
      observation(daphne::HOST_ROOT_READ_ONLY, "statvfs(/):ST_RDONLY", "1")};
  collect(io, result[0], [&] {
    const auto parts = fields(io.read_file("/proc/uptime", 4096), 4096);
    if (parts.size() != 2) throw std::runtime_error("Malformed uptime record");
    (void)decimal(parts[1]); // Combined CPU idle time may exceed host uptime.
    result[0].set_scalar_value(decimal(parts[0]));
  });
  collect(io, result[1], [&] {
    const auto parts = fields(io.read_file("/proc/loadavg", 4096), 4096);
    if (parts.size() != 5) throw std::runtime_error("Malformed load-average record");
    (void)decimal(parts[1]); (void)decimal(parts[2]); (void)integer(parts[4]);
    const auto slash = parts[3].find('/');
    if (slash == std::string::npos) throw std::runtime_error("Malformed load-average processes");
    (void)integer(parts[3].substr(0, slash)); (void)integer(parts[3].substr(slash + 1));
    result[1].set_scalar_value(decimal(parts[0]));
  });
  collect(io, result[2], [&] {
    const auto input = io.read_file("/proc/meminfo", 16384);
    (void)fields(input, 16384); // Validate size and embedded NUL before parsing lines.
    std::istringstream stream(input);
    std::string line;
    bool found = false;
    uint64_t value = 0;
    while (std::getline(stream, line)) {
      const auto parts = fields(line.empty() ? " " : line, 16384);
      if (parts.empty() || parts[0] != "MemAvailable:") continue;
      if (found || parts.size() != 3 || parts[2] != "kB") throw std::runtime_error("Malformed MemAvailable record");
      found = true;
      value = multiply(integer(parts[1]), 1024); // Kernel kB means 1024 bytes.
    }
    if (!found) throw Unavailable("MemAvailable is not supplied by this kernel");
    result[2].set_bytes_value(value);
  });
  // One statvfs observation supplies all three root-filesystem values.
  collect(io, result[3], [&] {
    const auto space = io.root_filesystem();
    if (space.free_blocks > space.blocks || space.available_blocks > space.free_blocks)
      throw std::runtime_error("Inconsistent filesystem block counts");
    const auto free_bytes = multiply(space.free_blocks, space.fragment_bytes);
    const auto available_bytes = multiply(space.available_blocks, space.fragment_bytes);
    result[3].set_bytes_value(free_bytes);
    result[4].set_bytes_value(available_bytes);
    result[5].set_flag_value(space.read_only);
  });
  for (size_t i : {size_t{4}, size_t{5}}) {
    result[i].set_acquisition_started_monotonic_ns(result[3].acquisition_started_monotonic_ns());
    if (result[3].quality() == daphne::MEASUREMENT_GOOD) {
      result[i].set_quality(result[3].quality());
      result[i].set_detail(result[3].detail());
      result[i].set_observed_monotonic_ns(result[3].observed_monotonic_ns());
      result[i].set_observed_host_unix_ns(result[3].observed_host_unix_ns());
    } else failed(result[i], result[3].quality(), result[3].detail().c_str());
  }
  return result;
}

void add_host_resources(daphne::SystemStatusSnapshot& status) {
  LinuxHostResources io;
  status.clear_host_resources();
  for (const auto& item : read_host_resources(io)) *status.add_host_resources() = item;
}
}  // namespace daphne_sc
