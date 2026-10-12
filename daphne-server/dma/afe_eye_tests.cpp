#include "afe_eye.hpp"
#include <iostream>
#include <cstdlib>
void require(bool b) { if (!b) std::exit(1); }
int main() {
  using namespace daphne_dma;
  AfeRequest req{{32,33,34,35,36,37,38,39}, 32768, 2, 10000, 42};
  AfeCapture capture; capture.layout = afe_layout(req, 64ULL << 20);
  auto& raw = capture.raw[2]; raw.resize(capture.layout.bytes[2]);
  for (uint64_t t = 0; t < capture.layout.ticks; ++t) for (size_t l = 0; l < 8; ++l) {
    uint16_t value = uint16_t((t + l) * 4);
    raw[(t * 8 + l) * 2] = value; raw[(t * 8 + l) * 2 + 1] = value >> 8;
  }
  auto p = analyze_physical_ramp(capture, req, 120, 3);
  require(p.failures[7] == 0 && p.boundary[7] == 0 && p.low[7] == 0); // CH39 follows the same rules.
  raw[32768 * 16 + 14] ^= 1;
  p = analyze_physical_ramp(capture, req, 120, 3);
  require(p.boundary[7] == 1 && p.low[7] == 1 && p.failures[7] == 1);
  std::vector<EyePoint> points{{100,3}, {104,3}, {108,3}, {112,3}, {116,3}};
  points[0].failures[0] = 1; points[4].low[7] = 1;
  auto best = choose_eye(points, false);
  require(best.mask == 255 && best.first == 104 && best.last == 112 && best.tap == 108);
  for (auto& x : points) x.boundary[7] = 1;
  require(choose_eye(points, false).mask == 0);
  require(choose_eye(points, true).mask == 127);
  std::vector<EyeChoice> candidates{{2,0,200,100,255}, {5,40,160,100,255}, {3,0,300,148,127}};
  unsigned checks = 0;
  best = choose_verified_eye(candidates, [&](const EyeChoice& c) {
    ++checks; EyePoint final;
    if (c.slip == 2) final.failures[0] = 128; // Short search missed a periodic carry error.
    return final;
  });
  require(best.slip == 5 && best.mask == 255 && checks == 2);
  // Partial admission never accepts an error in an approved lane.
  checks = 0;
  best = choose_verified_eye({{2,0,200,100,127}}, [&](const EyeChoice&) {
    ++checks; EyePoint final; final.low[7] = 100; return final;
  });
  require(best.mask == 127 && checks == 1);
  bool rejected = false;
  try {
    choose_verified_eye({{2,0,200,100,127}}, [](const EyeChoice&) {
      EyePoint final; final.low[0] = 1; return final;
    });
  } catch (const std::runtime_error& e) {
    const std::string message = e.what();
    rejected = message.find("lane=0") != std::string::npos && message.find("low=1") != std::string::npos;
  }
  require(rejected);
  std::cout << "AFE physical eye tests passed\n";
}
