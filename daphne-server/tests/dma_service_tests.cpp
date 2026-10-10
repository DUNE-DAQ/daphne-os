#include "server_controller/dma_service.hpp"
#include <cstdlib>
#include <iostream>

using namespace daphne_sc;
using namespace daphne;
void require(bool b) { if (!b) { std::cerr << "DMA service assertion failed\n"; std::exit(1); } }
struct Engine final : daphne_dma::AfeCaptureEngine {
  unsigned starts = 0;
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
int main() {
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

