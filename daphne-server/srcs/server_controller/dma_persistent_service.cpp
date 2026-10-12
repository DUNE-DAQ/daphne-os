#include "server_controller/dma_service.hpp"
#include <algorithm>
#include <limits>

namespace daphne_sc {
namespace {
bool same_id(const daphne::DmaEventId& a, const daphne_afe_event_id& b) {
  return a.session() == b.session && a.sequence() == b.sequence && a.generation() == b.generation && a.slot() == b.slot;
}
void wire_id(daphne::DmaEventId* a, const daphne_afe_event_id& b) {
  a->set_session(b.session); a->set_sequence(b.sequence); a->set_generation(b.generation); a->set_slot(b.slot);
}
}
void DmaService::start_persistent(const daphne::DmaAcquireRequest& req, const std::string& owner,
                                  daphne::DmaJobResponse& out) {
  if (req.protocol_revision() != 3 || session_caps_.abi != 1 || (session_caps_.features & 31) != 31)
    throw std::invalid_argument("PERSISTENT_UNAVAILABLE: revision 3 and session ABI 1/features 31 required");
  if (req.waveforms() || !req.target_waveforms() || req.target_waveforms() > session_caps_.target_max)
    throw std::invalid_argument("Persistent N requires positive target_waveforms, legacy waveforms must be zero");
  uint32_t source;
  switch (req.trigger_source()) {
    case daphne::DMA_TRIGGER_SOFTWARE: source = 0; break;
    case daphne::DMA_TRIGGER_EXTERNAL: source = 1; break;
    case daphne::DMA_TRIGGER_TIMING: source = 2; break;
    default: throw std::invalid_argument("Persistent trigger source unsupported");
  }
  if (req.pressure_timeout_ms() && (req.pressure_timeout_ms() < 10 || req.pressure_timeout_ms() > 600000))
    throw std::invalid_argument("Pressure timeout must be zero or 10..600000 ms");
  // Explicit total deadline bounds wall clock independently of N, lease and pressure.
  const auto timeout = req.job_timeout_ms();
  if (timeout && (timeout < 10 || timeout > 7ULL * 24 * 3600 * 1000))
    throw std::invalid_argument("Persistent total deadline must be zero or 10 ms..7 days");
  daphne_dma::AfeRequest capture;
  capture.channels.assign(req.channels().begin(), req.channels().end()); capture.length = req.samples();
  capture.timeout_ms = req.timeout_ms() ? req.timeout_ms() : 30000; capture.build_id = identity_.build_id;
  auto layout = daphne_dma::afe_layout(capture, options_.maximum_job_bytes);
  if (req.pretrigger_samples() >= capture.length) throw std::invalid_argument("Require 0 <= P < L");
  // Validate the driver's default geometry (at least 8 periods) without allocating.
  const uint64_t ring = std::max<uint64_t>(8ULL * options_.period_ticks,
      ((uint64_t(capture.length) + 3ULL * options_.period_ticks - 1) / options_.period_ticks) * options_.period_ticks);
  uint64_t allocation = 0;
  for (const auto& route : layout.channels) if (!route.empty()) {
    const auto bytes = ring * route.size() * 2;
    if (bytes > session_caps_.route_max) throw std::invalid_argument("Persistent route ring exceeds budget");
    allocation += (bytes + 128 + 4095) & ~uint64_t(4095);
  }
  if (ring / options_.period_ticks > 512 || allocation > std::min<uint64_t>(options_.maximum_ring_bytes, session_caps_.pool_max))
    throw std::invalid_argument("Persistent ring exceeds pool budget");
  if (busy()) throw std::runtime_error("BUSY");
  check_frontend(capture.channels, false, req.force_acquisition()); new_job(owner);
  daphne_dma::AfePersistentRequest request{{capture, req.pretrigger_samples(), source, options_.period_ticks},
      req.target_waveforms(), std::min<uint64_t>(options_.maximum_ring_bytes, session_caps_.pool_max),
      req.pressure_timeout_ms(), options_.cleanup_timeout_ms};
  {
    std::lock_guard<std::mutex> lock(mutex_);
    samples_ = capture.length; target_ = request.target; capture_mode_ = daphne::DMA_CAPTURE_PERSISTENT;
    pretrigger_ = req.pretrigger_samples(); trigger_source_ = req.trigger_source();
    job_timeout_ms_ = timeout; phase_ = daphne::DMA_PHASE_PREPARING;
    force_acquisition_ = req.force_acquisition();
  }
  worker_ = std::thread([this, request, layout, timeout] {
    std::unique_ptr<daphne_dma::AfePersistentSession> session;
    const auto begin = std::chrono::steady_clock::now();
    try {
      session = engine_->open_persistent(request);
      for (;;) {
        if (cancel_.load()) throw std::runtime_error("DMA_CANCELLED");
        if (timeout && std::chrono::steady_clock::now() - begin >= std::chrono::milliseconds(timeout))
          throw std::runtime_error("Persistent total acquisition/delivery deadline expired");
        const auto s = session->status();
        if (s.abi != 1 || s.error || s.hardware_error || s.state == DAPHNE_SESSION_ERROR ||
            s.state == DAPHNE_SESSION_QUARANTINED || s.state == DAPHNE_SESSION_ABORTED)
          throw std::runtime_error(s.state == DAPHNE_SESSION_QUARANTINED ? "DMA_QUARANTINED" : "Persistent driver failed");
        bool room, all_staged;
        {
          std::lock_guard<std::mutex> lock(mutex_); session_status_ = s;
          phase_ = s.state == DAPHNE_SESSION_DRAINING ? daphne::DMA_PHASE_FINALIZING : daphne::DMA_PHASE_CAPTURING;
          room = staged_.size() < staging_event_limit_ && staged_bytes_ <= options_.maximum_job_bytes - layout.total_bytes;
          all_staged = staged_total_ == target_;
        }
        if (all_staged && s.state == DAPHNE_SESSION_COMPLETE && s.released == request.target) {
          if (!s.guards_ok || s.accepted != request.target || s.completed != request.target ||
              s.delivered != request.target || s.starts != 1 || s.stops != 1)
            throw std::runtime_error("Persistent final counters/guards mismatch");
          session->finish(false);
          std::lock_guard<std::mutex> lock(mutex_);
          producer_closed_ = true; state_ = daphne::DMA_JOB_READY; phase_ = daphne::DMA_PHASE_IDLE;
          break;
        }
        if (!all_staged && room) {
          daphne_dma::AfeCapture event;
          if (session->next(event, cancel_)) {
            std::lock_guard<std::mutex> lock(mutex_);
            staging_copy_ns_ += event.copy_ns;
            staged_bytes_ += event.layout.total_bytes; staged_.push_back({std::move(event), {}}); ++staged_total_;
            continue;
          }
        }
        std::unique_lock<std::mutex> lock(mutex_);
        credit_.wait_for(lock, std::chrono::milliseconds(2));
      }
    } catch (const std::exception& e) {
      std::string message = e.what();
      if (session) try { session->finish(true); } catch (const std::exception& cleanup) {
        message += "; DMA_QUARANTINED: "; message += cleanup.what();
      }
      std::lock_guard<std::mutex> lock(mutex_);
      message_ = message; quarantine_ = message.find("QUARANTINED") != std::string::npos;
      staged_.clear(); staged_bytes_ = 0;
      state_ = cancel_.load() ? daphne::DMA_JOB_CANCELLED : daphne::DMA_JOB_FAILED;
      phase_ = daphne::DMA_PHASE_IDLE;
    }
  });
  std::lock_guard<std::mutex> lock(mutex_); fill_status(out);
}
void DmaService::read_persistent(const daphne::DmaReadRequest& req, daphne::DmaReadResponse& out) {
  if ((state_ != daphne::DMA_JOB_RUNNING && state_ != daphne::DMA_JOB_READY) || !req.has_event_id() || req.route() >= 3 || req.waveform())
    throw std::invalid_argument("Persistent READ requires a complete event ID and live staged data");
  auto found = std::find_if(staged_.begin(), staged_.end(), [&](const StagedEvent& e) { return same_id(req.event_id(), e.capture.event.id); });
  if (found == staged_.end()) throw std::invalid_argument("STALE_EVENT: ID unavailable or already ACKed");
  auto& staged = *found; const auto& c = staged.capture; const auto& e = c.event; const auto r = req.route();
  if (req.tick_offset() != staged.read_ticks[r]) throw std::invalid_argument("Fragments require sequential ticks");
  const auto width = c.layout.channels[r].size() * 2;
  const auto maximum = req.maximum_bytes() ? std::min(req.maximum_bytes(), options_.maximum_fragment_bytes) : options_.maximum_fragment_bytes;
  if (!width || req.tick_offset() >= samples_ || maximum < width) throw std::invalid_argument("Invalid fragment geometry");
  const uint32_t count = std::min<uint32_t>(samples_ - req.tick_offset(), maximum / width);
  out.set_success(true); out.set_backend(daphne::ACQUISITION_DMA); out.set_job_id(job_id_);
  out.set_route(r); out.set_fragment_sequence(fragment_sequence_++); out.set_target_waveforms(target_);
  for (auto ch : c.layout.channels[r]) out.add_channels(ch);
  out.set_samples(samples_); out.set_tick_offset(req.tick_offset()); out.set_tick_count(count);
  out.set_raw16_le(c.raw[r].data() + size_t(req.tick_offset()) * width, count * width);
  out.set_final_route(req.tick_offset() + count == samples_);
  uint32_t last = 2; while (c.layout.channels[last].empty()) --last;
  out.set_final_waveform(out.final_route() && r == last); out.set_final_job(out.final_waveform() && e.id.sequence == target_);
  out.set_gateware_build_id(identity_.build_id); out.set_sample_format(1);
  out.set_timestamp(e.timestamp); out.set_timestamp_valid(e.timestamp_valid);
  out.set_independently_software_triggered(false);
  auto* m = out.mutable_waveform_metadata(); m->set_contract_version(3); m->set_capture_mode(daphne::DMA_CAPTURE_PERSISTENT);
  m->set_trigger_source(trigger_source_); m->set_samples(samples_); m->set_pretrigger_samples(pretrigger_);
  m->set_trigger_index(e.trigger_index); m->set_window_first(e.trigger_index - pretrigger_);
  m->set_period_ticks(options_.period_ticks); m->set_trigger_timestamp(e.timestamp); m->set_trigger_timestamp_valid(e.timestamp_valid);
  wire_id(m->mutable_event_id(), e.id); m->set_channel_mask(e.channel_mask); m->set_first_cursor(e.first_cursor);
  m->set_fence_end(e.fence_end); m->set_segment(e.segment);
  for (auto bytes : e.valid_bytes) m->add_valid_bytes(bytes);
  for (auto ignored : e.ignored) m->add_ignored(ignored);
  staged.read_ticks[r] += count;
  bool done = true;
  for (uint32_t route = 0; route < 3; ++route) if (c.layout.bytes[route] && staged.read_ticks[route] != samples_) done = false;
  if (done) ++delivered_;
}
void DmaService::ack_persistent(const daphne::DmaControlRequest& req) {
  if (state_ != daphne::DMA_JOB_RUNNING && state_ != daphne::DMA_JOB_READY) throw std::invalid_argument("Session ACK unavailable");
  if (!req.event_ids_size()) {
    if (!producer_closed_ || !staged_.empty() || acknowledged_ != target_)
      throw std::invalid_argument("Final ACK requires closed producer and all event ACKs");
    state_ = daphne::DMA_JOB_IDLE; owner_.clear(); return;
  }
  if (req.event_ids_size() > int(staging_event_limit_) || size_t(req.event_ids_size()) > staged_.size())
    throw std::invalid_argument("Invalid ACK batch size");
  // Entire ordered batch is validated before changing any credit.
  for (int i = 0; i < req.event_ids_size(); ++i) {
    const auto& e = staged_[i];
    if (!same_id(req.event_ids(i), e.capture.event.id) || e.capture.event.id.sequence != acknowledged_ + i + 1)
      throw std::invalid_argument("STALE_EVENT: out-of-order, repeated or stale ACK");
    for (uint32_t r = 0; r < 3; ++r)
      if (e.capture.layout.bytes[r] && e.read_ticks[r] != samples_) throw std::invalid_argument("ACK requires all route payloads read");
  }
  for (int i = 0; i < req.event_ids_size(); ++i) {
    staged_bytes_ -= staged_.front().capture.layout.total_bytes; staged_.pop_front(); ++acknowledged_;
  }
  credit_.notify_all();
}
} // namespace daphne_sc
