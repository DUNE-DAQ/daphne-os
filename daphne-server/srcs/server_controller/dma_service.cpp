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
      !engine_ || !guard_ || !live_guard_ || !device_available_)
    throw std::invalid_argument("Invalid DMA service budgets/dependencies");
}
DmaService::~DmaService() { shutdown(); }
void DmaService::verify_live() const { live_guard_(); }
void DmaService::shutdown() { cancel_.store(true); if (worker_.joinable()) worker_.join(); }
bool DmaService::busy() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return state_ == daphne::DMA_JOB_RUNNING || quarantine_;
}
void DmaService::invalidate(bool unconfigured) {
  std::lock_guard<std::mutex> lock(mutex_);
  ++generation_;
  approved_.fill(0);
  for (auto& state : states_)
    state = unconfigured ? daphne::FRONTEND_UNCONFIGURED :
        (state == daphne::FRONTEND_UNCONFIGURED ? state : daphne::FRONTEND_CONFIGURED_UNALIGNED);
}
void DmaService::configured(const daphne::ConfigureRequest& req) {
  std::lock_guard<std::mutex> lock(mutex_);
  ++generation_; approved_.fill(0); states_.fill(daphne::FRONTEND_UNCONFIGURED);
  for (const auto& afe : req.afes()) states_.at(afe.id()) = daphne::FRONTEND_CONFIGURED_UNALIGNED;
}
daphne::AcquisitionCapabilitiesResponse DmaService::capabilities() const {
  std::lock_guard<std::mutex> lock(mutex_);
  daphne::AcquisitionCapabilitiesResponse r;
  r.set_success(true); r.set_protocol_revision(1); r.set_backend(daphne::ACQUISITION_DMA);
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
  for (uint32_t a = 0; a < 5; ++a) {
    auto* s = r.add_afes(); s->set_afe(a); s->set_state(states_[a]);
    s->set_approved_lane_mask(approved_[a]); s->set_configuration_generation(generation_);
  }
  return r;
}
void DmaService::check_frontend(const std::vector<uint32_t>& channels, bool calibration) {
  live_guard_();
  guard_(channels, calibration);
  for (auto ch : channels) {
    const uint32_t a = ch / 8;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (states_[a] == daphne::FRONTEND_UNCONFIGURED || states_[a] == daphne::FRONTEND_FAILED ||
          (!calibration && !(approved_[a] & (1U << (ch % 8)))))
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
  lease_ = std::chrono::steady_clock::now() + std::chrono::milliseconds(options_.lease_ms);
}
void DmaService::start(const daphne::DmaAcquireRequest& req, const std::string& owner,
                       daphne::DmaJobResponse& out) {
  if (req.backend() != daphne::ACQUISITION_DMA)
    throw std::invalid_argument("BACKEND_MISMATCH: DMA must be selected explicitly");
  if (req.trigger_source() != daphne::DMA_TRIGGER_SOFTWARE)
    throw std::invalid_argument("TRIGGER_UNSUPPORTED: this firmware supports DMA software trigger/START only");
  daphne_dma::AfeRequest request;
  request.channels.assign(req.channels().begin(), req.channels().end());
  request.length = req.samples(); request.build_id = identity_.build_id;
  request.timeout_ms = req.timeout_ms() ? req.timeout_ms() : 10000;
  const auto layout = daphne_dma::afe_layout(request, options_.maximum_job_bytes);
  if (!req.waveforms() || req.waveforms() > options_.maximum_waveforms ||
      layout.total_bytes > options_.maximum_job_bytes / req.waveforms())
    throw std::invalid_argument("DMA job exceeds waveform/byte budget; reduce the client batch");
  if (busy()) throw std::runtime_error("BUSY");
  check_frontend(request.channels, false);
  new_job(owner);
  { std::lock_guard<std::mutex> lock(mutex_); samples_ = request.length; expected_ = req.waveforms(); }
  worker_ = std::thread([this, request, n = req.waveforms()] {
    try {
      for (uint32_t wave = 0; wave < n; ++wave) {
        check_frontend(request.channels, false);
        auto capture = engine_->capture(request, cancel_); // count=1: one software trigger per waveform
        std::lock_guard<std::mutex> lock(mutex_);
        captures_.push_back(std::move(capture)); read_ticks_.push_back({}); ++completed_;
      }
      std::lock_guard<std::mutex> lock(mutex_); state_ = daphne::DMA_JOB_READY;
    } catch (const std::exception& e) {
      std::lock_guard<std::mutex> lock(mutex_);
      message_ = e.what(); quarantine_ = message_.find("QUARANTINED") != std::string::npos;
      state_ = cancel_.load() ? daphne::DMA_JOB_CANCELLED : daphne::DMA_JOB_FAILED;
      if (!cancel_.load()) for (auto ch : request.channels) {
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
      !req.numberofwaveforms() || req.settletimeus() > 1000000 || verify < 32768 ||
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
  if (ticks > options_.maximum_scan_ticks / points / afe_count ||
      uint64_t(verify) * afe_count > options_.maximum_scan_ticks - ticks * points * afe_count)
    throw std::invalid_argument("DMA sweep exceeds the advertised scan tick budget");
  daphne_dma::AfeRequest check{std::vector<uint32_t>(channels.begin(), channels.begin() + 8),
      req.numberofsamples(), req.numberofwaveforms(), 10000, identity_.build_id};
  daphne_dma::afe_layout(check, options_.maximum_job_bytes);
  check.length = verify; check.count = 1; daphne_dma::afe_layout(check, options_.maximum_job_bytes);
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
      std::lock_guard<std::mutex> lock(mutex_);
      scan_result_ = std::move(result);
      for (uint32_t a = 0; a < 5; ++a) if (mask & (1U << a)) states_[a] = daphne::FRONTEND_CONFIGURED_UNALIGNED;
      for (const auto& a : scan_result_.afes()) if (a.applied()) {
        approved_[a.afe()] = a.approved_lane_mask(); states_[a.afe()] = daphne::FRONTEND_ALIGNED;
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
  out.set_state(state_); out.set_completed_waveforms(completed_); out.set_expected_waveforms(expected_);
  out.set_message(message_);
  if (scan_result_.afes_size()) *out.mutable_scan_result() = scan_result_;
}
void DmaService::status(uint64_t id, const std::string& owner, daphne::DmaJobResponse& out) {
  std::lock_guard<std::mutex> lock(mutex_); check_owner(id, owner); fill_status(out);
}
void DmaService::read(const daphne::DmaReadRequest& req, const std::string& owner, daphne::DmaReadResponse& out) {
  std::lock_guard<std::mutex> lock(mutex_); check_owner(req.job_id(), owner);
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
  out.set_independently_software_triggered(true);
  read_ticks_.at(req.waveform())[r] += count;
}
void DmaService::control(const daphne::DmaControlRequest& req, const std::string& owner, daphne::DmaJobResponse& out) {
  std::lock_guard<std::mutex> lock(mutex_); check_owner(req.job_id(), owner);
  if (req.action() == daphne::DMA_KEEPALIVE) { fill_status(out); return; }
  if (req.action() != daphne::DMA_CANCEL && req.action() != daphne::DMA_ACK) throw std::invalid_argument("Invalid DMA control action");
  if (req.action() == daphne::DMA_ACK && state_ != daphne::DMA_JOB_READY)
    throw std::invalid_argument("ACK requires a completed validated DMA job");
  if (req.action() == daphne::DMA_ACK)
    for (size_t w = 0; w < captures_.size(); ++w)
      for (size_t r = 0; r < 3; ++r)
        if (captures_[w].layout.bytes[r] && read_ticks_[w][r] != samples_)
          throw std::invalid_argument("ACK requires every validated payload fragment to be read");
  if (state_ == daphne::DMA_JOB_RUNNING) {
    cancel_.store(true); fill_status(out); return;
  }
  captures_.clear(); scan_result_.Clear(); state_ = daphne::DMA_JOB_IDLE; owner_.clear(); fill_status(out);
}
void DmaService::expire() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ != daphne::DMA_JOB_IDLE && std::chrono::steady_clock::now() > lease_) {
    if (state_ == daphne::DMA_JOB_RUNNING) cancel_.store(true);
    else { captures_.clear(); scan_result_.Clear(); state_ = daphne::DMA_JOB_IDLE; owner_.clear(); }
  }
}
bool DmaService::dispatch(const daphne::ControlEnvelopeV2& req, const std::string& owner, std::string& out) {
  if (req.type() == daphne::MT2_ACQUISITION_CAPABILITIES_REQ) { out = capabilities().SerializeAsString(); return true; }
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
