#include "server_controller/dma_service.hpp"
#include <iostream>
#include <cstdlib>
using namespace daphne;
using namespace daphne_sc;
using namespace daphne_dma;
static void check(bool b) { if (!b) { std::cerr << "Persistent test failed\n"; std::abort(); } }
struct Trace { std::atomic<unsigned> starts{0}, closes{0}, cancels{0}, releases{0}; bool corrupt = false; };
struct Backend final : AfeSessionBackend {
  Trace& trace; daphne_afe_session_config c{}; uint64_t delivered=0, released=0; bool aborted=false, busy=true;
  explicit Backend(Trace& t) : trace(t) {}
  daphne_afe_session_config prepare(daphne_afe_session_config cfg) override {
    check(!cfg.session && !cfg.slots && cfg.target_events && (cfg.flags & 4));
    c=cfg; c.session=777; c.slots=8; return c;
  }
  void start() override { ++trace.starts; }
  bool get(daphne_afe_session_event& e) override {
    if (delivered==c.target_events) return false;
    e={}; ++delivered; e.id={c.session,delivered,(delivered-1)/8+1,uint32_t((delivered-1)%8),0};
    e.length=c.length; e.pretrigger=c.pretrigger; e.source=c.source; e.channel_mask=c.channel_mask;
    e.first_cursor=(delivered-1)*65536; e.fence_end=e.first_cursor+((uint64_t(c.length)+8191)/8192)*8192;
    e.segment=(delivered-1)/8; e.trigger_index=e.first_cursor+c.pretrigger+e.segment*123456;
    for(unsigned r=0;r<3;++r) for(unsigned ch=r*16;ch<40&&ch<r*16+16;++ch)
      if(c.channel_mask&(1ULL<<ch)) e.valid_bytes[r]+=c.length*2;
    if(trace.corrupt) ++e.id.generation;
    return true;
  }
  void read(const daphne_afe_event_id& id,uint32_t,uint64_t offset,char* data,uint32_t bytes) override {
    check(id.sequence==delivered && bytes<=1048576 && !(offset%2));
    for(unsigned i=0;i<bytes;++i) data[i]=(i%2)?char(id.sequence>>8):char(id.sequence);
  }
  bool release(const daphne_afe_event_id& id) override {
    if(busy) {busy=false;return false;} // EBUSY is retried; accepted release is not.
    check(id.sequence==released+1); ++released; ++trace.releases; return true;
  }
  daphne_afe_session_status status() override {
    daphne_afe_session_status s{}; s.abi=1; s.session=c.session; s.target_events=c.target_events;s.slots=c.slots;
    s.accepted=s.completed=std::min<uint64_t>(c.target_events,delivered+8); s.delivered=delivered; s.released=released;
    s.state=aborted?DAPHNE_SESSION_ABORTED:(delivered==c.target_events?DAPHNE_SESSION_COMPLETE:DAPHNE_SESSION_RUNNING);
    s.guards_ok=1; s.starts=1; s.stops=s.state==DAPHNE_SESSION_RUNNING?0:1; return s;
  }
  void cancel() override { aborted=true; ++trace.cancels; }
  void wait() override {}
  void close() override {++trace.closes;}
};
struct Engine final : AfeCaptureEngine {
  Trace trace;
  daphne_afe_session_caps persistent_caps() const override {
    daphne_afe_session_caps c{};c.abi=1;c.features=31;c.slots=8;c.target_max=UINT64_MAX;
    c.pool_max=448ULL<<20;c.route_max=256ULL<<20;return c;
  }
  std::unique_ptr<AfePersistentSession> open_persistent(const AfePersistentRequest& r) override {
    return make_persistent_session(r,64ULL<<20,std::make_unique<Backend>(trace));
  }
  AfeCapture capture(const AfeRequest&,const std::atomic<bool>&) override {throw std::runtime_error("Unexpected finite capture");}
};
template<class Req,class Resp=DmaJobResponse>
Resp rpc(DmaService& s,MessageTypeV2 type,const Req& req,const std::string& owner="test") {
  ControlEnvelopeV2 env;env.set_type(type);env.set_payload(req.SerializeAsString());std::string raw;
  check(s.dispatch(env,owner,raw));Resp out;check(out.ParseFromString(raw));return out;
}
static DmaJobResponse status(DmaService& s,uint64_t id) {DmaJobRequest r;r.set_job_id(id);return rpc(s,MT2_DMA_STATUS_REQ,r);}
int main() {
  auto engine=std::make_unique<Engine>();auto* fake=engine.get();
  DmaServiceOptions options;options.maximum_job_bytes=2ULL<<20;options.lease_ms=1000;
  DmaService service({0x44415048,0x20000,3,123,144},options,std::move(engine),[](const auto&,bool){},
    [](const AfeDelaySweepRequest& r,const std::atomic<bool>&){
      AfeDelaySweepResponse out;for(auto a:r.afes()){auto* f=out.add_afes();f->set_afe(a);f->set_applied(true);f->set_approved_lane_mask(255);}return out;
    },[]{},[]{return true;});
  check(service.capabilities(2).capture_modes_size()==2);
  check(service.capabilities(3).capture_modes(2).available());
  ConfigureRequest cfg;for(unsigned a:{0U,2U})cfg.add_afes()->set_id(a);service.configured(cfg);
  AfeDelaySweepRequest scan;scan.set_backend(ACQUISITION_DMA);scan.add_afes(0);scan.add_afes(2);
  scan.set_firsttap(100);scan.set_lasttap(104);scan.set_tapstep(4);scan.set_numberofsamples(32768);
  scan.set_numberofwaveforms(1);scan.set_apply_best(true);
  auto job=rpc(service,MT2_DMA_SCAN_REQ,scan);
  for(unsigned i=0;i<2000&&status(service,job.job_id()).state()==DMA_JOB_RUNNING;++i) std::this_thread::sleep_for(std::chrono::milliseconds(1));
  DmaControlRequest ctrl;ctrl.set_job_id(job.job_id());ctrl.set_action(DMA_ACK);check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success());
  DmaAcquireRequest req;req.set_backend(ACQUISITION_DMA);req.set_capture_mode(DMA_CAPTURE_PERSISTENT);
  req.set_protocol_revision(3);req.add_channels(0);req.add_channels(16);req.set_samples(32768);
  req.set_pretrigger_samples(1000);req.set_target_waveforms(37);req.set_timeout_ms(30000);
  req.set_protocol_revision(2);check(!rpc(service,MT2_DMA_ACQUIRE_REQ,req).success());req.set_protocol_revision(3);
  job=rpc(service,MT2_DMA_ACQUIRE_REQ,req);check(job.success());ctrl.set_job_id(job.job_id());
  DmaJobResponse s;
  for(unsigned i=0;i<2000;++i){s=status(service,job.job_id());if(s.available_events_size()==16)break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  check(s.available_events_size()==16&&s.state()==DMA_JOB_RUNNING&&s.session_progress().staged_bytes()==options.maximum_job_bytes);
  std::this_thread::sleep_for(std::chrono::milliseconds(10));check(status(service,job.job_id()).available_events_size()==16);
  check(!rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success()); // final ACK too early
  auto first=s.available_events(0);*ctrl.add_event_ids()=first;
  check(!rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success()); // payload unread
  ctrl.set_action(DMA_KEEPALIVE);check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success());ctrl.set_action(DMA_ACK);
  uint64_t fragments=0;
  for(uint64_t sequence=1;sequence<=37;++sequence) {
    for(unsigned i=0;i<2000;++i){s=status(service,job.job_id());if(s.available_events_size())break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    auto id=s.available_events(0);check(id.sequence()==sequence&&id.generation()==(sequence-1)/8+1);
    for(unsigned route:{0U,1U}) {
      DmaReadRequest read;read.set_job_id(job.job_id());read.set_route(route);*read.mutable_event_id()=id;
      auto stale=read;stale.mutable_event_id()->set_generation(id.generation()+1);
      check(!rpc<DmaReadRequest,DmaReadResponse>(service,MT2_DMA_READ_REQ,stale).success());
      auto result=rpc<DmaReadRequest,DmaReadResponse>(service,MT2_DMA_READ_REQ,read);
      check(result.success()&&result.fragment_sequence()==fragments++&&result.waveform_metadata().event_id().sequence()==sequence);
      check(result.raw16_le().size()==65536&&static_cast<unsigned char>(result.raw16_le()[0])==sequence);
      check(!rpc<DmaReadRequest,DmaReadResponse>(service,MT2_DMA_READ_REQ,read).success());
    }
    ctrl.clear_event_ids();*ctrl.add_event_ids()=id;
    if(sequence==1) {auto wrong=ctrl;wrong.mutable_event_ids(0)->set_session(778);check(!rpc(service,MT2_DMA_CONTROL_REQ,wrong).success());}
    check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success());check(!rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success());
  }
  for(unsigned i=0;i<2000;++i){s=status(service,job.job_id());if(s.state()!=DMA_JOB_RUNNING)break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  check(s.state()==DMA_JOB_READY&&s.session_progress().acknowledged()==37&&s.session_progress().driver_released()==37);
  check(fake->trace.starts==1&&fake->trace.closes==1&&fake->trace.releases==37);
  ctrl.clear_event_ids();check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).state()==DMA_JOB_IDLE);
  // N > 2^32 does not reserve by N. Cancel while bounded staging is full.
  req.set_target_waveforms((1ULL<<32)+7);job=rpc(service,MT2_DMA_ACQUIRE_REQ,req);check(job.success());
  for(unsigned i=0;i<2000;++i){s=status(service,job.job_id());if(s.available_events_size()==16)break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  check(s.session_progress().target()==(1ULL<<32)+7);
  ctrl.set_job_id(job.job_id());ctrl.set_action(DMA_CANCEL);check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).success());
  for(unsigned i=0;i<2000;++i){s=status(service,job.job_id());if(s.state()!=DMA_JOB_RUNNING)break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  check(s.state()==DMA_JOB_CANCELLED);check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).state()==DMA_JOB_IDLE);
  // Corrupt ID fails closed and cancels the owned event.
  fake->trace.corrupt=true;req.set_target_waveforms(1);job=rpc(service,MT2_DMA_ACQUIRE_REQ,req);check(job.success());
  for(unsigned i=0;i<2000;++i){s=status(service,job.job_id());if(s.state()!=DMA_JOB_RUNNING)break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  check(s.state()==DMA_JOB_FAILED&&s.available_events_size()==0);
  ctrl.set_job_id(job.job_id());check(rpc(service,MT2_DMA_CONTROL_REQ,ctrl).state()==DMA_JOB_IDLE);
  std::cout<<"Persistent copy-before-release, bounded pressure, wrap/IDs, stale ACK, N64 and cancellation PASS\n";
}
