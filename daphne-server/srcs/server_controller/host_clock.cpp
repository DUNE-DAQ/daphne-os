#include "server_controller/host_clock.hpp"

#include <cerrno>
#include <cstdio>
#include <ctime>
#include <limits>
#include <stdexcept>
#include <system_error>

namespace daphne_sc {
namespace {
constexpr int64_t billion = 1'000'000'000;
constexpr int64_t maximum = std::numeric_limits<int64_t>::max();
int64_t nanoseconds(HostClockValue value) {
  // UNIX nanoseconds use the workbook's signed Long. Negative wall time and
  // values beyond 2262 are explicitly unsupported, never unsigned-wrapped.
  if (value.seconds < 0 || value.nanoseconds < 0 || value.nanoseconds >= billion ||
      value.seconds > (maximum - value.nanoseconds) / billion)
    throw std::runtime_error("Invalid clock value");
  return value.seconds * billion + value.nanoseconds;
}
std::string utc(int64_t value) {
  const time_t seconds = static_cast<time_t>(value / billion);
  if (static_cast<int64_t>(seconds) != value / billion) throw std::runtime_error("Clock range unsupported");
  struct tm calendar{};
  if (!gmtime_r(&seconds, &calendar)) throw std::runtime_error("Clock conversion failed");
  char output[40];
  const auto size = std::snprintf(output, sizeof(output), "%04d-%02d-%02dT%02d:%02d:%02d.%09lldZ",
      calendar.tm_year + 1900, calendar.tm_mon + 1, calendar.tm_mday,
      calendar.tm_hour, calendar.tm_min, calendar.tm_sec,
      static_cast<long long>(value % billion));
  if (size != 30) throw std::runtime_error("Clock formatting failed");
  return std::string(output, static_cast<size_t>(size));
}
uint64_t end_time(HostClockIo& io, uint64_t start) {
  const auto end = io.monotonic_ns();
  if (!start || end < start || end - start > kHostClockMaximumCollectionNs)
    throw std::runtime_error("Invalid clock acquisition bracket");
  return end;
}
int64_t offset_ns(const KernelClockValue& value) {
  const int64_t scale = value.status & STA_NANO ? 1 : 1000;
  if (value.offset > maximum / scale || value.offset < std::numeric_limits<int64_t>::min() / scale)
    throw std::runtime_error("Kernel clock offset overflow");
  return value.offset * scale;
}
uint64_t error_ns(int64_t value) {
  if (value < 0 || static_cast<uint64_t>(value) > UINT64_MAX / 1000)
    throw std::runtime_error("Invalid kernel clock error estimate");
  return static_cast<uint64_t>(value) * 1000;
}
template <typename Observation>
void failure(Observation& item, daphne::MeasurementQuality quality) {
  // Never leave partially decoded values or success timestamps on failure.
  const auto start = item.acquisition_started_monotonic_ns();
  const auto source = item.source();
  item.Clear();
  item.set_acquisition_started_monotonic_ns(start);
  item.set_source(source);
  item.set_quality(quality);
  item.set_detail(quality == daphne::MEASUREMENT_UNAVAILABLE ?
      "Host clock source unavailable" : "Host clock read, range or acquisition validation failed");
}
template <typename Observation, typename Read>
void collect(HostClockIo& io, Observation& item, Read read) {
  try {
    item.set_acquisition_started_monotonic_ns(io.monotonic_ns());
    read();
  } catch (const std::system_error& error) {
    const auto code = error.code();
    failure(item, code == std::errc::function_not_supported || code == std::errc::permission_denied ||
        code == std::errc::operation_not_permitted ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR);
  } catch (const std::exception&) {
    failure(item, daphne::MEASUREMENT_ERROR);
  }
}
HostClockValue linux_clock(clockid_t id) {
  struct timespec value{};
  if (clock_gettime(id, &value) != 0) throw std::system_error(errno, std::generic_category());
  return {value.tv_sec, value.tv_nsec};
}
class LinuxHostClock final : public HostClockIo {
 public:
  uint64_t monotonic_ns() override { return static_cast<uint64_t>(nanoseconds(linux_clock(CLOCK_MONOTONIC))); }
  HostClockValue clock(HostClockId id) override {
    return linux_clock(id == HostClockId::Realtime ? CLOCK_REALTIME : CLOCK_BOOTTIME);
  }
  KernelClockValue discipline() override { return query_kernel_clock(adjtimex); }
};
}  // namespace

KernelClockValue query_kernel_clock(int (*query)(struct timex*)) {
  if (!query) throw std::invalid_argument("Missing kernel clock query");
  struct timex value{}; // modes=0: read current parameters, never adjust them.
  const int state = query(&value);
  if (state < 0) throw std::system_error(errno, std::generic_category());
  return {state, value.status, value.offset, value.maxerror, value.esterror};
}

daphne::HostTimeStatus read_host_clock(HostClockIo& io) {
  daphne::HostTimeStatus result;
  auto& clock = *result.mutable_clock();
  clock.set_source("clock_gettime:CLOCK_REALTIME/CLOCK_BOOTTIME; CLOCK_MONOTONIC bracket");
  collect(io, clock, [&] {
    const auto before = nanoseconds(io.clock(HostClockId::Realtime));
    const auto boot = nanoseconds(io.clock(HostClockId::Boottime));
    const auto after = nanoseconds(io.clock(HostClockId::Realtime));
    const auto end = end_time(io, clock.acquisition_started_monotonic_ns());
    // Reject observed backward/large forward steps. This is not proof that no
    // small or compensating step occurred between samples; expose the span.
    if (after < before || static_cast<uint64_t>(after - before) >
        end - clock.acquisition_started_monotonic_ns() + kHostClockStepToleranceNs)
      throw std::runtime_error("Wall clock discontinuity");
    const auto middle = before + (after - before) / 2;
    if (middle < boot) throw std::runtime_error("Derived boot time before supported epoch");
    const auto boot_estimate = middle - boot;
    clock.set_unix_time_ns(after);
    clock.set_current_utc(utc(after));
    clock.set_boottime_ns(static_cast<uint64_t>(boot));
    clock.set_boot_time_estimate_unix_ns(boot_estimate);
    clock.set_boot_time_estimate_utc(utc(boot_estimate));
    clock.set_realtime_sample_span_ns(static_cast<uint64_t>(after - before));
    clock.set_observed_monotonic_ns(end);
    clock.set_quality(daphne::MEASUREMENT_GOOD);
    clock.set_detail("Local wall clock, not verified UTC or FPGA time. Boot estimate is realtime midpoint minus suspend-inclusive BOOTTIME; not a persisted boot event or certified uncertainty bound");
  });
  auto& kernel = *result.mutable_kernel();
  kernel.set_source("adjtimex:modes=0");
  collect(io, kernel, [&] {
    const auto value = io.discipline();
    if (value.state < TIME_OK || value.state > TIME_ERROR || value.status < 0)
      throw std::runtime_error("Invalid kernel clock state");
    kernel.set_time_state_raw(static_cast<uint32_t>(value.state));
    kernel.set_status_raw(static_cast<uint32_t>(value.status));
    kernel.set_reports_synchronized(value.state != TIME_ERROR);
    kernel.set_adjustment_offset_ns(offset_ns(value));
    kernel.set_maximum_error_ns(error_ns(value.maximum_error_us));
    kernel.set_estimated_error_ns(error_ns(value.estimated_error_us));
    kernel.set_observed_monotonic_ns(end_time(io, kernel.acquisition_started_monotonic_ns()));
    kernel.set_quality(daphne::MEASUREMENT_GOOD);
    kernel.set_detail("Kernel discipline state, not independent UTC verification or a fresh NTP exchange. Offset is kernel adjustment state, NOT NtpOffsetMilliseconds or FPGA timestamp error; error estimates are not measured bounds");
  });
  return result;
}

void add_host_clock(daphne::SystemStatusSnapshot& status) {
  LinuxHostClock io;
  *status.mutable_host_time() = read_host_clock(io);
  const auto& clock = status.host_time().clock();
  // Legacy aliases use the exact same observation, not a separate clock read.
  status.clear_ps_local_time();
  status.clear_ps_local_unix_ns();
  if (clock.quality() == daphne::MEASUREMENT_GOOD) {
    status.set_ps_local_time(clock.current_utc());
    status.set_ps_local_unix_ns(static_cast<uint64_t>(clock.unix_time_ns()));
  }
}
}  // namespace daphne_sc
