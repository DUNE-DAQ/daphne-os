#include "server_controller/timesync.hpp"
#include <arpa/inet.h>
#include <algorithm>
#include <limits>
#include <mutex>
#include <regex>
#include <stdexcept>
#include <system_error>

namespace daphne_sc {
namespace {
void need(bool good) { if (!good) throw std::runtime_error("Invalid timesync observation"); }
bool owner(const std::string& value) { return value.size() <= 80 && std::regex_match(value, std::regex(":[0-9]+(?:\\.[0-9]+)+")); }
bool name(const std::string& value) {
  if (value.empty()) return true;
  if (value.size() > 253) return false;
  unsigned char address[16];
  if (inet_pton(AF_INET, value.c_str(), address) == 1 || inet_pton(AF_INET6, value.c_str(), address) == 1) return true;
  std::string text = value;
  if (text.back() == '.') text.pop_back();
  if (text.empty()) return false;
  size_t start = 0;
  for (;;) {
    const auto end = text.find('.', start);
    const auto label = text.substr(start, end == std::string::npos ? end : end - start);
    if (label.empty() || label.size() > 63 || !std::regex_match(label, std::regex("[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"))) return false;
    if (end == std::string::npos) return true;
    start = end + 1;
  }
}
bool address(const std::string& value) {
  unsigned char bytes[16];
  return value.empty() || (value.size() <= 45 &&
      (inet_pton(AF_INET, value.c_str(), bytes) == 1 || inet_pton(AF_INET6, value.c_str(), bytes) == 1));
}
bool same_context(const TimesyncRaw& a, const TimesyncRaw& b) {
  return a.bus_id == b.bus_id && a.owner_before == b.owner_before &&
      a.selected_name == b.selected_name && a.selected_address == b.selected_address;
}
bool same_sample(const NtpSampleRaw& a, const NtpSampleRaw& b) {
  return a.leap == b.leap && a.version == b.version && a.mode == b.mode && a.stratum == b.stratum &&
      a.precision == b.precision && a.root_delay_us == b.root_delay_us && a.root_dispersion_us == b.root_dispersion_us &&
      a.timestamps_us == b.timestamps_us && a.ignored_spike == b.ignored_spike && a.jitter_us == b.jitter_us;
}
daphne::NtpSampleObservation decode(const NtpSampleRaw& raw) {
  daphne::NtpSampleObservation result;
  result.set_age_bound_quality(daphne::MEASUREMENT_UNAVAILABLE);
  if (!raw.count) {
    result.set_quality(daphne::MEASUREMENT_UNAVAILABLE);
    result.set_detail("No processed NTP sample reported; zero-filled daemon state is not a measurement");
    return result;
  }
  try {
    need(raw.leap <= 2 && (raw.version == 3 || raw.version == 4) && raw.mode == 4 && raw.stratum > 0 && raw.stratum < 16);
    need(raw.precision >= -128 && raw.precision <= 127);
    for (auto stamp : raw.timestamps_us) need(stamp > 0 && stamp <= static_cast<uint64_t>(INT64_MAX) / 1000);
    const auto t1 = static_cast<__int128>(raw.timestamps_us[0]), t2 = static_cast<__int128>(raw.timestamps_us[1]);
    const auto t3 = static_cast<__int128>(raw.timestamps_us[2]), t4 = static_cast<__int128>(raw.timestamps_us[3]);
    const auto delay = (t4 - t1) - (t3 - t2);
    const auto offset = ((t2 - t1) + (t3 - t4)) * 500; // Preserve half-microsecond units exactly.
    need(t4 >= t1 && t3 >= t2 && delay >= 0 && delay <= static_cast<__int128>(UINT64_MAX) / 1000);
    need(offset >= INT64_MIN && offset <= INT64_MAX);
    result.set_leap(raw.leap); result.set_version(raw.version); result.set_mode(raw.mode); result.set_stratum(raw.stratum);
    result.set_precision_exponent(raw.precision);
    result.set_root_delay_us(raw.root_delay_us); result.set_root_dispersion_us(raw.root_dispersion_us);
    result.set_origin_unix_us(raw.timestamps_us[0]); result.set_receive_unix_us(raw.timestamps_us[1]);
    result.set_transmit_unix_us(raw.timestamps_us[2]); result.set_destination_unix_us(raw.timestamps_us[3]);
    result.set_ignored_spike(raw.ignored_spike); result.set_jitter_us(raw.jitter_us);
    result.set_offset_ns(static_cast<int64_t>(offset)); result.set_round_trip_delay_ns(static_cast<uint64_t>(delay) * 1000);
    result.set_quality(daphne::MEASUREMENT_GOOD);
    result.set_detail("Historical processed response; ignored-spike flag retained. Not a present offset, successful adjustment, authenticated peer or fresh UTC guarantee");
  } catch (const std::exception&) {
    result.Clear();
    result.set_quality(daphne::MEASUREMENT_ERROR);
    result.set_age_bound_quality(daphne::MEASUREMENT_UNAVAILABLE);
    result.set_detail("Invalid historical NTP sample; fields withheld");
  }
  return result;
}
}  // namespace

void TimesyncHistory::reset() { prior_.reset(); prior_start_ = prior_end_ = 0; not_before_.reset(); }
std::optional<uint64_t> TimesyncHistory::observe(const TimesyncRaw& raw, uint64_t start, uint64_t end) {
  need(start && end >= start);
  if (!prior_ || !same_context(*prior_, raw) || start < prior_end_ || raw.sample.count < prior_->sample.count) {
    not_before_.reset();
  } else if (raw.sample.count > prior_->sample.count) {
    not_before_ = prior_start_; // New response was processed after the preceding snapshot read.
  } else if (!same_sample(raw.sample, prior_->sample)) {
    // Equal count but changed payload does not establish a stable sample epoch.
    not_before_.reset();
  }
  prior_ = raw; prior_start_ = start; prior_end_ = end;
  return raw.sample.count ? not_before_ : std::nullopt;
}

daphne::TimesyncObservation read_timesync(TimesyncIo& io, TimesyncHistory& history, bool private_details) {
  daphne::TimesyncObservation result;
  result.set_source("local system bus:org.freedesktop.timesync1.Manager:GetAll");
  try {
    const auto start = io.monotonic_ns();
    result.set_acquisition_started_monotonic_ns(start);
    need(start && start <= UINT64_MAX - kTimesyncMaximumCollectionNs);
    const auto raw = io.query(start + kTimesyncMaximumCollectionNs);
    const auto end = io.monotonic_ns();
    need(end >= start && end - start <= kTimesyncMaximumCollectionNs);
    need(std::regex_match(raw.bus_id, std::regex("[0-9a-f]{32}")) && owner(raw.owner_before));
    need(raw.owner_before == raw.owner_after && raw.owner_before == raw.reply_sender);
    need(name(raw.selected_name) && address(raw.selected_address));
    need(raw.poll_min_us > 0 && raw.poll_max_us >= raw.poll_min_us && raw.root_max_us > 0);
    need(raw.poll_us == 0 || (raw.poll_us >= raw.poll_min_us && raw.poll_us <= raw.poll_max_us));
    result.set_bus_id(raw.bus_id); result.set_unique_owner(raw.owner_before);
    result.set_owner_bracket_verified(true); result.set_details_included(private_details);
    result.set_selected_name_present(!raw.selected_name.empty());
    result.set_selected_address_present(!raw.selected_address.empty());
    if (private_details && !raw.selected_name.empty()) result.set_selected_server_name(raw.selected_name);
    if (private_details && !raw.selected_address.empty()) result.set_selected_server_address(raw.selected_address);
    result.set_poll_interval_us(raw.poll_us); result.set_poll_minimum_us(raw.poll_min_us); result.set_poll_maximum_us(raw.poll_max_us);
    result.set_root_distance_maximum_us(raw.root_max_us); result.set_frequency_scaled_ppm(raw.frequency_scaled_ppm);
    result.set_processed_packet_count(raw.sample.count);
    *result.mutable_last_sample() = decode(raw.sample);
    if (result.last_sample().quality() == daphne::MEASUREMENT_ERROR) history.reset();
    else {
      const auto bound = history.observe(raw, start, end);
      if (bound && result.last_sample().quality() == daphne::MEASUREMENT_GOOD) {
        need(*bound <= start);
        result.mutable_last_sample()->set_age_bound_quality(daphne::MEASUREMENT_GOOD);
        result.mutable_last_sample()->set_not_before_monotonic_ns(*bound);
        result.mutable_last_sample()->set_maximum_age_ns(end - *bound);
      }
    }
    result.set_observed_monotonic_ns(end); result.set_quality(daphne::MEASUREMENT_GOOD);
    result.set_detail("Pinned-owner service observation, not active-unit health or synchronization. Selected peer is not necessarily the origin of a retained sample. Unavailable sample age is not zero");
  } catch (const std::exception& error) {
    history.reset();
    const auto* system = dynamic_cast<const std::system_error*>(&error);
    const auto code = system ? system->code() : std::error_code{};
    const bool absent = system && (code == std::errc::no_such_file_or_directory || code == std::errc::no_such_process ||
        code == std::errc::permission_denied || code == std::errc::operation_not_permitted || code == std::errc::connection_refused);
    const auto start = result.acquisition_started_monotonic_ns();
    const auto source = result.source();
    result.Clear(); result.set_source(source); result.set_acquisition_started_monotonic_ns(start);
    result.set_quality(absent ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR);
    result.set_detail(absent ? "Timesync service/bus unavailable; no service activation attempted" : "Timesync query, owner, data or acquisition validation failed; private details suppressed");
    result.mutable_last_sample()->set_quality(daphne::MEASUREMENT_UNAVAILABLE);
    result.mutable_last_sample()->set_age_bound_quality(daphne::MEASUREMENT_UNAVAILABLE);
    result.mutable_last_sample()->set_detail("No usable current service observation");
  }
  return result;
}

void add_timesync_status(daphne::SystemStatusSnapshot& status, bool private_details) {
  static std::mutex mutex;
  static TimesyncHistory history;
  std::lock_guard<std::mutex> lock(mutex);
  auto io = make_linux_timesync_io();
  *status.mutable_host_time()->mutable_timesync() = read_timesync(*io, history, private_details);
}
}  // namespace daphne_sc
