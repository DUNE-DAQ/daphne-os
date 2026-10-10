#include "capture.hpp"
#include "dma_layout.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <limits>
#include <set>
#include <stdexcept>
#include <thread>

namespace daphne_dma {
Method parse_method(const std::string& value) {
  if (value == "spybuffer") return Method::Spybuffer;
  if (value == "dma-diagnostic") return Method::Diagnostic;
  throw std::invalid_argument("acquisition must be spybuffer or dma-diagnostic");
}
Layout validate(const daphne_dma_config& c) {
  struct daphne_dma_layout layout{};
  if (daphne_dma_layout(&c, 4096, &layout))
    throw std::invalid_argument("invalid DMA configuration, size or block limit");
  const auto total = layout.requested_bytes;
  if (total > uint64_t(480) * 1024 * 1024)
    throw std::invalid_argument("DMA request exceeds maximum diagnostic pool");
  return {layout.packet_bytes, total, layout.blocks};
}
bool active(uint32_t state) {
  return state == DAPHNE_DMA_RUNNING || state == DAPHNE_DMA_STOPPING;
}
const char* state_name(uint32_t state) {
  static const char* names[] = {"idle", "prepared", "running", "stopping",
    "complete", "stopped", "aborted", "error", "quarantined"};
  return state < sizeof(names) / sizeof(*names) ? names[state] : "unknown";
}
PatternChecker::PatternChecker(uint32_t path, uint32_t beats, uint32_t seed)
  : path_(path), beats_(beats), seed_(seed) {
  if (path > 2 || !beats) throw std::invalid_argument("invalid pattern parameters");
}
void PatternChecker::consume(const void* source, size_t count) {
  const auto* bytes = static_cast<const uint8_t*>(source);
  for (size_t i = 0; i < count; ++i) {
    partial_ |= uint32_t(bytes[i]) << (partial_bytes_ * 8);
    ++partial_bytes_;
    ++bytes_;
    if (partial_bytes_ != 4) continue;
    const uint64_t accepted = words_ / 4;
    uint32_t expected = 0;
    switch (words_ % 4) {
      case 0: expected = 0x444d4100U + path_; break;
      case 1: expected = uint32_t(accepted / beats_); break;
      case 2: expected = uint32_t(accepted % beats_); break;
      case 3: expected = seed_ + uint32_t(accepted); break;
    }
    if (partial_ != expected)
      throw std::runtime_error("pattern mismatch at word " + std::to_string(words_) +
        ": expected " + std::to_string(expected) + ", received " + std::to_string(partial_));
    ++words_;
    partial_ = 0;
    partial_bytes_ = 0;
  }
}
void PatternChecker::finish(uint64_t expected) const {
  if (bytes_ != expected || partial_bytes_ || bytes_ % 16)
    throw std::runtime_error("truncated or incorrectly sized DMA pattern");
}

namespace {
struct Session {
  std::unique_ptr<Backend> backend;
  bool prepared = false;
  ~Session() {
    if (prepared) { try { backend->abort(); } catch (...) {} }
  }
};
void validate_status(const Request& r, const daphne_dma_status& s) {
  if (s.abi != DAPHNE_DMA_ABI || s.path != r.path || s.magic != 0x44415048 ||
      s.gateware_abi != 0x00020000 || s.variant != 3 || (s.capabilities & ~0x10U) != 0x520 ||
      s.build_id != r.config.expected_build_id)
    throw std::runtime_error("DMA identity or API mismatch");
}
}
std::vector<Result> run(Method method, const std::vector<Request>& requests,
                        const Factory& factory, const Options& options) {
  if (method == Method::Spybuffer) return {};
  if (requests.empty() || requests.size() > 3 ||
      (options.stop_after_ms && options.abort_after_ms))
    throw std::invalid_argument("invalid route selection or conflicting cancellation modes");
  std::set<uint32_t> paths;
  uint64_t bytes = 0;
  uint32_t max_timeout = 0;
  for (const auto& r : requests) {
    if (r.path > 2 || !paths.insert(r.path).second)
      throw std::invalid_argument("invalid or duplicate DMA route");
    bytes += validate(r.config).total_bytes;
    max_timeout = std::max(max_timeout, r.config.timeout_ms);
  }
  if (bytes > uint64_t(480) * 1024 * 1024)
    throw std::invalid_argument("combined routes exceed maximum diagnostic pool");
  std::vector<std::unique_ptr<Session>> sessions;
  std::vector<Result> results(requests.size());
  for (const auto& r : requests) {
    auto session = std::make_unique<Session>();
    session->backend = factory(r.path);
    session->backend->prepare(r.config);
    session->prepared = true;
    const auto s = session->backend->status();
    validate_status(r, s);
    if (s.state != DAPHNE_DMA_PREPARED)
      throw std::runtime_error("DMA backend did not prepare");
    sessions.push_back(std::move(session));
  }
  bool aborted = options.cancelled();
  if (aborted) {
    for (auto& s : sessions) s->backend->abort();
  } else {
    for (auto& s : sessions) s->backend->start();
  }
  const auto begin = std::chrono::steady_clock::now();
  bool stopped = false;
  for (;;) {
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - begin).count();
    if (!aborted && (options.cancelled() ||
        (options.abort_after_ms && elapsed >= options.abort_after_ms))) {
      for (auto& s : sessions) s->backend->abort();
      aborted = true;
    }
    if (!stopped && options.stop_after_ms && elapsed >= options.stop_after_ms) {
      for (auto& s : sessions) s->backend->stop();
      stopped = true;
    }
    bool pending = false;
    for (size_t i = 0; i < sessions.size(); ++i) {
      auto s = sessions[i]->backend->status();
      if (options.observe_status) options.observe_status(s);
      validate_status(requests[i], s);
      results[i].status = s;
      pending |= active(s.state);
      if (s.state == DAPHNE_DMA_ERROR || s.state == DAPHNE_DMA_QUARANTINED || s.error)
        throw std::runtime_error("DMA route " + std::to_string(s.path) + " " +
          state_name(s.state) + ", kernel error " + std::to_string(s.error));
      if (!active(s.state) && s.state != DAPHNE_DMA_COMPLETE &&
          s.state != DAPHNE_DMA_STOPPED && !(aborted && s.state == DAPHNE_DMA_ABORTED))
        throw std::runtime_error("unexpected DMA state");
    }
    if (!pending) break;
    if (elapsed > int64_t(max_timeout) + 2000)
      throw std::runtime_error("DMA userspace watchdog expired");
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  for (size_t i = 0; i < sessions.size(); ++i) {
    auto& result = results[i];
    auto& backend = *sessions[i]->backend;
    const auto& s = result.status;
    const auto& c = requests[i].config;
    if (s.blocks > DAPHNE_DMA_MAX_BLOCKS)
      throw std::runtime_error("invalid block count");
    uint64_t offset = 0;
    for (uint32_t b = 0; b < s.blocks; ++b) {
      const auto info = backend.block(b);
      if (info.abi != DAPHNE_DMA_ABI || info.index != b || info.reserved ||
          !info.length || info.length > DAPHNE_DMA_CHUNK_BYTES ||
          info.length % 16 || info.logical_offset != offset || info.dma_address % 16 ||
          info.dma_address >= (uint64_t(1) << 40) ||
          info.length > (uint64_t(1) << 40) - info.dma_address)
        throw std::runtime_error("invalid DMA block layout");
      offset += info.length;
      result.blocks.push_back(info);
    }
    if (offset != validate(c).total_bytes)
      throw std::runtime_error("incomplete DMA block layout");
    if (s.state == DAPHNE_DMA_ABORTED) continue;
    if (!s.guards_ok || s.end_ns <= s.start_ns ||
        s.completed_packets > c.packets ||
        (s.state == DAPHNE_DMA_COMPLETE && s.completed_packets != c.packets) ||
        s.received_bytes != uint64_t(s.completed_packets) * c.beats * 16 ||
        s.accepted_beats != uint64_t(s.completed_packets) * c.beats ||
        s.producer_packets != s.completed_packets || (s.producer_status & 7) != 2 ||
        (s.dma_status & 0x770))
      throw std::runtime_error("DMA lengths, counters, status or guards disagree");
    PatternChecker checker(s.path, c.beats, c.seed);
    std::array<uint8_t, 65536> buffer;
    uint64_t received = 0;
    while (received < s.received_bytes) {
      if (options.cancelled())
        throw std::runtime_error("DMA verification cancelled");
      const auto n = backend.read(buffer.data(), size_t(std::min<uint64_t>(
        buffer.size(), s.received_bytes - received)));
      if (!n || n > buffer.size() || n > s.received_bytes - received)
        throw std::runtime_error("short or oversized DMA read");
      checker.consume(buffer.data(), n);
      received += n;
    }
    checker.finish(s.received_bytes);
    if (backend.read(buffer.data(), 1) != 0)
      throw std::runtime_error("extra DMA data past completion");
    result.verified = true;
  }
  return results;
}
}
