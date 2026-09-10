#include "server_controller/timesync.hpp"
#include <iostream>
#include <stdexcept>
#include <system_error>

using namespace daphne_sc;
void require(bool value) { if (!value) throw std::runtime_error("Timesync test failed"); }
TimesyncRaw fixture() {
  TimesyncRaw value;
  value.bus_id = std::string(32, 'a');
  value.owner_before = value.owner_after = value.reply_sender = ":1.55";
  value.selected_name = "ntp.example.invalid"; value.selected_address = "192.0.2.10";
  value.poll_us = value.poll_min_us = 32'000'000; value.poll_max_us = 2'048'000'000; value.root_max_us = 5'000'000;
  value.frequency_scaled_ppm = -123456;
  value.sample = {0, 4, 4, 2, -20, 1000, 2000,
      {1'700'000'000'000'000, 1'700'000'000'000'101, 1'700'000'000'000'111, 1'700'000'000'000'200}, false, 1, 300};
  return value;
}
struct Fake final : TimesyncIo {
  TimesyncRaw value = fixture();
  uint64_t start = 100, end = 200;
  unsigned times = 0, calls = 0;
  int failure = 0;
  uint64_t monotonic_ns() override { return times++ % 2 ? end : start; }
  TimesyncRaw query(uint64_t deadline) override {
    ++calls; require(deadline == start + kTimesyncMaximumCollectionNs);
    if (failure) throw std::system_error(failure, std::generic_category());
    return value;
  }
};
void no_sample_values(const daphne::NtpSampleObservation& sample) {
  for (int number = 3; number <= 17; ++number)
    require(!sample.GetReflection()->HasField(sample, sample.GetDescriptor()->FindFieldByNumber(number)));
  require(!sample.has_maximum_age_ns() && !sample.has_not_before_monotonic_ns());
}
void bad(const daphne::TimesyncObservation& value, daphne::MeasurementQuality quality = daphne::MEASUREMENT_ERROR) {
  require(value.quality() == quality && !value.observed_monotonic_ns() && !value.owner_bracket_verified());
  require(value.bus_id().empty() && value.unique_owner().empty() && !value.details_included());
  for (int number = 10; number <= 19; ++number)
    require(!value.GetReflection()->HasField(value, value.GetDescriptor()->FindFieldByNumber(number)));
  no_sample_values(value.last_sample());
}
int main() {
  Fake io; TimesyncHistory history;
  auto first = read_timesync(io, history);
  require(io.calls == 1 && first.quality() == daphne::MEASUREMENT_GOOD && first.owner_bracket_verified());
  require(first.selected_name_present() && first.selected_address_present());
  require(!first.details_included() && !first.has_selected_server_name() && !first.has_selected_server_address());
  require(first.last_sample().quality() == daphne::MEASUREMENT_GOOD);
  require(first.last_sample().offset_ns() == 6000 && first.last_sample().round_trip_delay_ns() == 190000);
  require(first.last_sample().has_ignored_spike() && !first.last_sample().ignored_spike());
  require(first.last_sample().age_bound_quality() == daphne::MEASUREMENT_UNAVAILABLE && !first.last_sample().has_maximum_age_ns());
  require(first.SerializeAsString().find("example.invalid") == std::string::npos && first.SerializeAsString().find("192.0.2.10") == std::string::npos);
  daphne::TimesyncObservation roundtrip;
  require(roundtrip.ParseFromString(first.SerializeAsString()) && roundtrip.SerializeAsString() == first.SerializeAsString());
  io.start = 300; io.end = 400; ++io.value.sample.count;
  const auto update = read_timesync(io, history, true);
  require(update.last_sample().not_before_monotonic_ns() == 100 && update.last_sample().maximum_age_ns() == 300);
  require(update.details_included() && update.selected_server_name() == "ntp.example.invalid" && update.selected_server_address() == "192.0.2.10");
  io.start = 1'000'000'000; io.end = io.start + 100;
  const auto old = read_timesync(io, history);
  require(old.last_sample().not_before_monotonic_ns() == 100 && old.last_sample().maximum_age_ns() == 1'000'000'000);
  require(!old.has_selected_server_name()); // A private request does not change later redaction.
  for (int kind = 0; kind < 7; ++kind) {
    Fake test; TimesyncHistory tracker;
    (void)read_timesync(test, tracker);
    test.start = 300; test.end = 400; ++test.value.sample.count;
    require(read_timesync(test, tracker).last_sample().has_maximum_age_ns());
    test.start = 500; test.end = 600;
    if (kind == 0) test.value.bus_id = std::string(32, 'b');
    if (kind == 1) test.value.owner_before = test.value.owner_after = test.value.reply_sender = ":1.56";
    if (kind == 2) test.value.selected_name = "another.example.invalid";
    if (kind == 3) test.value.selected_address = "2001:db8::1";
    if (kind == 4) test.value.sample.count = 1;
    if (kind == 5) ++test.value.sample.timestamps_us[1];
    if (kind == 6) { test.start = 399; test.end = 400; }
    require(!read_timesync(test, tracker).last_sample().has_maximum_age_ns());
  }
  Fake none; none.value.sample = {}; TimesyncHistory empty;
  const auto absent = read_timesync(none, empty);
  require(absent.quality() == daphne::MEASUREMENT_GOOD && absent.has_processed_packet_count() && absent.processed_packet_count() == 0);
  require(absent.last_sample().quality() == daphne::MEASUREMENT_UNAVAILABLE); no_sample_values(absent.last_sample());
  none.start = 300; none.end = 400; none.value.sample = fixture().sample;
  require(read_timesync(none, empty).last_sample().maximum_age_ns() == 300);
  Fake spike; spike.value.sample.ignored_spike = true; TimesyncHistory spike_history;
  require(read_timesync(spike, spike_history).last_sample().ignored_spike());
  for (int kind = 0; kind < 11; ++kind) {
    Fake test; TimesyncHistory tracker;
    if (kind == 0) test.value.bus_id = "private-secret";
    if (kind == 1) test.value.owner_before = "other.service";
    if (kind == 2) test.value.owner_after = ":1.999";
    if (kind == 3) test.value.reply_sender = ":1.999";
    if (kind == 4) test.value.selected_name = "private/secret";
    if (kind == 5) test.value.selected_address = "private-secret";
    if (kind == 6) test.value.poll_min_us = 0;
    if (kind == 7) test.value.poll_max_us = test.value.poll_min_us - 1;
    if (kind == 8) test.value.root_max_us = 0;
    if (kind == 9) test.value.poll_us = 1;
    if (kind == 10) test.value.poll_us = test.value.poll_max_us + 1;
    const auto invalid = read_timesync(test, tracker, true); bad(invalid);
    require(invalid.SerializeAsString().find("private") == std::string::npos || invalid.detail().find("private details suppressed") != std::string::npos);
    require(invalid.SerializeAsString().find("private-secret") == std::string::npos);
  }
  for (int code : {ENOENT, ESRCH, EPERM, EACCES, ECONNREFUSED, EIO, ETIMEDOUT}) {
    Fake test; TimesyncHistory tracker; (void)read_timesync(test, tracker);
    test.failure = code; test.start = 300; test.end = 400;
    bad(read_timesync(test, tracker), code == EIO || code == ETIMEDOUT ? daphne::MEASUREMENT_ERROR : daphne::MEASUREMENT_UNAVAILABLE);
    test.failure = 0; test.times = 0; test.start = 500; test.end = 600; ++test.value.sample.count;
    require(!read_timesync(test, tracker).last_sample().has_maximum_age_ns());
  }
  for (int kind = 0; kind < 4; ++kind) {
    Fake test; TimesyncHistory tracker;
    if (kind == 0) test.start = 0;
    if (kind == 1) test.start = UINT64_MAX;
    if (kind == 2) test.end = 99;
    if (kind == 3) test.end = test.start + kTimesyncMaximumCollectionNs + 1;
    bad(read_timesync(test, tracker));
  }
  for (int kind = 0; kind < 10; ++kind) {
    Fake test; TimesyncHistory tracker;
    if (kind == 0) test.value.sample.leap = 3;
    if (kind == 1) test.value.sample.version = 2;
    if (kind == 2) test.value.sample.mode = 3;
    if (kind == 3) test.value.sample.stratum = 16;
    if (kind == 4) test.value.sample.precision = 128;
    if (kind == 5) test.value.sample.timestamps_us[0] = 0;
    if (kind == 6) test.value.sample.timestamps_us[3] = test.value.sample.timestamps_us[0] - 1;
    if (kind == 7) test.value.sample.timestamps_us[2] = test.value.sample.timestamps_us[1] - 1;
    if (kind == 8) test.value.sample.timestamps_us[2] += 1000;
    if (kind == 9) test.value.sample.timestamps_us[1] = UINT64_MAX;
    const auto invalid = read_timesync(test, tracker);
    require(invalid.quality() == daphne::MEASUREMENT_GOOD && invalid.last_sample().quality() == daphne::MEASUREMENT_ERROR);
    no_sample_values(invalid.last_sample());
  }
  Fake wide; TimesyncHistory wide_history;
  wide.value.sample.count = UINT64_MAX; wide.value.sample.timestamps_us = {100, 105, 115, 121};
  auto exact = read_timesync(wide, wide_history);
  require(exact.processed_packet_count() == UINT64_MAX && exact.last_sample().offset_ns() == -500);
  wide.value.sample.timestamps_us = {static_cast<uint64_t>(INT64_MAX)/1000 - 200, static_cast<uint64_t>(INT64_MAX)/1000 - 100,
      static_cast<uint64_t>(INT64_MAX)/1000 - 99, static_cast<uint64_t>(INT64_MAX)/1000};
  wide.times = 0; TimesyncHistory maximum_history;
  exact = read_timesync(wide, maximum_history);
  require(exact.last_sample().quality() == daphne::MEASUREMENT_GOOD && exact.last_sample().offset_ns() == 500);
  Fake no_peer; TimesyncHistory no_peer_history;
  no_peer.value.selected_name.clear(); no_peer.value.selected_address.clear(); no_peer.value.poll_us = 0; no_peer.value.sample = {};
  const auto unknown = read_timesync(no_peer, no_peer_history, true);
  require(unknown.quality() == daphne::MEASUREMENT_GOOD && unknown.has_selected_name_present() && !unknown.selected_name_present());
  require(unknown.has_selected_address_present() && !unknown.selected_address_present() && !unknown.has_selected_server_name());
  std::cout << "Timesync sample arithmetic, history age bounds, restart/gap handling, privacy, quality and wire tests passed\n";
}
