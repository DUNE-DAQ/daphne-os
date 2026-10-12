#include "server_controller/dma_service.hpp"
#include "server_controller/dma_control_policy.hpp"
#include <cstdlib>
#include <iostream>

using namespace daphne_sc;
using namespace daphne;
void require_at(bool b, int line) { if (!b) { std::cerr << "DMA service assertion failed at line " << line << '\n'; std::exit(1); } }
#define require(...) require_at((__VA_ARGS__), __LINE__)
struct Engine final : daphne_dma::AfeCaptureEngine {
  unsigned starts = 0;
  unsigned prepares = 0, arms = 0, finishes = 0;
  uint32_t trigger_source = 99;
  bool triggered = false;
  std::atomic<bool> waiting{false};
  bool supports_triggered() const override { return triggered; }
  struct Session final : daphne_dma::AfeTriggeredSession {
    Engine& engine; daphne_dma::AfeTriggerRequest request;
    bool finished = false;
    Session(Engine& e, const daphne_dma::AfeTriggerRequest& r) : engine(e), request(r) {}
    daphne_dma::AfeCapture next(const std::atomic<bool>& cancel, const daphne_dma::TriggerProgress& progress) override {
      ++engine.arms; progress(daphne_dma::TriggerPhase::waiting);
      while (engine.waiting.load() && !cancel.load()) {
        progress(daphne_dma::TriggerPhase::waiting);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
      if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
      auto c = engine.capture(request.capture, cancel); c.triggered = true;
      c.trigger.pretrigger = request.pretrigger; c.trigger.trigger_index = 8192;
      c.trigger.window_first = 8192 - request.pretrigger; c.trigger.stream_ticks = 16384;
      c.trigger.trigger_flags = 2; c.trigger.period_ticks = 8192; c.trigger.ring_ticks = 24576;
      return c;
    }
    void finish() override { if (!finished) { finished = true; ++engine.finishes; } }
  };
  std::unique_ptr<daphne_dma::AfeTriggeredSession> open_triggered(const daphne_dma::AfeTriggerRequest& r, uint64_t) override {
    ++prepares; trigger_source = r.source; return std::make_unique<Session>(*this, r);
  }
  bool wait = false, quarantine = false;
  daphne_dma::AfeCapture capture(const daphne_dma::AfeRequest& r, const std::atomic<bool>& cancel) override {
    ++starts; require(r.count == 1);
    if (quarantine) throw std::runtime_error("DMA_QUARANTINED");
    while (wait && !cancel.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
    daphne_dma::AfeCapture c; c.layout = daphne_dma::afe_layout(r, 65536);
    c.status.format = 1;
    for (size_t route = 0; route < 3; ++route) c.raw[route].assign(c.layout.bytes[route], '\0');
    return c;
  }
};
template<class Request, class Response = DmaJobResponse>
Response rpc(DmaService& s, MessageTypeV2 type, const Request& request, const std::string& owner = "owner") {
  ControlEnvelopeV2 env; env.set_type(type); env.set_payload(request.SerializeAsString());
  std::string bytes; require(s.dispatch(env, owner, bytes)); Response out; require(out.ParseFromString(bytes)); return out;
}
DmaJobResponse wait_ready(DmaService& s, uint64_t id) {
  DmaJobRequest request; request.set_job_id(id);
  DmaJobResponse r;
  for (unsigned i = 0; i < 1000; ++i) {
    r = rpc(s, MT2_DMA_STATUS_REQ, request);
    if (r.state() != DMA_JOB_RUNNING) return r;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  require(false); return r;
}
void test_triggered() {
  auto engine = std::make_unique<Engine>(); auto* fake = engine.get(); fake->triggered = true;
  DmaServiceOptions options; options.maximum_fragment_bytes = 64; options.lease_ms = 1000;
  DmaService service({0x44415048,0x20000,3,987,80}, options, std::move(engine),
      [](const auto&, bool) {}, [](const AfeDelaySweepRequest&, const std::atomic<bool>&) {
        AfeDelaySweepResponse out; auto* a = out.add_afes(); a->set_afe(0); a->set_applied(true); a->set_approved_lane_mask(255); return out;
      }, [] {}, [] { return true; });
  require(service.capabilities().protocol_revision() == 1 && !service.capabilities().capture_modes_size());
  AcquisitionCapabilitiesRequest query; query.set_maximum_protocol_revision(2);
  const auto caps = rpc<AcquisitionCapabilitiesRequest,AcquisitionCapabilitiesResponse>(service, MT2_ACQUISITION_CAPABILITIES_REQ, query);
  require(caps.protocol_revision() == 2 && caps.capture_modes(1).available());
  ConfigureRequest configure; configure.add_afes()->set_id(0); service.configured(configure);
  AfeDelaySweepRequest scan; scan.set_backend(ACQUISITION_DMA); scan.add_afes(0); scan.set_firsttap(100);
  scan.set_lasttap(104); scan.set_tapstep(4); scan.set_numberofsamples(32768); scan.set_numberofwaveforms(1); scan.set_apply_best(true);
  auto job = rpc(service, MT2_DMA_SCAN_REQ, scan); require(wait_ready(service, job.job_id()).state() == DMA_JOB_READY);
  DmaControlRequest control; control.set_job_id(job.job_id()); control.set_action(DMA_ACK);
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  DmaAcquireRequest acquire; acquire.set_backend(ACQUISITION_DMA); acquire.add_channels(0); acquire.set_samples(17);
  acquire.set_waveforms(2); acquire.set_capture_mode(DMA_CAPTURE_TRIGGERED); acquire.set_pretrigger_samples(8);
  acquire.set_trigger_source(DMA_TRIGGER_EXTERNAL); acquire.set_timeout_ms(1000);
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success());
  require(job.contract_version() == 2 && job.capture_mode() == DMA_CAPTURE_TRIGGERED && job.pretrigger_samples() == 8);
  auto ready = wait_ready(service, job.job_id()); require(ready.state() == DMA_JOB_READY);
  require(fake->prepares == 1 && fake->arms == 2 && fake->finishes == 1 && fake->trigger_source == DAPHNE_AFE_TRIGGER_EXTERNAL);
  for (unsigned wave = 0; wave < 2; ++wave) {
    DmaReadRequest read; read.set_job_id(job.job_id()); read.set_waveform(wave);
    auto fragment = rpc<DmaReadRequest,DmaReadResponse>(service, MT2_DMA_READ_REQ, read);
    require(fragment.success() && !fragment.independently_software_triggered() && fragment.has_waveform_metadata());
    const auto& m = fragment.waveform_metadata(); require(m.trigger_source() == DMA_TRIGGER_EXTERNAL && m.pretrigger_samples() == 8);
    require(m.window_first() == m.trigger_index() - 8 && !m.trigger_timestamp_valid());
  }
  control.set_job_id(job.job_id()); require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  // STATUS and KEEPALIVE stay responsive while the worker waits for a hardware event.
  fake->waiting.store(true); acquire.set_trigger_source(DMA_TRIGGER_TIMING);
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success());
  DmaJobRequest status; status.set_job_id(job.job_id());
  for (unsigned i = 0; i < 1000; ++i) {
    ready = rpc(service, MT2_DMA_STATUS_REQ, status);
    if (ready.phase() == DMA_PHASE_WAITING_TRIGGER) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  require(ready.phase() == DMA_PHASE_WAITING_TRIGGER && service.busy());
  require(!rpc(service, MT2_DMA_ACQUIRE_REQ, acquire).success());
  control.set_job_id(job.job_id()); control.set_action(DMA_KEEPALIVE);
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).state() == DMA_JOB_RUNNING);
  control.set_action(DMA_CANCEL); require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_CANCELLED);
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  require(fake->finishes == 2 && service.capabilities().afes(0).state() == FRONTEND_ALIGNED);
  // Missing events expire the total deadline without revoking AFE alignment.
  acquire.set_job_timeout_ms(10);
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success());
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_FAILED);
  require(service.capabilities().afes(0).state() == FRONTEND_ALIGNED);
  control.set_job_id(job.job_id()); require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  // A disconnected client cannot leave cyclic history running indefinitely.
  acquire.set_job_timeout_ms(0);
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success());
  std::this_thread::sleep_for(std::chrono::milliseconds(1100)); service.expire();
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_CANCELLED);
  control.set_job_id(job.job_id()); require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
}
void test_triggered_admission_after_calibration() {
  auto engine = std::make_unique<Engine>(); auto* fake = engine.get();
  DmaService service({0x44415048,0x20000,3,987,80}, {}, std::move(engine),
      [](const auto&, bool) {}, [fake](const AfeDelaySweepRequest&, const std::atomic<bool>&) {
        fake->triggered = true;
        AfeDelaySweepResponse out; auto* a = out.add_afes(); a->set_afe(0);
        a->set_applied(true); a->set_approved_lane_mask(255); return out;
      }, [] {}, [] { return true; });
  require(!service.capabilities(2).capture_modes(1).available());
  ConfigureRequest configure; configure.add_afes()->set_id(0); service.configured(configure);
  AfeDelaySweepRequest scan; scan.set_backend(ACQUISITION_DMA); scan.add_afes(0);
  scan.set_firsttap(100); scan.set_lasttap(104); scan.set_tapstep(4);
  scan.set_numberofsamples(32768); scan.set_numberofwaveforms(1); scan.set_apply_best(true);
  auto job = rpc(service, MT2_DMA_SCAN_REQ, scan);
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_READY);
  require(service.capabilities(2).capture_modes(1).available());
}
void test_long_scan_verification_budget() {
  auto engine = std::make_unique<Engine>();
  unsigned scans = 0, guards = 0;
  DmaServiceOptions options; options.maximum_scan_ticks = 200000;
  DmaService service({0x44415048,0x20000,3,987,80}, options, std::move(engine),
      [&](const auto&, bool) { ++guards; }, [&](const AfeDelaySweepRequest&, const std::atomic<bool>&) {
        ++scans; return AfeDelaySweepResponse{};
      }, [] {}, [] { return true; });
  ConfigureRequest configure; configure.add_afes()->set_id(0); service.configured(configure);
  AfeDelaySweepRequest scan; scan.set_backend(ACQUISITION_DMA); scan.add_afes(0);
  scan.set_firsttap(100); scan.set_lasttap(104); scan.set_tapstep(4);
  scan.set_numberofsamples(2048); scan.set_numberofwaveforms(1); scan.set_apply_best(true);
  scan.set_verification_samples(32768);
  const auto result = rpc(service, MT2_DMA_SCAN_REQ, scan);
  require(!result.success() && result.message().find("scan tick budget") != std::string::npos);
  require(scans == 0 && guards == 0 && !service.busy());
}
void test_explicit_force_and_unverified_scan() {
  auto engine = std::make_unique<Engine>();
  bool reject_hardware = false;
  unsigned scans = 0;
  DmaService service({0x44415048,0x20000,3,987,80}, {}, std::move(engine),
      [&](const auto&, bool) { if (reject_hardware) throw std::runtime_error("FRONTEND_NOT_READY"); },
      [&](const AfeDelaySweepRequest& req, const std::atomic<bool>&) {
        ++scans; if (scans == 1) throw std::runtime_error("Final physical ramp verification failed");
        AfeDelaySweepResponse out; out.set_success(true);out.set_backend(ACQUISITION_DMA);
        auto* a=out.add_afes();a->set_afe(0);a->set_applied(true);a->set_approved_lane_mask(1);
        a->set_ramp_verification_skipped(req.skip_ramp_verification());return out;
      }, [] {}, [] { return true; });
  DmaAcquireRequest acquire;acquire.set_backend(ACQUISITION_DMA);acquire.add_channels(1);
  acquire.set_samples(17);acquire.set_waveforms(1);
  require(!rpc(service,MT2_DMA_ACQUIRE_REQ,acquire).success());
  acquire.set_force_acquisition(true);
  auto job=rpc(service,MT2_DMA_ACQUIRE_REQ,acquire);require(job.success() && job.force_acquisition());
  require(wait_ready(service,job.job_id()).state()==DMA_JOB_READY);
  DmaControlRequest ctl;ctl.set_job_id(job.job_id());ctl.set_action(DMA_CANCEL);require(rpc(service,MT2_DMA_CONTROL_REQ,ctl).success());
  reject_hardware=true;require(!rpc(service,MT2_DMA_ACQUIRE_REQ,acquire).success());reject_hardware=false;
  ConfigureRequest cfg;cfg.add_afes()->set_id(0);service.configured(cfg);
  AfeDelaySweepRequest scan;scan.set_backend(ACQUISITION_DMA);scan.add_afes(0);scan.set_firsttap(100);
  scan.set_lasttap(104);scan.set_tapstep(4);scan.set_numberofsamples(2048);scan.set_numberofwaveforms(1);scan.set_apply_best(true);
  job=rpc(service,MT2_DMA_SCAN_REQ,scan);require(wait_ready(service,job.job_id()).state()==DMA_JOB_FAILED);
  ctl.set_job_id(job.job_id());ctl.set_action(DMA_CANCEL);require(rpc(service,MT2_DMA_CONTROL_REQ,ctl).success());
  // A failed scan may be measured again without a configuration rewrite.
  scan.set_skip_ramp_verification(true);
  job=rpc(service,MT2_DMA_SCAN_REQ,scan);require(job.success());
  require(wait_ready(service,job.job_id()).state()==DMA_JOB_READY);
  require(service.capabilities().afes(0).state()==FRONTEND_CONFIGURED_UNALIGNED);
  require(service.capabilities().afes(0).approved_lane_mask()==0);
  ctl.set_job_id(job.job_id());ctl.set_action(DMA_ACK);require(rpc(service,MT2_DMA_CONTROL_REQ,ctl).success());
  acquire.set_force_acquisition(false);require(!rpc(service,MT2_DMA_ACQUIRE_REQ,acquire).success());
  acquire.set_force_acquisition(true);job=rpc(service,MT2_DMA_ACQUIRE_REQ,acquire);require(job.success());
  require(wait_ready(service,job.job_id()).state()==DMA_JOB_READY);
}
int main() {
  test_triggered();
  test_triggered_admission_after_calibration();
  test_long_scan_verification_budget();
  test_explicit_force_and_unverified_scan();
  auto engine = std::make_unique<Engine>(); auto* fake = engine.get();
  unsigned guards = 0;
  DmaServiceOptions options; options.maximum_job_bytes = 2U << 20; options.maximum_fragment_bytes = 64;
  DmaService service({0x44415048,0x20000,3,123,16}, options, std::move(engine),
    [&](const auto&, bool) { ++guards; },
    [](const AfeDelaySweepRequest& r, const std::atomic<bool>&) {
      AfeDelaySweepResponse out; out.set_success(true); out.set_backend(ACQUISITION_DMA);
      for (auto a : r.afes()) { auto* s = out.add_afes(); s->set_afe(a); s->set_applied(true); s->set_approved_lane_mask(255); }
      return out;
    }, [] {}, [] { return true; });
  DmaAcquireRequest acquire; acquire.set_backend(ACQUISITION_DMA); acquire.add_channels(39); acquire.add_channels(0);
  acquire.set_samples(17); acquire.set_waveforms(3); acquire.set_timeout_ms(1000);
  require(!rpc(service, MT2_DMA_ACQUIRE_REQ, acquire).success()); // Alignment cannot be asserted by acquisition.
  ConfigureRequest configure; for (unsigned a = 0; a < 5; ++a) configure.add_afes()->set_id(a);
  service.configured(configure);
  AfeDelaySweepRequest scan; scan.set_backend(ACQUISITION_DMA); scan.add_afes(0); scan.add_afes(4);
  scan.set_firsttap(100); scan.set_lasttap(104); scan.set_tapstep(4); scan.set_numberofsamples(32768);
  scan.set_numberofwaveforms(1); scan.set_apply_best(true);
  auto job = rpc(service, MT2_DMA_SCAN_REQ, scan); require(job.success());
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_READY);
  DmaControlRequest control; control.set_job_id(job.job_id()); control.set_action(DMA_ACK);
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  acquire.set_trigger_source(DMA_TRIGGER_EXTERNAL); guards = 0;
  require(!rpc(service, MT2_DMA_ACQUIRE_REQ, acquire).success() && guards == 0 && fake->starts == 0);
  acquire.set_trigger_source(DMA_TRIGGER_SOFTWARE);
  cmd_writeTrim_singleChannel trim; trim.set_trimchannel(39);
  require(affected_afe_mask(MT2_WRITE_TRIM_CH_REQ, trim.SerializeAsString()) == 16);
  service.invalidate(false, 16);
  auto caps = service.capabilities();
  require(caps.afes(0).state() == FRONTEND_ALIGNED && caps.afes(4).state() == FRONTEND_CONFIGURED_UNALIGNED);
  require(!rpc(service, MT2_DMA_ACQUIRE_REQ, acquire).success());
  job = rpc(service, MT2_DMA_SCAN_REQ, scan); require(job.success());
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_READY);
  control.set_job_id(job.job_id());
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success());
  auto ready = wait_ready(service, job.job_id()); require(ready.completed_waveforms() == 3 && fake->starts == 3);
  control.set_job_id(job.job_id());
  require(!rpc(service, MT2_DMA_CONTROL_REQ, control).success()); // Cannot ACK unread payload.
  DmaJobRequest status; status.set_job_id(job.job_id());
  require(!rpc(service, MT2_DMA_STATUS_REQ, status, "intruder").success());
  unsigned sequence = 0;
  for (unsigned w = 0; w < 3; ++w) for (unsigned route : {0,2}) {
    DmaReadRequest read; read.set_job_id(job.job_id()); read.set_waveform(w); read.set_route(route);
    auto fragment = rpc<DmaReadRequest,DmaReadResponse>(service, MT2_DMA_READ_REQ, read);
    require(fragment.success() && fragment.sequence() == sequence++ && fragment.tick_count() == 17);
    require(fragment.final_job() == (w == 2 && route == 2));
    require(!rpc<DmaReadRequest,DmaReadResponse>(service, MT2_DMA_READ_REQ, read).success());
  }
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  fake->wait = true;
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success() && service.busy());
  control.set_job_id(job.job_id()); control.set_action(DMA_CANCEL);
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_CANCELLED);
  require(rpc(service, MT2_DMA_CONTROL_REQ, control).success());
  fake->wait = false; fake->quarantine = true;
  job = rpc(service, MT2_DMA_ACQUIRE_REQ, acquire); require(job.success());
  require(wait_ready(service, job.job_id()).state() == DMA_JOB_FAILED && service.busy());
  require(!service.capabilities().dma_available());
  service.shutdown();
  std::cout << "DMA ownership, triggers, ACK, cancellation and quarantine tests passed\n";
}

