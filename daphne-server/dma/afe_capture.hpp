#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <functional>
#include <string>
#include <stdexcept>
#include <vector>

#include "../kernel/daphne-afe-dma/daphne_afe_dma_uapi.h"

namespace daphne_dma {

struct AfeRequest {
  std::vector<uint32_t> channels;
  uint32_t length = 0;
  uint32_t count = 1;
  uint32_t timeout_ms = 10000;
  uint32_t build_id = 0;
};
struct AfeLayout {
  uint64_t mask = 0;
  std::array<std::vector<uint32_t>, 3> channels;
  std::array<uint64_t, 3> bytes{};
  uint64_t ticks = 0;
  uint64_t total_bytes = 0;
};
struct AfeCapture {
  AfeLayout layout;
  daphne_afe_dma_status status{};
  std::array<std::string, 3> raw;
  bool triggered = false;
  daphne_afe_trigger_status trigger{};
};

enum class TriggerPhase { preparing, history, waiting, capturing, finalizing, reading };
using TriggerProgress = std::function<void(TriggerPhase)>;
struct AfeTriggerRequest {
  AfeRequest capture;
  uint32_t pretrigger = 0, source = 0, period_ticks = 8192;
};
struct AfeTriggerLayout {
  AfeLayout waveform;
  uint32_t ring_ticks = 0;
  uint64_t allocation_bytes = 0;
};
AfeTriggerLayout afe_trigger_layout(const AfeTriggerRequest&, uint64_t maximum_waveform_bytes,
                                    uint64_t maximum_ring_bytes);
void validate_afe_trigger_completion(const AfeTriggerRequest&, const AfeTriggerLayout&,
                                     const daphne_afe_trigger_status&);

// Injectable UAPI boundary: mutable ioctls are attempted once, never retried
// after EINTR with an unknown state. EAGAIN is specific to software trigger.
class AfeTriggerBackend {
 public:
  virtual ~AfeTriggerBackend() = default;
  virtual void prepare(const daphne_afe_trigger_config&) = 0;
  virtual void arm() = 0;
  virtual bool software_trigger() = 0;
  virtual daphne_afe_trigger_status status() = 0;
  virtual void wait() = 0;
  virtual std::string read_route(uint32_t, uint64_t, const std::atomic<bool>&) = 0;
  virtual void stop() = 0;
};
class AfeTriggeredSession {
 public:
  virtual ~AfeTriggeredSession() = default;
  virtual AfeCapture next(const std::atomic<bool>&, const TriggerProgress&) = 0;
  virtual void finish() = 0;
};
std::unique_ptr<AfeTriggeredSession> make_triggered_session(
    const AfeTriggerRequest&, uint64_t waveform_limit, uint64_t ring_limit,
    std::unique_ptr<AfeTriggerBackend>);

AfeLayout afe_layout(const AfeRequest& request, uint64_t maximum_bytes);
void validate_afe_completion(const AfeRequest& request, const AfeLayout& layout,
                             const daphne_afe_dma_status& status);

// Injectable boundary for tests. The server supplies the readiness/alignment
// permission; a public RPC cannot assert that the frontend is aligned.
class AfeCaptureEngine {
 public:
  virtual ~AfeCaptureEngine() = default;
  virtual AfeCapture capture(const AfeRequest&, const std::atomic<bool>& cancel) = 0;
  virtual bool supports_triggered() const { return false; }
  virtual std::unique_ptr<AfeTriggeredSession> open_triggered(const AfeTriggerRequest&, uint64_t) {
    throw std::runtime_error("TRIGGERED_UNAVAILABLE: capture engine has no triggered session");
  }
};
std::unique_ptr<AfeCaptureEngine> make_linux_afe_engine(
    uint64_t maximum_bytes, const std::string& device = "/dev/daphne-afe-dma");
void verify_linux_afe_idle(const std::string& device = "/dev/daphne-afe-dma");

} // namespace daphne_dma
