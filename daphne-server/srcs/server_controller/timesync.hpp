#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
constexpr uint64_t kTimesyncMaximumCollectionNs = 2'000'000'000;
struct NtpSampleRaw {
  uint32_t leap = 0, version = 0, mode = 0, stratum = 0;
  int32_t precision = 0;
  uint64_t root_delay_us = 0, root_dispersion_us = 0;
  std::array<uint64_t, 4> timestamps_us{};
  bool ignored_spike = false;
  uint64_t count = 0, jitter_us = 0;
};
struct TimesyncRaw {
  std::string bus_id, owner_before, owner_after, reply_sender;
  std::string selected_name, selected_address;
  uint64_t poll_us = 0, poll_min_us = 0, poll_max_us = 0, root_max_us = 0;
  int64_t frequency_scaled_ppm = 0;
  NtpSampleRaw sample;
};
class TimesyncIo {
 public:
  virtual ~TimesyncIo() = default;
  virtual uint64_t monotonic_ns() = 0;
  virtual TimesyncRaw query(uint64_t deadline_ns) = 0;
};
// Tracking is local to this server process. It only supplies conservative age
// bounds after count progress, never from wall time or a first observation.
class TimesyncHistory {
 public:
  void reset();
  std::optional<uint64_t> observe(const TimesyncRaw&, uint64_t start, uint64_t end);
 private:
  std::optional<TimesyncRaw> prior_;
  uint64_t prior_start_ = 0, prior_end_ = 0;
  std::optional<uint64_t> not_before_;
};
daphne::TimesyncObservation read_timesync(TimesyncIo&, TimesyncHistory&, bool include_private = false);
std::unique_ptr<TimesyncIo> make_linux_timesync_io();
void add_timesync_status(daphne::SystemStatusSnapshot&, bool include_private = false);
}  // namespace daphne_sc
