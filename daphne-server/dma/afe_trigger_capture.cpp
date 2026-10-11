#include "afe_capture.hpp"
#include <algorithm>
#include <chrono>
#include <limits>
#include <unistd.h>

namespace daphne_dma {
AfeTriggerLayout afe_trigger_layout(const AfeTriggerRequest& req, uint64_t waveform_limit,
                                    uint64_t ring_limit) {
  if (req.capture.count != 1 || req.pretrigger >= req.capture.length || req.source > 2 ||
      req.period_ticks < 8 || req.period_ticks > 1048576 ||
      (req.period_ticks & (req.period_ticks - 1)))
    throw std::invalid_argument("Invalid triggered L/P/source/period/count");
  AfeTriggerLayout out; out.waveform = afe_layout(req.capture, waveform_limit);
  const uint64_t d = req.period_ticks;
  const uint64_t ring = ((uint64_t(req.capture.length) + 2 * d + d - 1) / d) * d;
  if (ring > UINT32_MAX || ring / d > 512)
    throw std::invalid_argument("Triggered ring exceeds period/controller limits");
  out.ring_ticks = static_cast<uint32_t>(ring);
  const uint64_t page = static_cast<uint64_t>(::sysconf(_SC_PAGESIZE));
  if (!page || (page & (page - 1))) throw std::runtime_error("Invalid host page size");
  for (const auto& channels : out.waveform.channels) {
    if (channels.empty()) continue;
    const uint64_t bytes = 2 * channels.size() * ring;
    if (bytes > (256ULL << 20)) throw std::invalid_argument("Triggered route exceeds 256 MiB");
    out.allocation_bytes += (bytes + 128 + page - 1) & ~(page - 1);
  }
  if (out.allocation_bytes > ring_limit)
    throw std::invalid_argument("Triggered ring exceeds advertised CMA reservation budget");
  return out;
}

void validate_afe_trigger_completion(const AfeTriggerRequest& req, const AfeTriggerLayout& layout,
                                     const daphne_afe_trigger_status& t) {
  const auto& s = t.capture;
  uint32_t routes = 0;
  for (size_t r = 0; r < 3; ++r) if (!layout.waveform.channels[r].empty()) routes |= 1U << r;
  if (t.abi != DAPHNE_AFE_TRIGGER_ABI || s.abi != DAPHNE_AFE_DMA_ABI ||
      s.state != DAPHNE_AFE_COMPLETE || s.error || s.hardware_error || !s.guards_ok ||
      s.build_id != req.capture.build_id || s.format != 1 || s.flags != DAPHNE_AFE_ALIGNED ||
      s.channel_mask != layout.waveform.mask || s.active_routes != routes ||
      t.source != req.source || t.pretrigger != req.pretrigger ||
      t.period_ticks != req.period_ticks || t.ring_ticks != layout.ring_ticks ||
      !(t.trigger_flags & 2) || t.armed || t.trigger_index < req.pretrigger ||
      t.window_first != t.trigger_index - req.pretrigger ||
      t.window_first > UINT64_MAX - req.capture.length ||
      s.allocated_bytes != layout.allocation_bytes)
    throw std::runtime_error("Triggered DMA identity/geometry/trigger/guard mismatch");
  const uint64_t end = t.window_first + req.capture.length;
  if (t.stream_ticks < end || t.stream_ticks - end >= req.period_ticks ||
      t.stream_ticks % req.period_ticks || t.stream_ticks - t.window_first > layout.ring_ticks)
    throw std::runtime_error("Triggered DMA window/drainage mismatch");
  for (size_t r = 0; r < 3; ++r) {
    const uint64_t stride = 2 * layout.waveform.channels[r].size();
    if (t.stream_ticks > UINT64_MAX / std::max<uint64_t>(stride, 1) ||
        s.valid_bytes[r] != layout.waveform.bytes[r] ||
        s.transfer_bytes[r] != stride * layout.ring_ticks ||
        s.received_bytes[r] != stride * t.stream_ticks ||
        s.accepted_beats[r] > UINT64_MAX / 16 || s.accepted_beats[r] * 16 != stride * t.stream_ticks ||
        (stride && ((s.dma_status[r] & 0x770U) || !(s.dma_status[r] & 1U) || (s.dma_control[r] & 5U))))
      throw std::runtime_error("Triggered DMA stream bytes/beats/halt mismatch");
  }
}

namespace {
class TriggeredSession final : public AfeTriggeredSession {
 public:
  TriggeredSession(AfeTriggerRequest req, uint64_t limit, uint64_t ring_limit,
                   std::unique_ptr<AfeTriggerBackend> backend)
      : req_(std::move(req)), layout_(afe_trigger_layout(req_, limit, ring_limit)), backend_(std::move(backend)) {
    static_assert(sizeof(daphne_afe_trigger_config) == 48, "trigger config UAPI");
    static_assert(sizeof(daphne_afe_trigger_status) == 272, "trigger status UAPI");
    if (!backend_) throw std::invalid_argument("Missing trigger backend");
    daphne_afe_trigger_config cfg{};
    cfg.abi = DAPHNE_AFE_TRIGGER_ABI; cfg.flags = DAPHNE_AFE_ALIGNED;
    cfg.length = req_.capture.length; cfg.pretrigger = req_.pretrigger;
    cfg.period_ticks = req_.period_ticks; cfg.ring_ticks = layout_.ring_ticks;
    cfg.source = req_.source; cfg.timeout_ms = req_.capture.timeout_ms;
    cfg.expected_build_id = req_.capture.build_id; cfg.channel_mask = layout_.waveform.mask;
    try { backend_->prepare(cfg); }
    catch (const std::exception& e) { fail(e); }
  }
  ~TriggeredSession() override { try { finish(); } catch (...) {} }
  AfeCapture next(const std::atomic<bool>& cancel, const TriggerProgress& progress) override {
    if (finished_) throw std::runtime_error("Triggered session already released");
    try {
      auto notify = [&](TriggerPhase phase) {
        if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
        if (progress) progress(phase);
      };
      notify(TriggerPhase::history);
      backend_->arm(); // Exactly one ARM per waveform, after the preceding payload was copied.
      const auto deadline = std::chrono::steady_clock::now() +
          std::chrono::milliseconds(uint64_t(req_.capture.timeout_ms) + 10000);
      bool sent = false;
      auto phase = TriggerPhase::history;
      AfeCapture capture; capture.layout = layout_.waveform; capture.triggered = true;
      for (;;) {
        notify(phase);
        auto t = backend_->status();
        if (t.capture.state != DAPHNE_AFE_RUNNING) { capture.trigger = t; break; }
        if (std::chrono::steady_clock::now() >= deadline)
          throw std::runtime_error("Triggered DMA watchdog expired");
        const bool accepted = t.trigger_flags & 2;
        phase = accepted ? TriggerPhase::capturing : t.armed ? TriggerPhase::waiting : TriggerPhase::history;
        notify(phase);
        if (req_.source == DAPHNE_AFE_TRIGGER_SOFTWARE && t.armed && !accepted && !sent)
          sent = backend_->software_trigger(); // EAGAIN alone permits a bounded later attempt.
        backend_->wait();
      }
      notify(TriggerPhase::finalizing);
      validate_afe_trigger_completion(req_, layout_, capture.trigger);
      capture.status = capture.trigger.capture;
      notify(TriggerPhase::reading);
      for (uint32_t r = 0; r < 3; ++r) if (capture.layout.bytes[r]) {
        capture.raw[r] = backend_->read_route(r, capture.layout.bytes[r], cancel);
        if (capture.raw[r].size() != capture.layout.bytes[r]) throw std::runtime_error("Triggered DMA short payload");
      }
      return capture;
    } catch (const std::exception& e) { fail(e); }
  }
  void finish() override {
    if (finished_) return;
    finished_ = true; // Do not retry a mutable operation after an uncertain failure.
    try { backend_->stop(); }
    catch (const std::exception& e) {
      throw std::runtime_error(std::string("DMA_QUARANTINED: cleanup unconfirmed: ") + e.what());
    }
  }
 private:
  [[noreturn]] void fail(const std::exception& e) {
    std::string message = e.what();
    try { finish(); }
    catch (const std::exception& cleanup) { message += "; "; message += cleanup.what(); }
    throw std::runtime_error(message);
  }
  AfeTriggerRequest req_;
  AfeTriggerLayout layout_;
  std::unique_ptr<AfeTriggerBackend> backend_;
  bool finished_ = false;
};
}
std::unique_ptr<AfeTriggeredSession> make_triggered_session(const AfeTriggerRequest& req,
    uint64_t limit, uint64_t ring_limit, std::unique_ptr<AfeTriggerBackend> backend) {
  return std::make_unique<TriggeredSession>(req, limit, ring_limit, std::move(backend));
}
} // namespace daphne_dma
