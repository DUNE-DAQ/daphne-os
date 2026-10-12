#pragma once
#include "afe_capture.hpp"
#include <array>
#include <algorithm>
#include <sstream>
#include <functional>
#include <stdexcept>

namespace daphne_dma {
struct EyePoint {
  uint32_t tap = 0, slip = 0;
  std::array<uint64_t, 8> failures{}, low{}, boundary{};
};
struct EyeChoice { uint32_t slip = 0, first = 0, last = 0, tap = 0, mask = 0; };
inline unsigned population(uint32_t mask) {
  unsigned n = 0; for (; mask; mask &= mask - 1) ++n; return n;
}
inline EyeChoice choose_eye(const std::vector<EyePoint>& points, bool partial) {
  EyeChoice best;
  for (size_t first = 0; first < points.size(); ++first) {
    uint32_t mask = 255;
    for (size_t last = first; last < points.size(); ++last) {
      for (size_t lane = 0; lane < 8; ++lane)
        if (points[last].failures[lane] || points[last].low[lane] || points[last].boundary[lane]) mask &= ~(1U << lane);
      if (!mask || (!partial && mask != 255)) break;
      const auto width = points[last].tap - points[first].tap;
      if (population(mask) > population(best.mask) ||
          (population(mask) == population(best.mask) && width > best.last - best.first))
        best = {points[first].slip, points[first].tap, points[last].tap,
                points[first + (last - first) / 2].tap, mask};
    }
  }
  return best;
}
template<class Verify>
inline EyeChoice choose_verified_eye(std::vector<EyeChoice> candidates, Verify verify,
    std::function<void(const EyeChoice&, const EyePoint&)> rejected = {}) {
  std::stable_sort(candidates.begin(), candidates.end(), [](const auto& a, const auto& b) {
    if (population(a.mask) != population(b.mask)) return population(a.mask) > population(b.mask);
    return a.last - a.first > b.last - b.first;
  });
  std::ostringstream failures;
  for (const auto& candidate : candidates) {
    if (!candidate.mask) continue;
    const auto point = verify(candidate);
    bool passed = true;
    std::ostringstream detail;
    for (size_t lane = 0; lane < 8; ++lane) {
      if (!(candidate.mask & (1U << lane))) continue;
      if (point.failures[lane] || point.low[lane] || point.boundary[lane]) {
        passed = false;
        detail << " lane=" << lane << " delta=" << point.failures[lane]
               << " low=" << point.low[lane] << " boundary=" << point.boundary[lane];
      }
    }
    if (passed) return candidate;
    if (rejected) rejected(candidate, point);
    failures << " [slip=" << candidate.slip << " tap=" << candidate.tap << detail.str() << ']';
  }
  throw std::runtime_error("Final physical ramp verification failed for every candidate:" + failures.str());
}
inline EyePoint analyze_physical_ramp(const AfeCapture& c, const AfeRequest& req, uint32_t tap, uint32_t slip) {
  const auto route = req.channels.at(0) / 16;
  const auto& raw = c.raw.at(route);
  if (req.channels.size() != 8 || c.layout.channels.at(route) != req.channels ||
      raw.size() != uint64_t(req.length) * req.count * 16)
    throw std::runtime_error("DMA calibration route/channel layout mismatch");
  EyePoint point{tap, slip}; std::array<uint16_t, 8> previous{};
  for (uint64_t tick = 0; tick < uint64_t(req.length) * req.count; ++tick)
    for (size_t lane = 0; lane < 8; ++lane) {
      const auto offset = (tick * 8 + lane) * 2;
      const uint16_t value = uint8_t(raw[offset]) | (uint16_t(uint8_t(raw[offset + 1])) << 8);
      if (value & 3) ++point.low[lane];
      if (tick && uint16_t(value - previous[lane]) != 4) {
        if (tick % req.length == 0) ++point.boundary[lane]; else ++point.failures[lane];
      }
      previous[lane] = value;
    }
  return point;
}
}
