#include "server_controller/native_timestamp.hpp"
#include "server_controller/timing_status.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

#define REQUIRE(x) do { if (!(x)) throw std::runtime_error("Native timestamp test failed at line " + std::to_string(__LINE__)); } while (0)
namespace {
using namespace daphne_sc;
struct Access { uint32_t offset, value; bool fail = false; };
struct Fixture : Mmio32 {
  std::vector<Access> script;
  size_t reads = 0, writes = 0, clock_reads = 0;
  uint64_t now = 1000000000, step = 1000;
  std::vector<uint64_t> clock_values;
  uint32_t read32(uint64_t address) override {
    REQUIRE(reads < script.size());
    const auto expected = script.at(reads++);
    REQUIRE(address == kTimingRegisterBase + expected.offset);
    if (expected.fail) throw std::runtime_error("injected read failure");
    return expected.value;
  }
  void write32(uint64_t, uint32_t) override { ++writes; throw std::runtime_error("Unexpected write"); }
  void header(uint32_t abi = kNativeTimestampAbi, uint32_t budget = 1024) {
    script.push_back({0x10, abi}); script.push_back({0x28, budget});
  }
  void attempt(uint32_t seq, uint32_t status, uint64_t ticks,
               bool conflict = false, bool status_conflict = false, bool late_conflict = false) {
    script.insert(script.end(), {{0x18, seq}, {0x14, status}, {0x18, seq + (conflict ? 2U : 1U)},
      {0x1c, status_conflict ? status ^ 2U : status}, {0x20, uint32_t(ticks)}, {0x24, uint32_t(ticks >> 32)},
      {0x18, seq + (conflict || late_conflict ? 2U : 1U)}});
  }
  void pair(uint64_t first = 100, uint64_t second = 200, uint32_t status = 0x13) {
    header(); attempt(40, status, first); attempt(41, status, second); header();
  }
  daphne::NativeTimestampObservation run(uint32_t abi = kGatewareAbiV21) {
    auto result = read_native_timestamp(*this, abi, [&] {
      if (!clock_values.empty()) {
        REQUIRE(clock_reads < clock_values.size());
        return clock_values.at(clock_reads++);
      }
      const auto result = now; now += step; ++clock_reads; return result;
    });
    REQUIRE(writes == 0);
    daphne::NativeTimestampObservation decoded;
    REQUIRE(decoded.ParseFromString(result.SerializeAsString()));
    REQUIRE(decoded.SerializeAsString() == result.SerializeAsString());
    return result;
  }
};
void no_usable_values(const daphne::NativeTimestampObservation& r) {
  REQUIRE(!r.has_advancing() && !r.has_delta_ticks() && !r.identity_bracket_verified());
  for (const auto& sample : r.samples()) REQUIRE(!sample.has_timestamp_ticks());
}
void test_no_alias_probes() {
  for (uint32_t abi : {kGatewareAbiV2, 0U, 0x00020002U, 0x00010000U, 0xffffffffU}) {
    Fixture f; auto result = f.run(abi);
    REQUIRE(result.quality() == daphne::MEASUREMENT_UNAVAILABLE);
    REQUIRE(f.reads == 0 && f.clock_reads == 0 && result.samples_size() == 0);
    no_usable_values(result);
  }
}
void test_valid_pairs() {
  for (uint32_t status : {0x11U, 0x13U}) {
    for (auto values : {std::pair<uint64_t, uint64_t>{0, 1}, {0xfffffff0ULL, 0x10000000fULL},
                        {UINT64_MAX - 4, 2}, {UINT64_MAX, 0}, {500, 500}, {500, 499}}) {
      Fixture f; f.pair(values.first, values.second, status); auto r = f.run();
      const auto delta = values.second - values.first;
      REQUIRE(r.quality() == daphne::MEASUREMENT_GOOD && r.samples_size() == 2);
      REQUIRE(f.reads == 18 && f.reads == f.script.size());
      REQUIRE(r.has_advancing() && r.advancing() == (delta > 0 && delta < (1ULL << 63)));
      REQUIRE(r.has_delta_ticks() && r.delta_ticks() == delta);
      REQUIRE(!r.identity_bracket_verified()); // Only the outer collector can establish admission.
      REQUIRE(native_timestamp_pair_consistent(r));
      for (int i = 0; i < 2; ++i) {
        const auto& sample = r.samples(i);
        REQUIRE(sample.quality() == daphne::MEASUREMENT_GOOD && sample.has_timestamp_ticks());
        REQUIRE(sample.timestamp_ticks() == (i == 0 ? values.first : values.second));
        REQUIRE(sample.source() == (status == 0x11 ? daphne::NATIVE_TIMESTAMP_LOCAL_COUNTER : daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS));
        REQUIRE(sample.sample_index() == unsigned(i) && sample.attempt_index() == 1);
        REQUIRE(sample.sequence_first() == 41U + i && sample.sequence_after() == 41U + i);
        REQUIRE(sample.observed_monotonic_ns() >= sample.acquisition_started_monotonic_ns());
      }
    }
  }
  Fixture f; f.header(); f.attempt(UINT32_MAX, 0x11, 100); f.attempt(0, 0x11, 200); f.header();
  auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_GOOD && r.samples(0).sequence_first() == 0);
}
void test_all_flag_patterns() {
  const std::vector<uint32_t> failures{0x04, 0x06, 0x08, 0x0a, 0x30, 0x32, 0x44, 0x46, 0x48, 0x4a, 0x50, 0x52, 0x70, 0x72};
  for (uint32_t status = 0; status < 256; ++status) {
    if (status == 0x11 || status == 0x13) continue;
    Fixture f; f.header(); f.attempt(1, status, 0); auto r = f.run();
    const bool defined_failure = std::find(failures.begin(), failures.end(), status) != failures.end();
    REQUIRE(r.quality() == (defined_failure ? daphne::MEASUREMENT_UNAVAILABLE : daphne::MEASUREMENT_ERROR));
    REQUIRE(f.reads == 9 && r.samples_size() == 1 && r.samples(0).has_low_raw());
    no_usable_values(r);
  }
  for (uint32_t status : {0xffffffffU, 0x10011U, 0x80000011U}) {
    Fixture f; f.header(); f.attempt(1, status, 0); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); no_usable_values(r);
  }
  Fixture f; f.header(); f.attempt(1, 4, 123); auto r = f.run();
  REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); no_usable_values(r);
}
void test_conflicts() {
  for (int kind = 0; kind < 3; ++kind) {
    Fixture f; f.header(); f.attempt(40, 0x13, 99, kind == 0, kind == 1, kind == 2);
    f.attempt(42, 0x13, 100); f.attempt(43, 0x13, 200); f.header(); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_GOOD && r.samples_size() == 3 && f.reads == 25);
    REQUIRE(r.samples(0).quality() == daphne::MEASUREMENT_ERROR && !r.samples(0).has_timestamp_ticks());
    REQUIRE(r.samples(1).attempt_index() == 2 && r.samples(2).sample_index() == 1);
    REQUIRE(native_timestamp_pair_consistent(r));
  }
  for (bool fail_second : {false, true}) {
    Fixture f; f.header(); if (fail_second) f.attempt(1, 0x13, 100);
    for (unsigned i = 0; i < 3; ++i) f.attempt(2 + 2*i, 0x13, 200, true);
    auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == f.script.size());
    REQUIRE(r.samples_size() == (fail_second ? 4 : 3)); no_usable_values(r);
  }
}
void test_errors_and_staleness() {
  for (size_t fail_at = 0; fail_at < 18; ++fail_at) {
    Fixture f; f.pair(); f.script.at(fail_at).fail = true; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == fail_at + 1); no_usable_values(r);
  }
  for (uint32_t budget : {0U, 7U, 1048577U, 0xffffffffU}) {
    Fixture f; f.header(kNativeTimestampAbi, budget); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 2); no_usable_values(r);
  }
  {
    Fixture f; f.header(0); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 1); no_usable_values(r);
  }
  for (size_t changed : {size_t{16}, size_t{17}}) {
    Fixture f; f.pair(); ++f.script.at(changed).value; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); no_usable_values(r);
  }
  {
    Fixture f; f.header(); f.attempt(1, 0x11, 100); f.attempt(2, 0x13, 200); f.header(); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_UNAVAILABLE); no_usable_values(r);
  }
  {
    Fixture f; f.pair(); f.step = 200000000; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_STALE && f.reads == 2); no_usable_values(r);
  }
  {
    Fixture f; f.pair(); f.clock_values = {1000000000, 1000001000, 1000002000, 1000003000, 1000004000, 1200000000};
    auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_STALE); no_usable_values(r);
    REQUIRE(r.samples(1).quality() == daphne::MEASUREMENT_STALE);
  }
  {
    Fixture f; f.pair(); f.clock_values = {1000000000, 1000005000, 1000001000};
    auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); no_usable_values(r);
  }
  {
    Fixture f; f.pair(); f.now = 0; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 0); no_usable_values(r);
  }
}
void test_pair_validation() {
  Fixture f; f.pair(); auto good = f.run(); REQUIRE(native_timestamp_pair_consistent(good));
  for (unsigned mutation = 0; mutation < 14; ++mutation) {
    auto value = good;
    switch (mutation) {
      case 0: value.mutable_samples(0)->clear_low_raw(); break;
      case 1: value.mutable_samples(0)->set_status_raw(0x11); break;
      case 2: value.mutable_samples(0)->set_timestamp_ticks(99); break;
      case 3: value.mutable_samples(1)->set_sequence_after(99); break;
      case 4: value.set_delta_ticks(0); break;
      case 5: value.set_advancing(false); break;
      case 6: value.clear_feature_abi_after(); break;
      case 7: value.mutable_samples(1)->set_sample_index(0); break;
      case 8: value.mutable_samples(0)->set_quality(daphne::MEASUREMENT_ERROR); break;
      case 9: value.mutable_samples(1)->set_observed_monotonic_ns(0); break;
      case 10: value.set_maximum_attempts_per_sample(4); break;
      case 11: value.set_maximum_acquisition_ms(101); break;
      case 12: value.mutable_samples(0)->set_attempt_index(2); break;
      case 13: value.mutable_samples()->SwapElements(0, 1); break;
    }
    REQUIRE(!native_timestamp_pair_consistent(value));
  }
}
}
int main() {
  test_no_alias_probes(); test_valid_pairs(); test_all_flag_patterns(); test_conflicts(); test_errors_and_staleness(); test_pair_validation();
  std::cout << "Native timestamp: exact ABI guard, all flag patterns, zero/rollover, bounded conflicts, faults and stale evidence passed\n";
}
