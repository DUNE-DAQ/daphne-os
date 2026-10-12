#include "server_controller/dma_service.hpp"
#include <algorithm>
#include <filesystem>
#include <limits>
#include <stdexcept>

namespace daphne_sc {
DmaService::DmaService(GatewareIdentity id, DmaServiceOptions opts,
    std::unique_ptr<daphne_dma::AfeCaptureEngine> engine, Guard guard, Scanner scanner,
    std::function<void()> live_guard, std::function<bool()> device_available)
    : guard_(std::move(guard)), scanner_(std::move(scanner)), live_guard_(std::move(live_guard)),
      device_available_(std::move(device_available)), identity_(id), options_(opts), engine_(std::move(engine)) {
  if (!opts.maximum_job_bytes || opts.maximum_job_bytes > (256ULL << 20) ||
      !opts.maximum_waveforms || !opts.maximum_fragment_bytes ||
      opts.maximum_fragment_bytes > (1U << 20) || opts.lease_ms < 1000 ||
      !opts.maximum_ring_bytes || opts.maximum_ring_bytes > (448ULL << 20) ||
      opts.period_ticks != 8192 || opts.cleanup_timeout_ms < 10000 || opts.cleanup_timeout_ms > 60000 ||
      !engine_ || !guard_ || !live_guard_ || !device_available_)
    throw std::invalid_argument("Invalid DMA service budgets/dependencies");
  triggered_available_ = (identity_.capabilities & 64U) && engine_->supports_triggered();
  if (identity_.capabilities & 128U) session_caps_ = engine_->persistent_caps();
}
DmaService::~DmaService() { shutdown(); }
void DmaService::verify_live() const { live_guard_(); }
void DmaService::shutdown() { cancel_.store(true); credit_.notify_all(); if (worker_.joinable()) worker_.join(); }
bool DmaService::busy() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return state_ == daphne::DMA_JOB_RUNNING || quarantine_ ||
      (capture_mode_ == daphne::DMA_CAPTURE_PERSISTENT && state_ != daphne::DMA_JOB_IDLE);
}
void DmaService::invalidate(bool unconfigured, uint32_t afe_mask) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (uint32_t a = 0; a < 5; ++a) if (afe_mask & (1U << a)) {
    ++generations_[a]; approved_[a] = 0;
    auto& state = states_[a];
    state = unconfigured ? daphne::FRONTEND_UNCONFIGURED :
        (state == daphne::FRONTEND_UNCONFIGURED ? state : daphne::FRONTEND_CONFIGURED_UNALIGNED);
  }
}
void DmaService::configured(const daphne::ConfigureRequest& req) {
  std::lock_guard<std::mutex> lock(mutex_);
  for (auto& generation : generations_) ++generation;
  approved_.fill(0); states_.fill(daphne::FRONTEND_UNCONFIGURED);
  for (const auto& afe : req.afes()) states_.at(afe.id()) = daphne::FRONTEND_CONFIGURED_UNALIGNED;
}
daphne::AcquisitionCapabilitiesResponse DmaService::capabilities(uint32_t maximum_revision) const {
  std::lock_guard<std::mutex> lock(mutex_);
  daphne::AcquisitionCapabilitiesResponse r;
  const bool extended = maximum_revision >= 2;
  r.set_success(true); r.set_protocol_revision(extended ? 2 : 1); r.set_backend(daphne::ACQUISITION_DMA);
  r.set_force_acquisition_supported(true); r.set_skip_ramp_verification_supported(true);
  if (maximum_revision >= 3) r.set_protocol_revision(3);
  r.add_available_backends(daphne::ACQUISITION_DMA);
  r.add_dma_trigger_sources(daphne::DMA_TRIGGER_SOFTWARE);
  r.set_gateware_build_id(identity_.build_id); r.set_gateware_abi(identity_.abi);
  r.set_gateware_capabilities(identity_.capabilities); r.set_sample_format(1);
  r.set_maximum_job_bytes(options_.maximum_job_bytes);
  r.set_maximum_samples(static_cast<uint32_t>(options_.maximum_job_bytes / 2));
  r.set_maximum_waveforms(options_.maximum_waveforms);
  r.set_maximum_fragment_bytes(options_.maximum_fragment_bytes);
  r.set_maximum_scan_ticks(options_.maximum_scan_ticks);
  r.set_dma_available(!quarantine_ && device_available_());
  r.set_timestamp_available(false);
  r.set_message("Software trigger = one START per waveform; external/timing/self/all require future trigger firmware. No pretrigger.");
  if (extended) {
    auto* finite = r.add_capture_modes(); finite->set_mode(daphne::DMA_CAPTURE_FINITE);
    finite->add_trigger_sources(daphne::DMA_TRIGGER_SOFTWARE); finite->set_available(r.dma_available());
    auto* triggered = r.add_capture_modes(); triggered->set_mode(daphne::DMA_CAPTURE_TRIGGERED);
    triggered->set_available(triggered_available_ && r.dma_available());
    triggered->set_pretrigger_available(true); triggered->set_timing_requires_endpoint(true);
    for (auto source : {daphne::DMA_TRIGGER_SOFTWARE, daphne::DMA_TRIGGER_EXTERNAL, daphne::DMA_TRIGGER_TIMING})
      triggered->add_trigger_sources(source);
    triggered->add_experimental_sources(daphne::DMA_TRIGGER_EXTERNAL);
    triggered->add_experimental_sources(daphne::DMA_TRIGGER_TIMING);
    r.set_maximum_ring_bytes(options_.maximum_ring_bytes); r.set_period_ticks(options_.period_ticks);
    r.set_lease_ms(options_.lease_ms); r.set_cleanup_timeout_ms(options_.cleanup_timeout_ms);
    r.set_message("Finite software START remains compatible. Triggered PREPARE verifies AFEC/provider API before ARM; external/timing are experimental, timing requires a valid endpoint. No continuous acquisition.");
  }
  if (maximum_revision >= 3) {
    auto* mode = r.add_capture_modes(); mode->set_mode(daphne::DMA_CAPTURE_PERSISTENT);
    mode->set_available(session_caps_.abi == 1 && (session_caps_.features & 31) == 31 && r.dma_available());
    mode->set_pretrigger_available(true); mode->set_timing_requires_endpoint(true);
    for (auto source : {daphne::DMA_TRIGGER_SOFTWARE, daphne::DMA_TRIGGER_EXTERNAL, daphne::DMA_TRIGGER_TIMING})
      mode->add_trigger_sources(source);
    mode->add_experimental_sources(daphne::DMA_TRIGGER_EXTERNAL); mode->add_experimental_sources(daphne::DMA_TRIGGER_TIMING);
    r.set_session_abi(session_caps_.abi); r.set_session_features(session_caps_.features);
    r.set_session_slots(session_caps_.slots); r.set_maximum_target_waveforms(session_caps_.target_max);
    r.set_maximum_staged_events(staging_event_limit_);
    r.set_session_pool_bytes(std::min<uint64_t>(session_caps_.pool_max, options_.maximum_ring_bytes));
    r.set_session_route_bytes(session_caps_.route_max);
    r.set_message("Persistent: one START for positive N, bounded staging retained until ordered event ACK; external/timing experimental. Software AUTO; polling driver, final stop cost remains.");
  }
  for (uint32_t a = 0; a < 5; ++a) {
    auto* s = r.add_afes(); s->set_afe(a); s->set_state(states_[a]);
    s->set_approved_lane_mask(approved_[a]); s->set_configuration_generation(generations_[a]);
  }
  return r;
}
void DmaService::check_frontend(const std::vector<uint32_t>& channels, bool calibration, bool force_acquisition) {
  live_guard_();
  guard_(channels, calibration);
  for (auto ch : channels) {
    const uint32_t a = ch / 8;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (!force_acquisition && (states_[a] == daphne::FRONTEND_UNCONFIGURED || (!calibration && states_[a] == daphne::FRONTEND_FAILED) ||
          (!calibration && !(approved_[a] & (1U << (ch % 8))))))
        throw std::runtime_error("ALIGNMENT_REQUIRED: configure and run scan_afe_delay_eye.py --dma --apply_best");
    }

  }
}
void DmaService::new_job(const std::string& owner) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (quarantine_) throw std::runtime_error("DMA_QUARANTINED: recovery requires operator intervention");
    if (state_ != daphne::DMA_JOB_IDLE) throw std::runtime_error("BUSY: ACK or cancel the previous DMA job");
  }
  if (worker_.joinable()) worker_.join();
  std::lock_guard<std::mutex> lock(mutex_);
  ++job_id_; owner_ = owner; state_ = daphne::DMA_JOB_RUNNING;
  completed_ = expected_ = samples_ = read_sequence_ = 0;
  message_.clear(); captures_.clear(); read_ticks_.clear(); scan_result_.Clear(); cancel_.store(false);
  force_acquisition_ = false;
  capture_mode_ = daphne::DMA_CAPTURE_FINITE; trigger_source_ = daphne::DMA_TRIGGER_SOFTWARE;
  pretrigger_ = 0; job_timeout_ms_ = 0; phase_ = daphne::DMA_PHASE_IDLE;
  staged_.clear(); session_status_ = {}; target_ = staged_total_ = acknowledged_ = delivered_ = 0;
  staged_bytes_ = fragment_sequence_ = staging_copy_ns_ = 0; producer_closed_ = false;
  lease_ = std::chrono::steady_clock::now() + std::chrono::milliseconds(options_.lease_ms);
}
void DmaService::start(const daphne::DmaAcquireRequest& req, const std::string& owner,
                       daphne::DmaJobResponse& out) {
  if (req.backend() != daphne::ACQUISITION_DMA)
    throw std::invalid_argument("BACKEND_MISMATCH: DMA must be selected explicitly");
  if (req.capture_mode() == daphne::DMA_CAPTURE_PERSISTENT) { start_persistent(req, owner, out); return; }
  if (req.target_waveforms() || req.pressure_timeout_ms()) throw std::invalid_argument("Persistent fields require persistent mode");
  if (req.capture_mode() != daphne::DMA_CAPTURE_FINITE && req.capture_mode() != daphne::DMA_CAPTURE_TRIGGERED)
    throw std::invalid_argument("CAPTURE_MODE_UNSUPPORTED");
  const bool triggered = req.capture_mode() == daphne::DMA_CAPTURE_TRIGGERED;
  if (!triggered && (req.trigger_source() != daphne::DMA_TRIGGER_SOFTWARE || req.pretrigger_samples()))
    throw std::invalid_argument("FINITE requires software trigger and P=0");
  if (triggered && !triggered_available_)
    throw std::invalid_argument("TRIGGERED_UNAVAILABLE: firmware/driver/provider support missing");
  uint32_t source = 0;
  switch (req.trigger_source()) {
    case daphne::DMA_TRIGGER_SOFTWARE: source = DAPHNE_AFE_TRIGGER_SOFTWARE; break;
    case daphne::DMA_TRIGGER_EXTERNAL: source = DAPHNE_AFE_TRIGGER_EXTERNAL; break;
    case daphne::DMA_TRIGGER_TIMING: source = DAPHNE_AFE_TRIGGER_TIMING; break;
    default: throw std::invalid_argument("TRIGGER_UNSUPPORTED: triggered supports software/external/timing");
  }
  daphne_dma::AfeRequest request;
  request.channels.assign(req.channels().begin(), req.channels().end());
  request.length = req.samples(); request.build_id = identity_.build_id;
  request.timeout_ms = req.timeout_ms() ? req.timeout_ms() : 10000;
  const auto layout = daphne_dma::afe_layout(request, options_.maximum_job_bytes);
  const daphne_dma::AfeTriggerRequest trigger_request{request, req.pretrigger_samples(), source, options_.period_ticks};
  if (triggered) daphne_dma::afe_trigger_layout(trigger_request, options_.maximum_job_bytes, options_.maximum_ring_bytes);
  if (!req.waveforms() || req.waveforms() > options_.maximum_waveforms ||
      layout.total_bytes > options_.maximum_job_bytes / req.waveforms())
    throw std::invalid_argument("DMA job exceeds waveform/byte budget; reduce the client batch");
  if (busy()) throw std::runtime_error("BUSY");
  check_frontend(request.channels, false, req.force_acquisition());
  const uint64_t maximum_job_timeout = uint64_t(req.waveforms()) * (request.timeout_ms + uint64_t(options_.cleanup_timeout_ms)) + 5000;
  const uint64_t job_timeout = req.job_timeout_ms() ? req.job_timeout_ms() : maximum_job_timeout;
  if (job_timeout < 10 || job_timeout > maximum_job_timeout)
    throw std::invalid_argument("DMA total job deadline exceeds the bounded waveform budget");
  new_job(owner);
  { std::lock_guard<std::mutex> lock(mutex_); samples_ = request.length; expected_ = req.waveforms();
    capture_mode_ = req.capture_mode(); trigger_source_ = req.trigger_source(); pretrigger_ = req.pretrigger_samples();
    job_timeout_ms_ = job_timeout; phase_ = daphne::DMA_PHASE_PREPARING;
    force_acquisition_ = req.force_acquisition();
  }
  worker_ = std::thread([this, request, trigger_request, triggered, job_timeout, force = req.force_acquisition(), n = req.waveforms()] {
    std::unique_ptr<daphne_dma::AfeTriggeredSession> session;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(job_timeout);
    try {
      const auto progress = [this, deadline](daphne_dma::TriggerPhase phase) {
        if (cancel_.load()) throw std::runtime_error("DMA_CANCELLED");
        if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("DMA total job deadline expired");
        live_guard_();
        daphne::DmaCapturePhase value = daphne::DMA_PHASE_PREPARING;
        switch (phase) {
          case daphne_dma::TriggerPhase::preparing: break;
          case daphne_dma::TriggerPhase::history: value = daphne::DMA_PHASE_HISTORY; break;
          case daphne_dma::TriggerPhase::waiting: value = daphne::DMA_PHASE_WAITING_TRIGGER; break;
          case daphne_dma::TriggerPhase::capturing: value = daphne::DMA_PHASE_CAPTURING; break;
          case daphne_dma::TriggerPhase::finalizing: value = daphne::DMA_PHASE_FINALIZING; break;
          case daphne_dma::TriggerPhase::reading: value = daphne::DMA_PHASE_READING; break;
        }
        std::lock_guard<std::mutex> lock(mutex_); phase_ = value;
      };
      if (triggered) session = engine_->open_triggered(trigger_request, options_.maximum_ring_bytes);
      for (uint32_t wave = 0; wave < n; ++wave) {
        check_frontend(request.channels, false, force);
        progress(daphne_dma::TriggerPhase::history);
        auto capture = triggered ? session->next(cancel_, progress) : engine_->capture(request, cancel_);
        // Copy is retained before the next ARM invalidates the driver's waveform.
        std::lock_guard<std::mutex> lock(mutex_);
        captures_.push_back(std::move(capture)); read_ticks_.push_back({}); ++completed_;
      }
      if (session) { progress(daphne_dma::TriggerPhase::finalizing); session->finish(); }
      std::lock_guard<std::mutex> lock(mutex_); state_ = daphne::DMA_JOB_READY; phase_ = daphne::DMA_PHASE_IDLE;
    } catch (const std::exception& e) {
      std::string message = e.what();
      if (session) try { session->finish(); } catch (const std::exception& cleanup) { message += "; DMA_QUARANTINED: "; message += cleanup.what(); }
      std::lock_guard<std::mutex> lock(mutex_);
      message_ = message; quarantine_ = message_.find("QUARANTINED") != std::string::npos;
      state_ = cancel_.load() ? daphne::DMA_JOB_CANCELLED : daphne::DMA_JOB_FAILED;
      phase_ = daphne::DMA_PHASE_IDLE;
      if (!triggered && !cancel_.load()) for (auto ch : request.channels) {
        states_[ch / 8] = daphne::FRONTEND_FAILED; approved_[ch / 8] = 0;
      }
      captures_.clear();
    }
  });
  std::lock_guard<std::mutex> lock(mutex_); fill_status(out);
}
void DmaService::scan(const daphne::AfeDelaySweepRequest& req, const std::string& owner,
                      daphne::DmaJobResponse& out) {
  if (req.backend() != daphne::ACQUISITION_DMA) throw std::invalid_argument("BACKEND_MISMATCH");
  // Validate all bounds and total work before saving or changing any registers.
  const uint32_t coarse = req.coarse_step() ? req.coarse_step() : 16;
  const uint32_t verify = req.verification_samples() ? req.verification_samples() : 32768;
  const uint32_t timeout = req.timeout_ms() ? req.timeout_ms() : 600000;
  if (req.firsttap() > req.lasttap() || req.lasttap() > 511 || !req.tapstep() ||
      req.tapstep() > 511 || !coarse || coarse > 511 || req.numberofsamples() < 2 ||
      !req.numberofwaveforms() || req.settletimeus() > 1000000 || (!req.skip_ramp_verification() && verify < 32768) ||
      timeout < 10 || timeout > 600000 || (req.accept_partial_config() && !req.apply_best()))
    throw std::invalid_argument("Invalid bounded DMA scan request");
  std::vector<uint32_t> channels;
  uint32_t mask = 0;
  if (!req.afes_size()) { for (uint32_t a = 0; a < 5; ++a) mask |= 1U << a; }
  for (auto a : req.afes()) {
    if (a >= 5 || (mask & (1U << a))) throw std::invalid_argument("Duplicate/invalid AFE");
    mask |= 1U << a;
  }
  for (uint32_t a = 0; a < 5; ++a) if (mask & (1U << a))
    for (uint32_t l = 0; l < 8; ++l) channels.push_back(a * 8 + l);
  const uint64_t span = req.lasttap() - req.firsttap();
  const uint64_t points = 16 * (span / coarse + 2 + span / req.tapstep() + 2);
  const uint64_t ticks = uint64_t(req.numberofsamples()) * req.numberofwaveforms();
  const uint64_t afe_count = channels.size() / 8;
  const uint64_t verification_ticks = uint64_t(verify) * afe_count * (req.apply_best() && !req.skip_ramp_verification() ? 16 : 0);
  if (ticks > options_.maximum_scan_ticks / points / afe_count ||
      verification_ticks > options_.maximum_scan_ticks - ticks * points * afe_count)
    throw std::invalid_argument("DMA sweep exceeds the advertised scan tick budget");
  daphne_dma::AfeRequest check{std::vector<uint32_t>(channels.begin(), channels.begin() + 8),
      req.numberofsamples(), req.numberofwaveforms(), 10000, identity_.build_id};
  daphne_dma::afe_layout(check, options_.maximum_job_bytes);
  if (req.apply_best() && !req.skip_ramp_verification()) {
    check.length = verify; check.count = 1; daphne_dma::afe_layout(check, options_.maximum_job_bytes);
  }
  if (busy()) throw std::runtime_error("BUSY");
  check_frontend(channels, true);
  new_job(owner);
  { std::lock_guard<std::mutex> lock(mutex_);
    for (auto ch : channels) { states_[ch / 8] = daphne::FRONTEND_CALIBRATING; approved_[ch / 8] = 0; }
  }
  worker_ = std::thread([this, req, mask] {
    try {
      if (!scanner_) throw std::runtime_error("DMA scanner unavailable");
      auto result = scanner_(req, cancel_);
      // A startup probe can observe a temporarily unavailable backend. After
      // calibration has closed its driver FDs, refresh read-only admission in
      // this worker; capabilities on the router continue to use cached data.
      const bool triggered = (identity_.capabilities & 64U) && engine_->supports_triggered();
      std::lock_guard<std::mutex> lock(mutex_);
      triggered_available_ = triggered;
      scan_result_ = std::move(result);
      for (uint32_t a = 0; a < 5; ++a) if (mask & (1U << a)) states_[a] = daphne::FRONTEND_CONFIGURED_UNALIGNED;
      for (const auto& a : scan_result_.afes()) if (a.applied()) {
        approved_[a.afe()] = a.ramp_verification_skipped() ? 0 : a.approved_lane_mask();
        states_[a.afe()] = a.ramp_verification_skipped() ? daphne::FRONTEND_CONFIGURED_UNALIGNED : daphne::FRONTEND_ALIGNED;
      }
      state_ = daphne::DMA_JOB_READY;
    } catch (const std::exception& e) {
      std::lock_guard<std::mutex> lock(mutex_); message_ = e.what();
      quarantine_ = message_.find("QUARANTINED") != std::string::npos;
      for (uint32_t a = 0; a < 5; ++a) if (mask & (1U << a)) { states_[a] = daphne::FRONTEND_FAILED; approved_[a] = 0; }
      state_ = cancel_.load() ? daphne::DMA_JOB_CANCELLED : daphne::DMA_JOB_FAILED;
    }
  });
  std::lock_guard<std::mutex> lock(mutex_); fill_status(out);
}
void DmaService::check_owner(uint64_t id, const std::string& owner) {
  if (!id || id != job_id_ || owner != owner_ || state_ == daphne::DMA_JOB_IDLE)
    throw std::invalid_argument("Unknown DMA job or owner");
  lease_ = std::chrono::steady_clock::now() + std::chrono::milliseconds(options_.lease_ms);
}
void DmaService::fill_status(daphne::DmaJobResponse& out) const {
  out.set_success(true); out.set_backend(daphne::ACQUISITION_DMA); out.set_job_id(job_id_);
  out.set_force_acquisition(force_acquisition_);
  out.set_state(state_); out.set_completed_waveforms(completed_); out.set_expected_waveforms(expected_);
  out.set_message(message_);
  out.set_capture_mode(capture_mode_); out.set_trigger_source(trigger_source_);
  out.set_pretrigger_samples(pretrigger_); out.set_phase(phase_);
  out.set_contract_version(2); out.set_job_timeout_ms(job_timeout_ms_);
  if (capture_mode_ == daphne::DMA_CAPTURE_PERSISTENT) {
    out.set_contract_version(3);
    auto* p = out.mutable_session_progress(); const auto& s = session_status_;
    p->set_target(target_); p->set_accepted(s.accepted); p->set_completed(s.completed);
    p->set_driver_delivered(s.delivered); p->set_driver_released(s.released);
    p->set_staged(staged_total_); p->set_acknowledged(acknowledged_); p->set_delivered(delivered_);
    p->set_staged_bytes(staged_bytes_); p->set_staged_events(staged_.size()); p->set_driver_state(s.state);
    p->set_segment(s.segment); p->set_pauses(s.pauses);
    for (auto count : s.ignored) p->add_ignored(count);
    p->set_allocated_bytes(s.allocated_bytes); p->set_start_ns(s.start_ns); p->set_end_ns(s.end_ns);
    p->set_starts(s.starts); p->set_stops(s.stops); p->set_producer_complete(s.state == DAPHNE_SESSION_COMPLETE);
    p->set_error(s.error); p->set_hardware_error(s.hardware_error); p->set_guards_ok(s.guards_ok);
    p->set_session(s.session);
    p->set_staging_copy_ns(staging_copy_ns_);
    for (const auto& event : staged_) {
      const auto& id = event.capture.event.id; auto* wire = out.add_available_events();
      wire->set_session(id.session); wire->set_sequence(id.sequence); wire->set_generation(id.generation); wire->set_slot(id.slot);
    }
  }
  if (scan_result_.afes_size()) *out.mutable_scan_result() = scan_result_;
}
void DmaService::status(uint64_t id, const std::string& owner, daphne::DmaJobResponse& out) {
  std::lock_guard<std::mutex> lock(mutex_); check_owner(id, owner); fill_status(out);
}
void DmaService::read(const daphne::DmaReadRequest& req, const std::string& owner, daphne::DmaReadResponse& out) {
  std::lock_guard<std::mutex> lock(mutex_); check_owner(req.job_id(), owner);
  if (capture_mode_ == daphne::DMA_CAPTURE_PERSISTENT) { read_persistent(req, out); return; }
  if (req.has_event_id()) throw std::invalid_argument("Event READ requires persistent mode");
  if (state_ != daphne::DMA_JOB_READY || req.waveform() >= captures_.size() || req.route() >= 3)
    throw std::invalid_argument("DMA data unavailable or invalid waveform/route");
  const auto& c = captures_[req.waveform()]; const auto r = req.route();
  if (req.tick_offset() != read_ticks_.at(req.waveform())[r])
    throw std::invalid_argument("DMA fragments must be read sequentially without gaps or repeats");
  const auto width = c.layout.channels[r].size() * 2;
  if (!width || req.tick_offset() >= samples_) throw std::invalid_argument("Invalid DMA tick offset/empty route");
  const auto maximum = req.maximum_bytes() ? std::min(req.maximum_bytes(), options_.maximum_fragment_bytes) : options_.maximum_fragment_bytes;
  const uint32_t count = std::min<uint32_t>(samples_ - req.tick_offset(), maximum / width);
  if (!count) throw std::invalid_argument("DMA fragment budget cannot hold a full tick");
  out.set_success(true); out.set_job_id(job_id_); out.set_backend(daphne::ACQUISITION_DMA);
  out.set_waveform(req.waveform()); out.set_route(r); out.set_sequence(read_sequence_++);
  for (auto ch : c.layout.channels[r]) out.add_channels(ch);
  out.set_samples(samples_); out.set_expected_waveforms(expected_);
  out.set_tick_offset(req.tick_offset()); out.set_tick_count(count);
  out.set_raw16_le(c.raw[r].data() + req.tick_offset() * width, count * width);
  out.set_final_route(req.tick_offset() + count == samples_);
  uint32_t last_route = 2; while (c.layout.channels[last_route].empty()) --last_route;
  out.set_final_waveform(out.final_route() && r == last_route);
  out.set_final_job(out.final_waveform() && req.waveform() + 1 == expected_);
  out.set_gateware_build_id(identity_.build_id); out.set_sample_format(c.status.format);
  out.set_timestamp(c.status.timestamp); out.set_timestamp_valid(bool(c.status.hardware_status & 64));
  out.set_independently_software_triggered(trigger_source_ == daphne::DMA_TRIGGER_SOFTWARE);
  if (c.triggered) {
    auto* m = out.mutable_waveform_metadata(); const auto& t = c.trigger;
    m->set_contract_version(1); m->set_capture_mode(daphne::DMA_CAPTURE_TRIGGERED);
    m->set_trigger_source(trigger_source_); m->set_samples(samples_); m->set_pretrigger_samples(pretrigger_);
    m->set_trigger_index(t.trigger_index); m->set_window_first(t.window_first); m->set_stream_ticks(t.stream_ticks);
    m->set_trigger_timestamp(t.trigger_timestamp); m->set_trigger_timestamp_valid(bool(t.trigger_flags & 1));
    m->set_ignored_triggers(t.ignored_triggers); m->set_period_ticks(t.period_ticks); m->set_ring_ticks(t.ring_ticks);
  }
  read_ticks_.at(req.waveform())[r] += count;
}
void DmaService::control(const daphne::DmaControlRequest& req, const std::string& owner, daphne::DmaJobResponse& out) {
  std::lock_guard<std::mutex> lock(mutex_); check_owner(req.job_id(), owner);
  if (req.action() == daphne::DMA_KEEPALIVE) { fill_status(out); return; }
  if (req.action() != daphne::DMA_CANCEL && req.action() != daphne::DMA_ACK) throw std::invalid_argument("Invalid DMA control action");
  if (capture_mode_ == daphne::DMA_CAPTURE_PERSISTENT && req.action() == daphne::DMA_ACK) {
    ack_persistent(req); fill_status(out); return;
  }
  if (req.event_ids_size()) throw std::invalid_argument("Event IDs only valid in persistent ACK");
  if (req.action() == daphne::DMA_ACK && state_ != daphne::DMA_JOB_READY)
    throw std::invalid_argument("ACK requires a completed validated DMA job");
  if (req.action() == daphne::DMA_ACK)
    for (size_t w = 0; w < captures_.size(); ++w)
      for (size_t r = 0; r < 3; ++r)
        if (captures_[w].layout.bytes[r] && read_ticks_[w][r] != samples_)
          throw std::invalid_argument("ACK requires every validated payload fragment to be read");
  if (state_ == daphne::DMA_JOB_RUNNING) {
    cancel_.store(true); credit_.notify_all(); fill_status(out); return;
  }
  captures_.clear(); staged_.clear(); staged_bytes_ = 0; scan_result_.Clear(); state_ = daphne::DMA_JOB_IDLE; owner_.clear(); fill_status(out);
}
void DmaService::expire() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ != daphne::DMA_JOB_IDLE && std::chrono::steady_clock::now() > lease_) {
    if (state_ == daphne::DMA_JOB_RUNNING) { cancel_.store(true); credit_.notify_all(); }
    else { captures_.clear(); staged_.clear(); staged_bytes_ = 0; scan_result_.Clear(); state_ = daphne::DMA_JOB_IDLE; owner_.clear(); }
  }
}
bool DmaService::dispatch(const daphne::ControlEnvelopeV2& req, const std::string& owner, std::string& out) {
  if (req.type() == daphne::MT2_ACQUISITION_CAPABILITIES_REQ) {
    daphne::AcquisitionCapabilitiesRequest query; daphne::AcquisitionCapabilitiesResponse response;
    if (!query.ParseFromString(req.payload())) { response.set_success(false); response.set_message("Bad capabilities query"); }
    else response = capabilities(query.maximum_protocol_revision());
    out = response.SerializeAsString(); return true;
  }
  if (req.type() == daphne::MT2_DMA_READ_REQ) {
    daphne::DmaReadRequest r; daphne::DmaReadResponse response;
    try { if (!r.ParseFromString(req.payload())) throw std::invalid_argument("Bad DMA read payload"); read(r, owner, response); }
    catch (const std::exception& e) { response.set_success(false); response.set_message(e.what()); }
    out = response.SerializeAsString(); return true;
  }
  daphne::DmaJobResponse response;
  try {
    switch (req.type()) {
      case daphne::MT2_DMA_ACQUIRE_REQ: { daphne::DmaAcquireRequest r; if (!r.ParseFromString(req.payload())) throw std::invalid_argument("Bad DMA acquisition payload"); start(r, owner, response); break; }
      case daphne::MT2_DMA_SCAN_REQ: { daphne::AfeDelaySweepRequest r; if (!r.ParseFromString(req.payload())) throw std::invalid_argument("Bad DMA scan payload"); scan(r, owner, response); break; }
      case daphne::MT2_DMA_STATUS_REQ: { daphne::DmaJobRequest r; if (!r.ParseFromString(req.payload())) throw std::invalid_argument("Bad DMA status payload"); status(r.job_id(), owner, response); break; }
      case daphne::MT2_DMA_CONTROL_REQ: { daphne::DmaControlRequest r; if (!r.ParseFromString(req.payload())) throw std::invalid_argument("Bad DMA control payload"); control(r, owner, response); break; }
      default: return false;
    }
  } catch (const std::exception& e) { response.set_success(false); response.set_message(e.what()); response.set_backend(daphne::ACQUISITION_DMA); }
  out = response.SerializeAsString(); return true;
}
} // namespace daphne_sc
