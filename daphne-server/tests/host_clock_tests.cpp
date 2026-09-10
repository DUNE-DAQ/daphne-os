#include "server_controller/host_clock.hpp"
#include <cerrno>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <system_error>
#include <vector>

using namespace daphne_sc;
void require(bool value, const char* message = "Host clock test failed") {
  if (!value) throw std::runtime_error(message);
}
struct Fake final : HostClockIo {
  std::vector<uint64_t> mono{100, 200, 300, 400};
  std::vector<HostClockValue> clocks{{1700000000, 100}, {123, 200}, {1700000000, 200}};
  KernelClockValue kernel{TIME_OK, STA_PLL | STA_NANO, -1234, 5678, 90};
  size_t mono_index = 0, clock_index = 0;
  int discipline_calls = 0, failure_clock = -1;
  int failure_errno = EIO;
  bool fail_kernel = false;
  uint64_t monotonic_ns() override { return mono.at(mono_index++); }
  HostClockValue clock(HostClockId id) override {
    require(id == (clock_index == 1 ? HostClockId::Boottime : HostClockId::Realtime));
    if (static_cast<int>(clock_index) == failure_clock) throw std::system_error(failure_errno, std::generic_category());
    return clocks.at(clock_index++);
  }
  KernelClockValue discipline() override {
    ++discipline_calls;
    if (fail_kernel) throw std::system_error(failure_errno, std::generic_category());
    return kernel;
  }
};
template<typename T>
void failed(const T& value, daphne::MeasurementQuality expected = daphne::MEASUREMENT_ERROR) {
  require(value.quality() == expected && !value.observed_monotonic_ns());
  const auto* reflection = value.GetReflection();
  for (int number = 1; number <= 6; ++number)
    require(!reflection->HasField(value, value.GetDescriptor()->FindFieldByNumber(number)));
  require(!value.source().empty() && !value.detail().empty());
}
int fake_query(struct timex* value) {
  require(value->modes == 0 && value->offset == 0 && value->freq == 0 && value->status == 0 &&
      value->maxerror == 0 && value->esterror == 0 && value->constant == 0 && value->precision == 0 &&
      value->tolerance == 0 && value->time.tv_sec == 0 && value->time.tv_usec == 0 && value->tick == 0 &&
      value->ppsfreq == 0 && value->jitter == 0 && value->shift == 0 && value->stabil == 0 &&
      value->jitcnt == 0 && value->calcnt == 0 && value->errcnt == 0 && value->stbcnt == 0 && value->tai == 0,
      "The syscall request must not adjust time");
  value->status = STA_UNSYNC;
  value->offset = -7;
  value->maxerror = 88;
  value->esterror = 99;
  return TIME_ERROR;
}
int missing_query(struct timex* value) {
  require(value->modes == 0);
  errno = ENOSYS;
  return -1;
}
int main() {
  Fake io;
  const auto result = read_host_clock(io);
  require(io.mono_index == 4 && io.clock_index == 3 && io.discipline_calls == 1);
  const auto& wall = result.clock();
  require(wall.quality() == daphne::MEASUREMENT_GOOD && wall.has_unix_time_ns());
  require(wall.unix_time_ns() == 1700000000000000200LL);
  require(wall.current_utc() == "2023-11-14T22:13:20.000000200Z");
  require(wall.boottime_ns() == 123000000200ULL);
  require(wall.boot_time_estimate_unix_ns() == 1699999876999999950LL);
  require(wall.boot_time_estimate_utc() == "2023-11-14T22:11:16.999999950Z");
  require(wall.realtime_sample_span_ns() == 100 && wall.acquisition_started_monotonic_ns() == 100 && wall.observed_monotonic_ns() == 200);
  const auto& kernel = result.kernel();
  require(kernel.quality() == daphne::MEASUREMENT_GOOD && kernel.has_reports_synchronized() && kernel.reports_synchronized());
  require(kernel.status_raw() == (STA_PLL | STA_NANO) && kernel.has_time_state_raw() && kernel.time_state_raw() == TIME_OK);
  require(kernel.adjustment_offset_ns() == -1234 && kernel.maximum_error_ns() == 5678000 && kernel.estimated_error_ns() == 90000);
  require(kernel.acquisition_started_monotonic_ns() == 300 && kernel.observed_monotonic_ns() == 400);
  daphne::HostTimeStatus decoded;
  require(decoded.ParseFromString(result.SerializeAsString()) && decoded.SerializeAsString() == result.SerializeAsString());

  for (int state = TIME_OK; state <= TIME_ERROR; ++state) {
    Fake test; test.kernel = {state, state == TIME_ERROR ? STA_UNSYNC : 0, -15, 0, 0};
    const auto observed = read_host_clock(test).kernel();
    require(observed.quality() == daphne::MEASUREMENT_GOOD && observed.has_reports_synchronized());
    require(observed.reports_synchronized() == (state != TIME_ERROR) && observed.adjustment_offset_ns() == -15000);
    require(observed.has_maximum_error_ns() && observed.maximum_error_ns() == 0 && observed.has_estimated_error_ns());
  }
  Fake epoch; epoch.clocks = {{0, 0}, {0, 0}, {0, 0}}; epoch.kernel = {TIME_OK, 0, 0, 0, 0};
  const auto zero = read_host_clock(epoch);
  require(zero.clock().quality() == daphne::MEASUREMENT_GOOD && zero.clock().has_unix_time_ns() && zero.clock().unix_time_ns() == 0);
  require(zero.clock().current_utc() == "1970-01-01T00:00:00.000000000Z" && zero.clock().has_boot_time_estimate_unix_ns());
  require(zero.kernel().has_adjustment_offset_ns() && zero.kernel().adjustment_offset_ns() == 0);
  Fake future; future.clocks = {{9223372036LL, 854775807}, {0, 0}, {9223372036LL, 854775807}};
  const auto latest = read_host_clock(future).clock();
  require(latest.unix_time_ns() == INT64_MAX && latest.current_utc() == "2262-04-11T23:47:16.854775807Z");
  Fake leap; leap.clocks = {{951782400, 0}, {0, 0}, {951782400, 0}};
  require(read_host_clock(leap).clock().current_utc() == "2000-02-29T00:00:00.000000000Z");
  for (auto invalid : std::vector<HostClockValue>{{-1, 0}, {0, -1}, {0, 1000000000}, {9223372036LL, 854775808}, {INT64_MAX, 0}}) {
    for (size_t index = 0; index < 3; ++index) {
      Fake test; test.clocks[index] = invalid;
      const auto output = read_host_clock(test);
      failed(output.clock());
      require(output.kernel().quality() == daphne::MEASUREMENT_GOOD && test.discipline_calls == 1);
    }
  }
  Fake backward; backward.clocks[2].nanoseconds = 99;
  failed(read_host_clock(backward).clock());
  Fake forward; forward.clocks[2].nanoseconds = 1000201;
  failed(read_host_clock(forward).clock());
  Fake tolerance; tolerance.clocks[2].nanoseconds = 1000200;
  require(read_host_clock(tolerance).clock().quality() == daphne::MEASUREMENT_GOOD);
  Fake pre_epoch; pre_epoch.clocks[1].seconds = 1700000001;
  failed(read_host_clock(pre_epoch).clock());
  for (const auto times : std::vector<std::vector<uint64_t>>{{0, 200, 300, 400}, {100, 99, 300, 400},
      {100, 250000101, 300000000, 300000100}, {100, 200, 0, 400}, {100, 200, 400, 399}, {100, 200, 300, 250000301}}) {
    Fake test; test.mono = times;
    const auto output = read_host_clock(test);
    if (times[0] == 0 || times[1] < times[0] || times[1] - times[0] > kHostClockMaximumCollectionNs) {
      failed(output.clock()); require(output.kernel().quality() == daphne::MEASUREMENT_GOOD);
    } else {
      failed(output.kernel()); require(output.clock().quality() == daphne::MEASUREMENT_GOOD);
    }
  }
  for (const int error : {ENOSYS, EPERM, EACCES, EIO}) {
    const auto quality = error == EIO ? daphne::MEASUREMENT_ERROR : daphne::MEASUREMENT_UNAVAILABLE;
    for (int index = 0; index < 3; ++index) {
      Fake test; test.failure_clock = index; test.failure_errno = error;
      const auto output = read_host_clock(test);
      failed(output.clock(), quality); require(output.kernel().quality() == daphne::MEASUREMENT_GOOD);
    }
    Fake test; test.fail_kernel = true; test.failure_errno = error;
    const auto output = read_host_clock(test);
    failed(output.kernel(), quality); require(output.clock().quality() == daphne::MEASUREMENT_GOOD);
  }
  for (const auto value : std::vector<KernelClockValue>{{-1, 0, 0, 0, 0}, {6, 0, 0, 0, 0}, {0, -1, 0, 0, 0},
      {0, 0, INT64_MAX, 0, 0}, {0, 0, INT64_MIN, 0, 0}, {0, 0, 0, -1, 0}, {0, 0, 0, 0, -1},
      {0, 0, 0, INT64_MAX, 0}, {0, 0, 0, 0, INT64_MAX}}) {
    Fake test; test.kernel = value;
    const auto output = read_host_clock(test);
    failed(output.kernel()); require(output.clock().quality() == daphne::MEASUREMENT_GOOD);
  }
  for (int64_t value : {INT64_MIN, INT64_MAX}) {
    Fake test; test.kernel.offset = value;
    require(read_host_clock(test).kernel().adjustment_offset_ns() == value);
  }
  for (int64_t value : {INT64_MIN / 1000, INT64_MAX / 1000}) {
    Fake test; test.kernel.status = 0; test.kernel.offset = value;
    require(read_host_clock(test).kernel().adjustment_offset_ns() == value * 1000);
  }
  const auto observed = query_kernel_clock(fake_query);
  require(observed.state == TIME_ERROR && observed.status == STA_UNSYNC && observed.offset == -7 &&
      observed.maximum_error_us == 88 && observed.estimated_error_us == 99);
  bool missing = false, null = false;
  try { (void)query_kernel_clock(missing_query); } catch (const std::system_error& e) { missing = e.code() == std::errc::function_not_supported; }
  try { (void)query_kernel_clock(nullptr); } catch (const std::invalid_argument&) { null = true; }
  require(missing && null);
  std::cout << "Host clock range, UTC, bracket, suspend-inclusive boot, kernel units/state, failure, wire and zero-mode syscall tests passed\n";
}
