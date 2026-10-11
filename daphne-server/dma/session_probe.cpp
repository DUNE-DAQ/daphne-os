// Standalone driver/DDR qualification; pattern words are diagnostic RAW16,
// not ADC14, so they never pass through the normal client decoder.
#include "afe_capture.hpp"
#include <chrono>
#include <iostream>
#include <sstream>
#include <thread>
using namespace daphne_dma;
int main(int argc, char** argv) {
  std::unique_ptr<AfePersistentSession> session;
  try {
    if (argc < 7 || argc > 8) throw std::invalid_argument("usage: daphne-afe-session-probe BUILD_ID N L P CHANNELS pattern|aligned [pause_ms]");
    AfePersistentRequest r; r.target = std::stoull(argv[2]);
    r.trigger.capture.build_id = std::stoul(argv[1], nullptr, 0);
    r.trigger.capture.length = std::stoul(argv[3]); r.trigger.pretrigger = std::stoul(argv[4]);
    std::istringstream channels(argv[5]); std::string ch;
    while (std::getline(channels, ch, ',')) r.trigger.capture.channels.push_back(std::stoul(ch));
    if (std::string(argv[6]) != "pattern" && std::string(argv[6]) != "aligned") throw std::invalid_argument("Explicit pattern|aligned required");
    r.pattern = std::string(argv[6]) == "pattern"; r.ring_budget = 448ULL << 20;
    r.trigger.capture.timeout_ms = 30000;
    const unsigned pause = argc == 8 ? std::stoul(argv[7]) : 0;
    if (!r.target || r.target > 10000 || pause > 1000) throw std::invalid_argument("Probe limited to N<=10000 and pause<=1000 ms");
    session = open_linux_persistent(r, 64ULL << 20, "/dev/daphne-afe-dma");
    const auto start = std::chrono::steady_clock::now();
    const auto deadline = start + std::chrono::seconds(120);
    std::atomic<bool> cancel{false}; uint64_t bytes=0, count=0, copy_ns=0;
    while (count < r.target) {
      if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("Probe 120 s deadline expired");
      AfeCapture c;
      if (!session->next(c, cancel)) { std::this_thread::sleep_for(std::chrono::milliseconds(2)); continue; }
      if (r.pattern) for (unsigned route=0;route<3;++route) {
        const auto width=c.layout.channels[route].size();
        for (uint32_t t=0;t<r.trigger.capture.length;++t) for (size_t k=0;k<width;++k) {
          const auto offset=(size_t(t)*width+k)*2;
          const auto word=uint16_t(static_cast<unsigned char>(c.raw[route][offset])) |
              (uint16_t(static_cast<unsigned char>(c.raw[route][offset+1]))<<8);
          const auto expected=(c.layout.channels[route][k]<<10) | ((c.event.trigger_index-r.trigger.pretrigger+t)&1023);
          if (word != expected) throw std::runtime_error("Pattern integrity mismatch event="+std::to_string(c.event.id.sequence)+" route="+std::to_string(route)+" tick="+std::to_string(t));
        }
      }
      bytes+=c.layout.total_bytes;copy_ns+=c.copy_ns;++count;
      if (pause) std::this_thread::sleep_for(std::chrono::milliseconds(pause));
    }
    const double delivery_seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    auto s=session->status();
    while (s.state!=DAPHNE_SESSION_COMPLETE || s.released!=r.target) {
      if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("Probe final stop deadline expired");
      std::this_thread::sleep_for(std::chrono::milliseconds(2));s=session->status();
    }
    if (s.accepted!=r.target || s.completed!=r.target || s.delivered!=r.target || s.starts!=1 || s.stops!=1 || !s.guards_ok)
      throw std::runtime_error("Probe final counts/guards failed");
    session->finish(false);
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"{\"events\":"<<count<<",\"bytes\":"<<bytes<<",\"seconds\":"<<seconds
      <<",\"capture_delivery_seconds\":"<<delivery_seconds<<",\"final_drain_close_seconds\":"<<seconds-delivery_seconds
      <<",\"copy_ns\":"<<copy_ns<<",\"payload_MB_s\":"<<bytes/seconds/1e6<<",\"pauses\":"<<s.pauses
      <<",\"starts\":"<<s.starts<<",\"stops\":"<<s.stops<<",\"guards_ok\":true,\"pattern\":"<<(r.pattern?"true":"false")<<"}\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr<<e.what()<<'\n';
    if(session) try {session->finish(true);} catch(const std::exception& cleanup){std::cerr<<"DMA_QUARANTINED: "<<cleanup.what()<<'\n';}
    return 1;
  }
}
