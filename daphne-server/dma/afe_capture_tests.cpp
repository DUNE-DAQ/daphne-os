#include "afe_capture.hpp"
#include <functional>
#include <iostream>
#include <stdexcept>
using namespace daphne_dma;
void require(bool value) { if (!value) throw std::runtime_error("AFE DMA test failed"); }
void rejects(const std::function<void()>& f) { bool thrown = false; try { f(); } catch (const std::exception&) { thrown = true; } require(thrown); }
int main() {
  AfeRequest req{{39, 1, 17, 5}, 3, 1, 10000, 123};
  auto layout = afe_layout(req, 1024);
  require(layout.channels[0] == std::vector<uint32_t>({1, 5}));
  require(layout.channels[1] == std::vector<uint32_t>({17}));
  require(layout.bytes == std::array<uint64_t, 3>({12, 6, 6}));
  daphne_afe_dma_status s{};
  s.abi = 1; s.state = DAPHNE_AFE_COMPLETE; s.flags = DAPHNE_AFE_ALIGNED;
  s.active_routes = 7; s.guards_ok = 1; s.format = 1; s.build_id = 123;
  s.captured_ticks = 3; s.channel_mask = layout.mask;
  for (size_t r = 0; r < 3; ++r) { s.valid_bytes[r] = layout.bytes[r]; s.transfer_bytes[r] = s.received_bytes[r] = 16; s.accepted_beats[r] = 1; s.dma_status[r] = 8; }
  validate_afe_completion(req, layout, s);
  auto bad = s; bad.guards_ok = 0; rejects([&] { validate_afe_completion(req, layout, bad); });
  bad = s; bad.received_bytes[1] = 6; rejects([&] { validate_afe_completion(req, layout, bad); });
  bad = s; bad.accepted_beats[0] = 2; rejects([&] { validate_afe_completion(req, layout, bad); });
  bad = s; bad.channel_mask ^= 1; rejects([&] { validate_afe_completion(req, layout, bad); });
  bad = s; bad.hardware_error = 1; rejects([&] { validate_afe_completion(req, layout, bad); });
  bad = s; bad.state = DAPHNE_AFE_QUARANTINED; rejects([&] { validate_afe_completion(req, layout, bad); });
  req.channels = {1, 1}; rejects([&] { afe_layout(req, 1024); });
  req.channels = {40}; rejects([&] { afe_layout(req, 1024); });
  req.channels = {}; rejects([&] { afe_layout(req, 1024); });
  req.channels = {1}; req.length = 0xffffffff; req.count = 2; rejects([&] { afe_layout(req, UINT64_MAX); });
  req.length = 512; req.count = 1; rejects([&] { afe_layout(req, 1023); });
  req.channels.clear(); for (uint32_t ch = 0; ch < 40; ++ch) req.channels.push_back(ch);
  req.length = 100000; req.count = 10;
  require(afe_layout(req, 80000000).bytes == std::array<uint64_t, 3>({32000000, 32000000, 16000000}));
  std::cout << "AFE DMA layout/completion tests passed\n";
}
