#include "capture.hpp"
#include "dma_layout.h"
#include <algorithm>
#include <cstring>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace daphne_dma;
namespace {
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
void fails(const std::function<void()>& action) {
  bool threw = false;
  try { action(); } catch (const std::exception&) { threw = true; }
  require(threw, "expected failure");
}
daphne_dma_config config() { return {DAPHNE_DMA_ABI, 17, 3, 0xfffffff0, 5, 8, 100, 123}; }
std::vector<uint8_t> pattern(uint32_t path, const daphne_dma_config& c, uint32_t packets) {
  std::vector<uint8_t> result;
  for (uint32_t p = 0; p < packets; ++p)
    for (uint32_t b = 0; b < c.beats; ++b) {
      uint32_t words[] = {0x444d4100U + path, p, b, c.seed + p * c.beats + b};
      for (auto word : words)
        for (unsigned shift = 0; shift < 32; shift += 8)
          result.push_back(uint8_t(word >> shift));
    }
  return result;
}
struct Trace {
  std::vector<std::string> events;
  int fail_prepare = -1, fail_start = -1, fail_status = -1;
  bool corrupt = false, short_read = false, bad_guard = false, hang = false;
};
class Fake final : public Backend {
 public:
  Fake(uint32_t path, Trace& t) : path_(path), trace_(t) {}
  void prepare(const daphne_dma_config& c) override {
    trace_.events.push_back("prepare" + std::to_string(path_));
    if (int(path_) == trace_.fail_prepare) throw std::runtime_error("allocation failed");
    c_ = c;
    s_ = {};
    s_.abi = DAPHNE_DMA_ABI; s_.path = path_; s_.state = DAPHNE_DMA_PREPARED;
    s_.magic = 0x44415048; s_.gateware_abi = 0x20000; s_.variant = 3;
    s_.build_id = c.expected_build_id; s_.capabilities = 0x520;
    s_.blocks = c.packets;
    s_.requested_bytes = uint64_t(c.beats) * 16 * c.packets;
    s_.allocated_bytes = s_.requested_bytes + 128 * c.packets;
  }
  void start() override {
    trace_.events.push_back("start" + std::to_string(path_));
    if (int(path_) == trace_.fail_start) throw std::runtime_error("start failed");
    s_.state = DAPHNE_DMA_RUNNING;
    s_.start_ns = 1000; s_.end_ns = 2000;
  }
  void stop() override { finish(DAPHNE_DMA_STOPPED, 1); }
  void abort() override {
    trace_.events.push_back("abort" + std::to_string(path_));
    s_.state = DAPHNE_DMA_ABORTED;
  }
  daphne_dma_status status() override {
    if (s_.state == DAPHNE_DMA_RUNNING && !trace_.hang)
      finish(DAPHNE_DMA_COMPLETE, c_.packets);
    if (s_.state == DAPHNE_DMA_RUNNING && int(path_) == trace_.fail_status) {
      s_.state = DAPHNE_DMA_ERROR; s_.error = -110;
    }
    return s_;
  }
  daphne_dma_block_info block(uint32_t index) override {
    // Deliberately exercise addresses above 4 GiB without hardware claims.
    return {DAPHNE_DMA_ABI, index, c_.beats * 16, 0,
      uint64_t(0x800000000ULL) + uint64_t(index) * 4096, uint64_t(index) * c_.beats * 16};
  }
  size_t read(void* target, size_t size) override {
    if (trace_.short_read) return 0;
    size_t n = std::min({size, data_.size() - read_, size_t(7)});
    std::memcpy(target, data_.data() + read_, n);
    read_ += n;
    return n;
  }
 private:
  uint32_t path_;
  Trace& trace_;
  daphne_dma_config c_{};
  daphne_dma_status s_{};
  std::vector<uint8_t> data_;
  size_t read_ = 0;
  void finish(uint32_t state, uint32_t packets) {
    s_.state = state; s_.completed_packets = s_.producer_packets = packets;
    s_.accepted_beats = uint64_t(packets) * c_.beats;
    s_.received_bytes = s_.accepted_beats * 16;
    s_.producer_status = 10; s_.dma_status = 8;
    s_.guards_ok = !trace_.bad_guard;
    data_ = pattern(path_, c_, packets);
    if (trace_.corrupt) data_[data_.size() - 1] ^= 1;
  }
};
Factory factory(Trace& t) { return [&t](uint32_t p) { return std::make_unique<Fake>(p, t); }; }
}
int main() {
  try {
    Trace trace;
    auto requests = std::vector<Request>{{0, config()}, {1, config()}, {2, config()}};
    require(run(Method::Spybuffer, requests, factory(trace)).empty(), "default selects spybuffer");
    require(trace.events.empty(), "default must not open, reserve or start DMA");
    require(parse_method("spybuffer") == Method::Spybuffer, "selection parse");
    fails([] { parse_method("full-stream"); });
    for (unsigned bad = 0; bad < 8; ++bad) {
      auto c = config();
      switch (bad) {
        case 0: c.beats = 0; break;
        case 1: c.packets = 0; break;
        case 2: c.rate_num = 9; break;
        case 3: c.rate_den = 0; break;
        case 4: c.timeout_ms = 0; break;
        case 5: c.beats = std::numeric_limits<uint32_t>::max(); break;
        case 6: c.packets = std::numeric_limits<uint32_t>::max(); break;
        case 7: c.expected_build_id = 0xf0000000; break;
      }
      fails([&] { validate(c); });
    }
    auto big = config(); big.beats = DAPHNE_DMA_MAX_PACKET_BYTES / 16;
    big.packets = 1;
    require(validate(big).blocks == 64, "packet spans multiple SG descriptors");
    struct daphne_dma_layout geometry{};
    auto small = config();
    require(!daphne_dma_layout(&small, 4096, &geometry) &&
      geometry.allocated_bytes == 3 * 4096, "kernel guard/page allocation accounting");
    require(!daphne_dma_layout(&small, 65536, &geometry) &&
      geometry.allocated_bytes == 3 * 65536, "64-KiB target page accounting");
    require(daphne_dma_layout(&small, 6000, &geometry) == -EINVAL, "invalid page geometry");
    auto duplicate = requests; duplicate[1].path = 0;
    fails([&] { run(Method::Diagnostic, duplicate, factory(trace)); });
    require(trace.events.empty(), "validate before any backend access");
    const auto results = run(Method::Diagnostic, requests, factory(trace));
    require(results.size() == 3 && results[2].verified, "all three routes verified");
    require(trace.events[2] == "prepare2" && trace.events[3] == "start0",
      "all allocations precede every producer start");
    for (uint32_t p = 0; p < 3; ++p) {
      auto data = pattern(p, config(), 3);
      PatternChecker checker(p, config().beats, config().seed);
      for (auto byte : data) checker.consume(&byte, 1);
      checker.finish(data.size());
      for (unsigned word = 0; word < 4; ++word) {
        auto corrupt = data; corrupt[word * 4] ^= 1;
        fails([&] { PatternChecker c(p, config().beats, config().seed);
          c.consume(corrupt.data(), corrupt.size()); });
      }
      fails([&] { PatternChecker c(p, config().beats, config().seed);
        c.consume(data.data(), data.size() - 1); c.finish(data.size()); });
    }
    for (int failure = 0; failure < 5; ++failure) {
      Trace t;
      if (failure == 0) t.fail_prepare = 1;
      if (failure == 1) t.fail_start = 1;
      if (failure == 2) t.corrupt = true;
      if (failure == 3) t.short_read = true;
      if (failure == 4) t.bad_guard = true;
      fails([&] { run(Method::Diagnostic, requests, factory(t)); });
      require(std::find(t.events.begin(), t.events.end(), "abort0") != t.events.end(),
        "prepared routes cleaned up after failure");
    }
    Trace stop; stop.hang = true;
    Options opts; opts.stop_after_ms = 1;
    auto stopped = run(Method::Diagnostic, requests, factory(stop), opts);
    require(stopped[0].verified && stopped[0].status.completed_packets == 1,
      "STOP verifies only drained packets");
    Trace abort; abort.hang = true;
    opts.stop_after_ms = 0; opts.abort_after_ms = 1;
    auto aborted = run(Method::Diagnostic, requests, factory(abort), opts);
    require(!aborted[0].verified && aborted[0].status.state == DAPHNE_DMA_ABORTED,
      "aborted data must not be reported verified");
    Trace cancel; cancel.hang = true;
    opts.abort_after_ms = 0; opts.cancelled = [] { return true; };
    auto cancelled = run(Method::Diagnostic, requests, factory(cancel), opts);
    require(cancelled[0].status.state == DAPHNE_DMA_ABORTED, "signal cancellation cleanup");
    require(std::none_of(cancel.events.begin(), cancel.events.end(),
      [](const std::string& event) { return event.find("start") == 0; }),
      "cancellation during preparation must not start a producer");
    Trace timeout; timeout.hang = true; timeout.fail_status = 0;
    fails([&] { run(Method::Diagnostic, requests, factory(timeout)); });
    std::cout << "DMA unit tests passed (no hardware)\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n'; return 1;
  }
}
