#pragma once

#include <cstdint>
#include <sys/timex.h>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
struct HostClockValue { int64_t seconds; int64_t nanoseconds; };
enum class HostClockId { Realtime, Boottime };
struct KernelClockValue {
  int state;
  int status;
  int64_t offset;
  int64_t maximum_error_us;
  int64_t estimated_error_us;
};
class HostClockIo {
 public:
  virtual ~HostClockIo() = default;
  virtual uint64_t monotonic_ns() = 0;
  virtual HostClockValue clock(HostClockId id) = 0;
  virtual KernelClockValue discipline() = 0;
};
constexpr uint64_t kHostClockMaximumCollectionNs = 250'000'000;
constexpr uint64_t kHostClockStepToleranceNs = 1'000'000;
// The one production adjtimex call is value-initialized, with modes=0. The
// injectable syscall seam lets tests verify the exact no-adjustment request.
KernelClockValue query_kernel_clock(int (*query)(struct timex*));
daphne::HostTimeStatus read_host_clock(HostClockIo& io);
// Fixed clock_gettime clocks and adjtimex(modes=0) only; no files, processes,
// privileges, network, time-setting, service activation or FPGA accesses.
void add_host_clock(daphne::SystemStatusSnapshot& status);
}  // namespace daphne_sc
