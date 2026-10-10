#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <memory>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"
#include "../../dma/afe_capture.hpp"

class Daphne;
namespace daphne_sc {

struct DmaServiceOptions {
  uint64_t maximum_job_bytes = 64ULL << 20;
  uint32_t maximum_waveforms = 256;
  uint32_t maximum_fragment_bytes = 1U << 20;
  uint32_t lease_ms = 30000;
  uint64_t maximum_scan_ticks = 1000000000;
};

// Router-thread RPCs own the job lease. Only worker threads touch the engine.
// No worker uses the ZeroMQ socket or creates a public ALIGNED assertion.
class DmaService {
 public:
  using Guard = std::function<void(const std::vector<uint32_t>&, bool)>;
  using Scanner = std::function<daphne::AfeDelaySweepResponse(const daphne::AfeDelaySweepRequest&, const std::atomic<bool>&)>;
  DmaService(Daphne&, GatewareIdentity, DmaServiceOptions = {},
             std::unique_ptr<daphne_dma::AfeCaptureEngine> = nullptr);
  DmaService(GatewareIdentity, DmaServiceOptions, std::unique_ptr<daphne_dma::AfeCaptureEngine>, Guard, Scanner,
             std::function<void()> live_guard, std::function<bool()> device_available);
  ~DmaService();
  bool dispatch(const daphne::ControlEnvelopeV2&, const std::string& owner, std::string& out);
  void expire();
  void shutdown();
  bool busy() const;
  void verify_live() const;
  void invalidate(bool unconfigured = false);
  void configured(const daphne::ConfigureRequest&);
  daphne::AcquisitionCapabilitiesResponse capabilities() const;
 private:
  void start(const daphne::DmaAcquireRequest&, const std::string&, daphne::DmaJobResponse&);
  void scan(const daphne::AfeDelaySweepRequest&, const std::string&, daphne::DmaJobResponse&);
  void status(uint64_t, const std::string&, daphne::DmaJobResponse&);
  void read(const daphne::DmaReadRequest&, const std::string&, daphne::DmaReadResponse&);
  void control(const daphne::DmaControlRequest&, const std::string&, daphne::DmaJobResponse&);
  void fill_status(daphne::DmaJobResponse&) const;
  void check_owner(uint64_t, const std::string&);
  void new_job(const std::string&);
  void check_frontend(const std::vector<uint32_t>&, bool calibration);
  Guard guard_;
  Scanner scanner_;
  std::function<void()> live_guard_;
  std::function<bool()> device_available_;
  GatewareIdentity identity_;
  DmaServiceOptions options_;
  std::unique_ptr<daphne_dma::AfeCaptureEngine> engine_;
  mutable std::mutex mutex_;
  std::thread worker_;
  std::atomic<bool> cancel_{false};
  std::array<daphne::FrontendState, 5> states_{};
  std::array<uint32_t, 5> approved_{};
  uint64_t generation_ = 0, job_id_ = 0;
  std::string owner_, message_;
  daphne::DmaJobState state_ = daphne::DMA_JOB_IDLE;
  uint32_t samples_ = 0, expected_ = 0, completed_ = 0, read_sequence_ = 0;
  bool quarantine_ = false;
  std::chrono::steady_clock::time_point lease_;
  std::vector<daphne_dma::AfeCapture> captures_;
  std::vector<std::array<uint32_t, 3>> read_ticks_;
  daphne::AfeDelaySweepResponse scan_result_;
};

// Physical-pattern scan, using the same capture engine as normal acquisition.
daphne::AfeDelaySweepResponse run_dma_eye_scan(
    Daphne&, daphne_dma::AfeCaptureEngine&, const GatewareIdentity&,
    const DmaServiceOptions&, const daphne::AfeDelaySweepRequest&,
    const std::atomic<bool>& cancel);

} // namespace daphne_sc
