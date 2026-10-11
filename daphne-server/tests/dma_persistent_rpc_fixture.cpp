// Offline transport integration fixture. It never opens a DMA/MMIO device.
#include "server_controller/dma_service.hpp"
#include "server_controller/v2_envelope.hpp"
#include <zmq.hpp>
#include <iostream>
using namespace daphne_dma;
struct OfflineSession final : AfePersistentSession {
  AfePersistentRequest r; AfeLayout layout; uint64_t produced=0; bool cancelled=false;
  explicit OfflineSession(const AfePersistentRequest& request) : r(request), layout(afe_layout(r.trigger.capture,64ULL<<20)) {}
  bool next(AfeCapture& c,const std::atomic<bool>& cancel) override {
    if(cancel.load())throw std::runtime_error("DMA_CANCELLED");
    if(produced==r.target)return false;
    ++produced;c={};c.layout=layout;auto& e=c.event;
    e.id={111,produced,(produced-1)/8+1,uint32_t((produced-1)%8),0};
    e.channel_mask=layout.mask;e.length=r.trigger.capture.length;e.pretrigger=r.trigger.pretrigger;e.source=r.trigger.source;
    e.first_cursor=(produced-1)*65536;e.fence_end=e.first_cursor+((uint64_t(e.length)+8191)/8192)*8192;
    e.segment=(produced-1)/8;e.trigger_index=e.first_cursor+e.pretrigger+e.segment*123456;
    for(unsigned route=0;route<3;++route) {
      e.valid_bytes[route]=layout.bytes[route];c.raw[route].resize(layout.bytes[route]);
      for(uint32_t t=0;t<e.length;++t)for(size_t k=0;k<layout.channels[route].size();++k) {
        const uint16_t value=(((t+layout.channels[route][k]*100+(produced-1)*10)&0x3fff)^0x2000)<<2;
        const auto off=(size_t(t)*layout.channels[route].size()+k)*2;
        c.raw[route][off]=value&255;c.raw[route][off+1]=value>>8;
      }
    }
    return true;
  }
  daphne_afe_session_status status() override {
    daphne_afe_session_status s{};s.abi=1;s.session=111;s.slots=8;s.target_events=r.target;
    s.accepted=s.completed=s.delivered=s.released=produced;s.starts=1;s.guards_ok=1;
    s.state=cancelled?DAPHNE_SESSION_ABORTED:(produced==r.target?DAPHNE_SESSION_COMPLETE:DAPHNE_SESSION_RUNNING);
    s.stops=s.state==DAPHNE_SESSION_RUNNING?0:1;return s;
  }
  void finish(bool cancel) override {cancelled=cancel;}
};
struct OfflineEngine final : AfeCaptureEngine {
  daphne_afe_session_caps persistent_caps() const override {
    daphne_afe_session_caps c{};c.abi=1;c.features=31;c.slots=8;c.target_max=UINT64_MAX;
    c.pool_max=448ULL<<20;c.route_max=256ULL<<20;return c;
  }
  std::unique_ptr<AfePersistentSession> open_persistent(const AfePersistentRequest& r) override {return std::make_unique<OfflineSession>(r);}
  AfeCapture capture(const AfeRequest&,const std::atomic<bool>&) override {throw std::runtime_error("Offline fixture is persistent only");}
};
int main(int argc,char** argv) {
  if(argc!=2||std::string(argv[1])!="--offline-fixture")return 2;
  daphne_sc::DmaServiceOptions options;options.lease_ms=1000;
  daphne_sc::DmaService service({0x44415048,0x20000,3,123,144},options,std::make_unique<OfflineEngine>(),
      [](const auto&,bool){},[](const daphne::AfeDelaySweepRequest& r,const std::atomic<bool>&){
        daphne::AfeDelaySweepResponse result;for(auto a:r.afes()){auto* f=result.add_afes();f->set_afe(a);f->set_applied(true);f->set_approved_lane_mask(255);}return result;
      },[]{},[]{return true;});
  daphne::ConfigureRequest cfg;for(unsigned a=0;a<5;++a)cfg.add_afes()->set_id(a);service.configured(cfg);
  daphne::AfeDelaySweepRequest scan;scan.set_backend(daphne::ACQUISITION_DMA);
  for(unsigned a=0;a<5;++a)scan.add_afes(a);
  scan.set_firsttap(100);scan.set_lasttap(104);scan.set_tapstep(4);scan.set_numberofsamples(32768);
  scan.set_numberofwaveforms(1);scan.set_apply_best(true);
  daphne::ControlEnvelopeV2 req;req.set_type(daphne::MT2_DMA_SCAN_REQ);req.set_payload(scan.SerializeAsString());std::string raw;
  service.dispatch(req,"setup",raw);daphne::DmaJobResponse job;job.ParseFromString(raw);
  daphne::DmaJobRequest status;status.set_job_id(job.job_id());req.set_type(daphne::MT2_DMA_STATUS_REQ);req.set_payload(status.SerializeAsString());
  do {std::this_thread::sleep_for(std::chrono::milliseconds(1));service.dispatch(req,"setup",raw);job.ParseFromString(raw);}while(job.state()==daphne::DMA_JOB_RUNNING);
  daphne::DmaControlRequest ack;ack.set_job_id(job.job_id());ack.set_action(daphne::DMA_ACK);
  req.set_type(daphne::MT2_DMA_CONTROL_REQ);req.set_payload(ack.SerializeAsString());service.dispatch(req,"setup",raw);
  zmq::context_t context;zmq::socket_t router(context,ZMQ_ROUTER);router.set(zmq::sockopt::linger,0);
  router.bind("tcp://127.0.0.1:*");std::cout<<router.get(zmq::sockopt::last_endpoint)<<std::endl;
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
  while(std::chrono::steady_clock::now()<deadline) {
    service.expire();zmq::pollitem_t item{router.handle(),0,ZMQ_POLLIN,0};zmq::poll(&item,1,std::chrono::milliseconds(10));
    if(!(item.revents&ZMQ_POLLIN))continue;
    zmq::message_t owner,wire; if(!router.recv(owner)||!router.recv(wire))continue;
    req.ParseFromArray(wire.data(),wire.size());
    const std::string name(static_cast<const char*>(owner.data()),owner.size());
    if(!service.dispatch(req,name,raw))return 3;
    const auto response=daphne_sc::v2::make_response(req,daphne_sc::v2::response_type(req.type()),raw).SerializeAsString();
    router.send(owner,zmq::send_flags::sndmore);router.send(zmq::buffer(response),zmq::send_flags::none);
  }
}
