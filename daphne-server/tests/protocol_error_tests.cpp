#include "server_controller/protocol_errors.hpp"
#include "server_controller/timing_status.hpp"
#include <iostream>
#include <stdexcept>
#include <vector>
#define REQUIRE(x) do { if (!(x)) throw std::runtime_error("Protocol history test failed at line " + std::to_string(__LINE__)); } while (0)
namespace {
using namespace daphne_sc;
struct Access { uint32_t offset, value; bool fail = false; };
struct Fixture : Mmio32 {
  std::vector<Access> script;
  size_t reads = 0, writes = 0, clocks = 0;
  uint64_t now = 1000000000, step = 1000;
  std::vector<uint64_t> clock_values;
  uint32_t read32(uint64_t address) override {
    REQUIRE(reads < script.size());
    const auto access = script.at(reads++);
    REQUIRE(address == kTimingRegisterBase + access.offset);
    if (access.fail) throw std::runtime_error("private injected failure must not escape");
    return access.value;
  }
  void write32(uint64_t, uint32_t) override { ++writes; throw std::runtime_error("Unexpected write"); }
  void header(uint32_t feature = kProtocolErrorAbi, uint32_t timeout = 1024) {
    script.push_back({0x30, feature}); script.push_back({0x48, timeout});
  }
  void attempt(uint32_t seq = 40, uint32_t status = 0x11, uint32_t count = 0, uint32_t detail = 0,
               unsigned conflict = 0) {
    script.insert(script.end(), {{0x38, seq}, {0x34, status},
        {0x38, seq + (conflict == 1 ? 2U : 1U)}, {0x3c, conflict == 2 ? status ^ 1U : status},
        {0x40, count}, {0x44, detail}, {0x38, seq + (conflict == 3 ? 2U : 1U)}});
  }
  void complete(uint32_t count = 0, uint32_t detail = 0, uint32_t status = 0x11) {
    header(); attempt(40, status, count, detail); header();
  }
  daphne::ProtocolErrorObservation run(uint32_t abi = kGatewareAbiV22) {
    auto r = read_protocol_error_history(*this, abi, [&] {
      ++clocks;
      if (!clock_values.empty()) return clock_values.at(clocks - 1);
      const auto value = now; now += step; return value;
    });
    REQUIRE(writes == 0);
    daphne::ProtocolErrorObservation copy;
    REQUIRE(copy.ParseFromString(r.SerializeAsString()) && copy.SerializeAsString() == r.SerializeAsString());
    REQUIRE(r.message().find("private") == std::string::npos);
    return r;
  }
};
void unavailable(const daphne::ProtocolErrorObservation& r) {
  REQUIRE(!r.has_count() && !r.has_reasons_seen() && !r.has_saturated() && !r.has_overflowed() &&
          !r.has_receiver_reset() && !r.identity_bracket_verified() && !r.reset_epoch_known());
  REQUIRE(!protocol_error_history_consistent(r));
  for (const auto& a : r.attempts()) REQUIRE(a.quality() != daphne::MEASUREMENT_GOOD);
}
void tests() {
  for (auto abi : {0U, kGatewareAbiV2, kGatewareAbiV21, 0x00020003U, 0xffffffffU}) {
    Fixture f; auto r = f.run(abi);
    REQUIRE(r.quality() == daphne::MEASUREMENT_UNAVAILABLE && f.reads == 0 && f.clocks == 0 && r.attempts_size() == 0);
    unavailable(r);
  }
  for (auto values : {std::pair<uint32_t, uint32_t>{0, 0}, {0, 128}, {1, 1}, {1, 31},
                      {42, 27}, {42, 155}, {0xffffffffU, 33}, {0xffffffffU, 127}, {0xffffffffU, 255}}) {
    Fixture f; f.complete(values.first, values.second); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_GOOD && f.reads == 11 && f.reads == f.script.size());
    REQUIRE(r.has_count() && r.count() == values.first && r.has_reasons_seen() && r.reasons_seen() == (values.second & 31));
    REQUIRE(r.has_saturated() && r.saturated() == bool(values.second & 32));
    REQUIRE(r.has_overflowed() && r.overflowed() == bool(values.second & 64));
    REQUIRE(r.has_receiver_reset() && r.receiver_reset() == bool(values.second & 128));
    REQUIRE(!r.identity_bracket_verified() && !r.reset_epoch_known() && protocol_error_history_consistent(r));
  }
  // Defined stopped-clock/busy outcomes require ZERO raw data, no decoded zero.
  for (uint32_t status : {4U, 8U}) {
    Fixture f; f.complete(0, 0, status); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_UNAVAILABLE && r.attempts_size() == 1 && f.reads == 11);
    REQUIRE(r.attempts(0).has_count_raw() && r.attempts(0).count_raw() == 0); unavailable(r);
    for (bool detail : {false, true}) {
      Fixture bad; bad.complete(detail ? 0 : 1, detail ? 128 : 0, status);
      auto failed = bad.run(); REQUIRE(failed.quality() == daphne::MEASUREMENT_ERROR); unavailable(failed);
    }
  }
  // All undefined status combinations, including reserved high bits, fail.
  for (uint32_t status = 0; status < 256; ++status) {
    if (status == 4 || status == 8 || status == 0x11) continue;
    Fixture f; f.complete(0, 0, status); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 9); unavailable(r);
  }
  for (uint32_t status : {0x10011U, 0xffffffffU}) {
    Fixture f; f.complete(0, 0, status); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); unavailable(r);
  }
  for (auto values : {std::pair<uint32_t, uint32_t>{0, 1}, {1, 0}, {1, 33}, {1, 65},
                      {0xffffffffU, 1}, {0xffffffffU, 32}, {1, 0x101}, {0, 0x100}}) {
    Fixture f; f.complete(values.first, values.second); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); unavailable(r);
  }
  for (unsigned conflict : {1, 2, 3}) {
    Fixture f; f.header(); f.attempt(40, 0x11, 9, 1, conflict); f.attempt(43, 0x11, 10, 3); f.header();
    auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_GOOD && r.count() == 10 && r.attempts_size() == 2 && f.reads == 18);
    REQUIRE(r.attempts(0).quality() == daphne::MEASUREMENT_ERROR && r.attempts(1).attempt_index() == 2);
    REQUIRE(protocol_error_history_consistent(r));
  }
  {
    Fixture f; f.header(); for (unsigned i = 0; i < 3; ++i) f.attempt(40 + i, 0x11, 0, 0, 1);
    auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 23 && r.attempts_size() == 3); unavailable(r);
  }
  {
    Fixture f; f.header(); f.attempt(0xffffffffU, 0x11, 1, 1); f.header(); auto r = f.run();
    REQUIRE(r.attempts(0).sequence_first() == 0 && protocol_error_history_consistent(r));
  }
  // Every register failure is fail-closed; no manufactured count or private exception.
  for (unsigned at = 0; at < 11; ++at) {
    Fixture f; f.complete(1, 1); f.script.at(at).fail = true; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == at + 1); unavailable(r);
  }
  for (uint32_t feature : {0U, 0x50450101U, 0xffffffffU}) {
    Fixture f; f.header(feature); auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 1); unavailable(r);
  }
  for (uint32_t timeout : {0U, 7U, (1U << 20) + 1U, 0xffffffffU}) {
    Fixture f; f.header(kProtocolErrorAbi, timeout); auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR && f.reads == 2); unavailable(r);
  }
  for (unsigned at : {9, 10}) {
    Fixture f; f.complete(1, 1); ++f.script.at(at).value; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); unavailable(r);
  }
  for (unsigned at = 0; at < 5; ++at) {
    Fixture f; f.complete(1, 1);
    f.clock_values = {1000000000, 1000001000, 1000002000, 1000003000, 1000004000};
    f.clock_values.at(at) = at == 0 ? 0 : 1;
    auto r = f.run(); REQUIRE(r.quality() == daphne::MEASUREMENT_ERROR); unavailable(r);
  }
  {
    Fixture f; f.complete(); f.step = 100000001; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_STALE && f.reads == 2); unavailable(r);
  }
  {
    Fixture f; f.complete(1, 1); f.clock_values = {1, 2, 3, 4, 100000002}; auto r = f.run();
    REQUIRE(r.quality() == daphne::MEASUREMENT_STALE && f.reads == 11); unavailable(r);
  }
  // Structural consumer must reject corrupted/partial GOOD claims.
  Fixture f; f.complete(0, 0); auto good = f.run();
  for (const auto* field : {"count", "reasons_seen", "saturated", "overflowed", "receiver_reset",
                            "feature_abi", "feature_abi_after", "timeout_cycles", "timeout_cycles_after"}) {
    auto bad = good; bad.GetReflection()->ClearField(&bad, bad.GetDescriptor()->FindFieldByName(field));
    REQUIRE(!protocol_error_history_consistent(bad));
  }
  for (const auto* field : {"sequence_before", "sequence_first", "sequence_after", "request_status_raw",
                            "status_raw", "count_raw", "detail_raw"}) {
    auto bad = good; auto* a = bad.mutable_attempts(0);
    a->GetReflection()->ClearField(a, a->GetDescriptor()->FindFieldByName(field));
    REQUIRE(!protocol_error_history_consistent(bad));
  }
  auto bad = good; bad.set_reset_epoch_known(true); REQUIRE(!protocol_error_history_consistent(bad));
  bad = good; bad.set_counter_width_bits(64); REQUIRE(!protocol_error_history_consistent(bad));
  bad = good; bad.set_count(1); REQUIRE(!protocol_error_history_consistent(bad));
  bad = good; bad.set_receiver_reset(true); REQUIRE(!protocol_error_history_consistent(bad));
  bad = good; bad.set_maximum_attempts(4); REQUIRE(!protocol_error_history_consistent(bad));
  bad = good; bad.set_observed_monotonic_ns(1); REQUIRE(!protocol_error_history_consistent(bad));
  bad = good; bad.add_attempts()->CopyFrom(good.attempts(0)); REQUIRE(!protocol_error_history_consistent(bad));
  invalidate_protocol_error_history(good, daphne::MEASUREMENT_ERROR, "Outer identity bracket failed"); unavailable(good);
}
}
int main() {
  tests();
  std::cout << "PASS protocol history: exact ABI/no old probes, zero/limits/reasons, all status patterns, conflicts, metadata, time, read failures and wire presence\n";
}
