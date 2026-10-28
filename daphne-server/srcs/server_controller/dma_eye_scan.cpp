#include "server_controller/dma_service.hpp"
#include "server_controller/hardware_admission.hpp"
#include "Daphne.hpp"
#include "defines.hpp"
#include "../../dma/afe_eye.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <functional>
#include <set>
#include <stdexcept>
#include <thread>

namespace daphne_sc {
namespace {
struct Saved {
  uint32_t afe, pl, delay, slip, sync, pattern;
};
using Point = daphne_dma::EyePoint;
using Choice = daphne_dma::EyeChoice;
using daphne_dma::population;
using daphne_dma::choose_eye;
std::vector<uint32_t> taps(uint32_t first, uint32_t last, uint32_t step) {
  std::vector<uint32_t> result;
  for (auto tap = first;;) {
    result.push_back(tap); if (tap == last) break;
    tap = last - tap < step ? last : tap + step;
  }
  return result;
}
Point measure(daphne_dma::AfeCaptureEngine& engine, const daphne_dma::AfeRequest& req,
              uint32_t tap, uint32_t slip, const std::atomic<bool>& cancel) {
  return daphne_dma::analyze_physical_ramp(engine.capture(req, cancel), req, tap, slip);
}
}

daphne::AfeDelaySweepResponse run_dma_eye_scan(
    Daphne& d, daphne_dma::AfeCaptureEngine& engine, const GatewareIdentity& identity,
    const DmaServiceOptions& options, const daphne::AfeDelaySweepRequest& req,
    const std::atomic<bool>& cancel) {
  auto* fe = d.getFrontEnd(); auto* afe = d.getAfe();
  const uint32_t old_vtc = fe->getEnableDelayVtc();
  std::vector<Saved> saved;
  AfeReadbackVerifier readback(options.afe_readback_policy, "DMA eye scan");
  std::vector<uint32_t> requested;
  for (auto a : req.afes()) requested.push_back(a);
  if (requested.empty()) for (uint32_t a = 0; a < 5; ++a) requested.push_back(a);
  for (auto a : requested) {
    const auto pl = afe_definitions::AFE_board2PL_map.at(a);
    saved.push_back({a, pl, fe->getDelay(pl), fe->getBitslip(pl),
        afe->getAFEFunction(pl, "SYNC_PATTERN"), afe->getAFEFunction(pl, "TEST_PATTERN_MODES")});
  }
  bool touched = false;
  std::set<uint32_t> retained;
  auto restore = [&](bool keep) {
    // Never attempt restoration through a retired overlay. The admission
    // error supersedes cleanup rather than risking an AXI access to absent PL.
    require_live_gateware(identity, GatewareMode::kRawDma);
    std::string failures;
    auto attempt = [&](const std::function<void()>& f) {
      try { f(); } catch (const std::exception& e) { failures += std::string(e.what()) + "; "; }
    };
    for (const auto& s : saved) {
      if (!keep || !retained.count(s.afe)) {
        attempt([&] { if (fe->setDelay(s.pl, s.delay) != s.delay) throw std::runtime_error("delay restore mismatch"); });
        attempt([&] { if (fe->setBitslip(s.pl, s.slip) != s.slip) throw std::runtime_error("bitslip restore mismatch"); });
      }
      attempt([&] { readback.check(s.afe, "TEST_PATTERN_MODES restore", s.pattern,
          afe->setAFEFunction(s.pl, "TEST_PATTERN_MODES", s.pattern), "pattern restore mismatch"); });
      attempt([&] { readback.check(s.afe, "SYNC_PATTERN restore", s.sync,
          afe->setAFEFunction(s.pl, "SYNC_PATTERN", s.sync), "sync restore mismatch"); });
    }
    const auto vtc = keep && !retained.empty() ? 0U : old_vtc;
    attempt([&] { if (fe->setEnableDelayVtc(vtc) != vtc) throw std::runtime_error("VTC restore mismatch"); });
    if (!failures.empty()) throw std::runtime_error("DMA scan restoration failed: " + failures);
  };
  daphne::AfeDelaySweepResponse out;
  out.set_backend(daphne::ACQUISITION_DMA); out.set_originalvtcenable(old_vtc);
  std::string verification_diagnostics;
  const auto deadline = std::chrono::steady_clock::now() +
      std::chrono::milliseconds(req.timeout_ms() ? req.timeout_ms() : 600000);
  auto check = [&] {
    if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
    if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("DMA scan deadline expired");
    require_live_gateware(identity, GatewareMode::kRawDma);
    if (afe->getPowerState() != 1 || !fe->getDelayCtrlReady()) throw std::runtime_error("Frontend readiness lost during scan");
  };
  try {
    touched = true;
    if (fe->setEnableDelayVtc(0) != 0) throw std::runtime_error("VTC disable mismatch");
    for (const auto& s : saved) {
      check();
      readback.check(s.afe, "SYNC_PATTERN", 1, afe->setAFEFunction(s.pl, "SYNC_PATTERN", 1),
                     "Physical AFE ramp readback mismatch");
      readback.check(s.afe, "TEST_PATTERN_MODES", 7, afe->setAFEFunction(s.pl, "TEST_PATTERN_MODES", 7),
                     "Physical AFE ramp readback mismatch");
    }
    bool all_pass = true;
    for (const auto& s : saved) {
      daphne_dma::AfeRequest capture;
      for (uint32_t lane = 0; lane < 8; ++lane) capture.channels.push_back(s.afe * 8 + lane);
      capture.length = req.numberofsamples(); capture.count = req.numberofwaveforms();
      capture.build_id = identity.build_id; capture.timeout_ms = 10000;
      auto* result = out.add_afes(); result->set_afe(s.afe);
      result->set_originaldelay(s.delay); result->set_bitslip(s.slip);
      Choice best;
      std::vector<Choice> candidates;
      auto position = [&](uint32_t tap, uint32_t slip) {
        check();
        if (fe->setDelay(s.pl, tap) != tap || fe->setBitslip(s.pl, slip) != slip)
          throw std::runtime_error("DMA timing readback mismatch");
        if (req.settletimeus()) std::this_thread::sleep_for(std::chrono::microseconds(req.settletimeus()));
      };
      for (uint32_t slip = 0; slip < 16; ++slip) {
        const auto coarse_taps = taps(req.firsttap(), req.lasttap(), req.coarse_step() ? req.coarse_step() : 16);
        std::vector<Point> coarse;
        for (auto tap : coarse_taps) { position(tap, slip); coarse.push_back(measure(engine, capture, tap, slip, cancel)); }
        const auto window = choose_eye(coarse, req.accept_partial_config());
        // Refine the full range on a miss, so a narrow eye between coarse taps
        // is not classified as a failed lane. Work was budgeted before MMIO.
        const uint32_t padding = req.coarse_step() ? req.coarse_step() : 16;
        const uint32_t first = window.mask && window.first > req.firsttap() + padding ? window.first - padding : req.firsttap();
        const uint32_t last = window.mask && window.last + padding < req.lasttap() ? window.last + padding : req.lasttap();
        std::vector<Point> fine;
        for (auto tap : taps(first, last, req.tapstep())) {
          position(tap, slip); fine.push_back(measure(engine, capture, tap, slip, cancel));
          const auto& p = fine.back(); auto* point = result->add_points();
          point->set_tap(tap); point->set_bitslip(slip);
          point->set_transitionsperchannel(uint64_t(capture.count) * (capture.length - 1));
          point->set_boundary_transitions_per_channel(capture.count - 1);
          for (size_t lane = 0; lane < 8; ++lane) {
            point->add_channelfailures(p.failures[lane]); point->add_low_bit_failures(p.low[lane]);
            point->add_boundary_failures(p.boundary[lane]);
          }
        }
        const auto candidate = choose_eye(fine, req.accept_partial_config());
        if (candidate.mask) candidates.push_back(candidate);
        if (population(candidate.mask) > population(best.mask) ||
            (population(candidate.mask) == population(best.mask) && candidate.last - candidate.first > best.last - best.first))
          best = candidate;
      }
      if (!best.mask) { all_pass = false; continue; }
      if (req.apply_best() && !req.skip_ramp_verification()) {
        auto verify = capture; verify.length = req.verification_samples() ? req.verification_samples() : 32768; verify.count = 1;
        daphne_dma::afe_layout(verify, options.maximum_job_bytes);
        try {
          best = daphne_dma::choose_verified_eye(candidates, [&](const Choice& candidate) {
            position(candidate.tap, candidate.slip);
            return measure(engine, verify, candidate.tap, candidate.slip, cancel);
          }, [&](const Choice& candidate, const Point& point) {
            verification_diagnostics += " AFE" + std::to_string(s.afe) + " rejected slip=" +
                std::to_string(candidate.slip) + " tap=" + std::to_string(candidate.tap);
            for (size_t lane = 0; lane < 8; ++lane) {
              if (!(candidate.mask & (1U << lane))) continue;
              if (point.failures[lane] || point.low[lane] || point.boundary[lane])
                verification_diagnostics += " CH" + std::to_string(s.afe * 8 + lane) +
                    " delta=" + std::to_string(point.failures[lane]) + " low=" +
                    std::to_string(point.low[lane]) + " boundary=" + std::to_string(point.boundary[lane]);
            }
            verification_diagnostics += ";";
          });
        } catch (const std::exception& error) {
          throw std::runtime_error("AFE" + std::to_string(s.afe) + " verification_samples=" +
                                   std::to_string(verify.length) + ": " + error.what());
        }
        retained.insert(s.afe); result->set_applied(true);
      }
      if (req.apply_best() && req.skip_ramp_verification()) {
        position(best.tap, best.slip);
        retained.insert(s.afe); result->set_applied(true);
        result->set_ramp_verification_skipped(true);
      }
      result->set_selected_delay(best.tap); result->set_bitslip(best.slip);
      result->set_first_passing_tap(best.first); result->set_last_passing_tap(best.last);
      result->set_approved_lane_mask(best.mask);
    }
    restore(req.apply_best()); touched = false;
    out.set_success(all_pass);
    out.set_message(all_pass ? "Physical DMA eye measured; applied candidates verified and AFE patterns restored" :
        "One or more AFEs have no passing eye; failed lanes remain unavailable");
    if (!verification_diagnostics.empty()) out.set_message(out.message() + "; long verification:" + verification_diagnostics);
    if (req.skip_ramp_verification() && req.apply_best())
      out.set_message("Timing candidates applied without final ramp verification; use force acquisition for unverified AFEs");
    out.set_message(readback.summary() + out.message());
    return out;
  } catch (const std::exception& e) {
    std::string message = e.what();
    if (touched && message.find("QUARANTINED") == std::string::npos)
      try { restore(false); } catch (const std::exception& cleanup) { message += "; "; message += cleanup.what(); }
    throw std::runtime_error(readback.summary() + message);
  }
}
} // namespace daphne_sc
