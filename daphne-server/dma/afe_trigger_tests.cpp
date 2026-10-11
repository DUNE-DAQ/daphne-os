#include "afe_capture.hpp"
#include <iostream>
using namespace daphne_dma;
void require(bool value) { if (!value) throw std::runtime_error("Triggered engine assertion failed"); }
template<class F> void rejects(F f) { bool rejected = false; try { f(); } catch (...) { rejected = true; } require(rejected); }
struct Trace {
  unsigned prepared=0, arms=0, triggers=0, reads=0, stops=0, polls=0;
  bool short_read=false, fail_stop=false, fail_arm=false;
  daphne_afe_trigger_config config{};
};
struct Backend final : AfeTriggerBackend {
  std::shared_ptr<Trace> t;
  unsigned step=0;
  explicit Backend(std::shared_ptr<Trace> trace): t(std::move(trace)) {}
  void prepare(const daphne_afe_trigger_config& c) override { t->config=c; ++t->prepared; }
  void arm() override { ++t->arms; step=0; if(t->fail_arm) throw std::runtime_error("EINTR uncertain ARM"); }
  bool software_trigger() override { return ++t->triggers > 1; }
  daphne_afe_trigger_status status() override {
    ++step; const auto& c=t->config; daphne_afe_trigger_status s{};
    s.abi=1; s.pretrigger=c.pretrigger; s.period_ticks=c.period_ticks; s.ring_ticks=c.ring_ticks; s.source=c.source;
    auto& a=s.capture; a.abi=1; a.flags=2; a.format=1; a.build_id=c.expected_build_id; a.channel_mask=c.channel_mask;
    a.guards_ok=1; a.state=step>=3 ? DAPHNE_AFE_COMPLETE : DAPHNE_AFE_RUNNING;
    a.hardware_status=step>=3 ? 2 : 1;
    s.armed=step<3; s.trigger_flags=step>=3 ? 2 : 0;
    s.trigger_index=uint64_t(c.ring_ticks)*3+c.pretrigger; s.window_first=s.trigger_index-c.pretrigger;
    s.stream_ticks=((s.window_first+c.length+c.period_ticks-1)/c.period_ticks)*c.period_ticks;
    for(unsigned r=0;r<3;++r) {
      unsigned channels=0; for(unsigned ch=r*16;ch<std::min(40U,r*16+16);++ch) if(c.channel_mask&(1ULL<<ch)) ++channels;
      const uint64_t stride=channels*2;
      a.dma_status[r]=1;
      if(!stride) continue;
      a.active_routes|=1U<<r; a.valid_bytes[r]=stride*c.length;
      a.transfer_bytes[r]=stride*c.ring_ticks; a.received_bytes[r]=stride*s.stream_ticks;
      a.accepted_beats[r]=a.received_bytes[r]/16;
      a.allocated_bytes+=(a.transfer_bytes[r]+128+4095)&~4095ULL;
    }
    return s;
  }
  void wait() override { ++t->polls; }
  std::string read_route(uint32_t, uint64_t bytes, const std::atomic<bool>&) override {
    ++t->reads; return std::string(bytes-(t->short_read?1:0),'\0');
  }
  void stop() override { ++t->stops; if(t->fail_stop) throw std::runtime_error("halt not proven"); }
};
int main() {
  AfeTriggerRequest req{{{39,0,17},65536,1,1000,123},8192,0,8192};
  auto layout=afe_trigger_layout(req,64ULL<<20,448ULL<<20);
  require(layout.ring_ticks==81920);
  auto bad=req; bad.pretrigger=bad.capture.length; rejects([&]{afe_trigger_layout(bad,64ULL<<20,448ULL<<20);});
  rejects([&]{afe_trigger_layout(req,64ULL<<20,1);});
  auto trace=std::make_shared<Trace>(); std::atomic<bool> cancel{false};
  auto session=make_triggered_session(req,64ULL<<20,448ULL<<20,std::make_unique<Backend>(trace));
  auto first=session->next(cancel,{}); auto second=session->next(cancel,{});
  require(first.trigger.trigger_index-first.trigger.window_first==8192 && second.raw[2].size()==131072);
  require(trace->prepared==1 && trace->arms==2 && trace->triggers==3 && trace->reads==6);
  auto invalid=first.trigger; invalid.stream_ticks+=1; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  // Real consumer retains monitor registers sampled before its halt/reset.
  // One route's physical snapshot: IDLE, RUN/CYCLIC still visible in cache.
  auto cached=first.trigger;
  for(unsigned r=0;r<3;++r) { cached.capture.dma_status[r]=69640; cached.capture.dma_control[r]=81939; }
  validate_afe_trigger_completion(req,layout,cached);
  invalid=cached; invalid.capture.dma_status[0]=0; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  invalid=cached; invalid.capture.dma_status[0]|=0x10; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  invalid=cached; invalid.capture.dma_control[0]|=4; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  invalid=cached; invalid.capture.hardware_status=1; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  invalid=first.trigger; invalid.trigger_flags=0; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  invalid=first.trigger; invalid.capture.guards_ok=0; rejects([&]{validate_afe_trigger_completion(req,layout,invalid);});
  session->finish(); require(trace->stops==1); session.reset(); require(trace->stops==1);
  for(unsigned source : {1U,2U}) {
    req.source=source; trace=std::make_shared<Trace>();
    session=make_triggered_session(req,64ULL<<20,448ULL<<20,std::make_unique<Backend>(trace));
    session->next(cancel,{}); session->finish(); require(trace->triggers==0);
  }
  trace=std::make_shared<Trace>(); trace->fail_arm=true;
  session=make_triggered_session(req,64ULL<<20,448ULL<<20,std::make_unique<Backend>(trace));
  rejects([&]{session->next(cancel,{});}); require(trace->arms==1 && trace->stops==1);
  trace=std::make_shared<Trace>(); trace->short_read=true; trace->fail_stop=true;
  session=make_triggered_session(req,64ULL<<20,448ULL<<20,std::make_unique<Backend>(trace));
  try { session->next(cancel,{}); require(false); } catch(const std::exception& e) { require(std::string(e.what()).find("QUARANTINED")!=std::string::npos); }
  session.reset(); require(trace->stops==1);
  trace=std::make_shared<Trace>(); trace->fail_stop=true;
  session=make_triggered_session(req,64ULL<<20,448ULL<<20,std::make_unique<Backend>(trace));
  session->next(cancel,{});
  try { session->finish(); require(false); } catch(const std::exception& e) { require(std::string(e.what()).find("QUARANTINED")!=std::string::npos); }
  session.reset(); require(trace->stops==1);
  trace=std::make_shared<Trace>();
  session=make_triggered_session(req,64ULL<<20,448ULL<<20,std::make_unique<Backend>(trace));
  rejects([&]{session->next(cancel,[&](TriggerPhase phase){if(phase==TriggerPhase::waiting) cancel=true;});});
  require(trace->reads==0 && trace->stops==1);
  std::cout<<"Triggered geometry, wrap, repeated ARM, source, cancellation and quarantine passed\n";
}
