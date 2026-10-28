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
#include <deque>
#include <condition_variable>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"
#include "server_controller/afe_readback_policy.hpp"
#include "../../dma/afe_capture.hpp"

class Daphne;
namespace daphne_sc {

struct DmaServiceOptions {
  AfeReadbackPolicy afe_readback_policy = AfeReadbackPolicy::kStrict;
  uint64_t maximum_job_bytes = 64ULL << 20;
  uint32_t maximum_waveforms = 256;
  uint32_t maximum_fragment_bytes = 1U << 20;
  uint32_t lease_ms = 30000;
  uint64_t maximum_scan_ticks = 1000000000;
  uint64_t maximum_ring_bytes = 448ULL << 20;
  uint32_t period_ticks = 8192;
  uint32_t cleanup_timeout_ms = 10000;
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
  void invalidate(bool unconfigured = false, uint32_t afe_mask = 31);
  void configured(const daphne::ConfigureRequest&);
  daphne::AcquisitionCapabilitiesResponse capabilities(uint32_t maximum_revision = 0) const;
 private:
  void start(const daphne::DmaAcquireRequest&, const std::string&, daphne::DmaJobResponse&);
  void start_persistent(const daphne::DmaAcquireRequest&, const std::string&, daphne::DmaJobResponse&);
  void read_persistent(const daphne::DmaReadRequest&, daphne::DmaReadResponse&);
  void ack_persistent(const daphne::DmaControlRequest&);
  void scan(const daphne::AfeDelaySweepRequest&, const std::string&, daphne::DmaJobResponse&);
  void status(uint64_t, const std::string&, daphne::DmaJobResponse&);
  void read(const daphne::DmaReadRequest&, const std::string&, daphne::DmaReadResponse&);
  void control(const daphne::DmaControlRequest&, const std::string&, daphne::DmaJobResponse&);
  void fill_status(daphne::DmaJobResponse&) const;
  void check_owner(uint64_t, const std::string&);
  void new_job(const std::string&);
  void check_frontend(const std::vector<uint32_t>&, bool calibration, bool force_acquisition = false);
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
  std::array<uint64_t, 5> generations_{};
  uint64_t job_id_ = 0;
  std::string owner_, message_;
  daphne::DmaJobState state_ = daphne::DMA_JOB_IDLE;
  uint32_t samples_ = 0, expected_ = 0, completed_ = 0, read_sequence_ = 0;
  bool quarantine_ = false;
  bool force_acquisition_ = false;
  bool triggered_available_ = false;
  daphne::DmaCaptureMode capture_mode_ = daphne::DMA_CAPTURE_FINITE;
  daphne::DmaTriggerSource trigger_source_ = daphne::DMA_TRIGGER_SOFTWARE;
  daphne::DmaCapturePhase phase_ = daphne::DMA_PHASE_IDLE;
  uint32_t pretrigger_ = 0;
  uint64_t job_timeout_ms_ = 0;
  std::chrono::steady_clock::time_point lease_;
  std::vector<daphne_dma::AfeCapture> captures_;
  std::vector<std::array<uint32_t, 3>> read_ticks_;
  daphne::AfeDelaySweepResponse scan_result_;
  struct StagedEvent { daphne_dma::AfeCapture capture; std::array<uint32_t, 3> read_ticks{}; };
  std::deque<StagedEvent> staged_;
  std::condition_variable credit_;
  daphne_afe_session_caps session_caps_{};
  daphne_afe_session_status session_status_{};
  uint64_t target_ = 0, staged_total_ = 0, acknowledged_ = 0, delivered_ = 0;
  uint64_t staged_bytes_ = 0, fragment_sequence_ = 0;
  uint64_t staging_copy_ns_ = 0;
  bool producer_closed_ = false;
  static constexpr uint32_t staging_event_limit_ = 16;
};

// Physical-pattern scan, using the same capture engine as normal acquisition.
daphne::AfeDelaySweepResponse run_dma_eye_scan(
    Daphne&, daphne_dma::AfeCaptureEngine&, const GatewareIdentity&,
    const DmaServiceOptions&, const daphne::AfeDelaySweepRequest&,
    const std::atomic<bool>& cancel);

} // namespace daphne_sc
