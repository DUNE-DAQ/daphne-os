#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
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
};

AfeLayout afe_layout(const AfeRequest& request, uint64_t maximum_bytes);
void validate_afe_completion(const AfeRequest& request, const AfeLayout& layout,
                             const daphne_afe_dma_status& status);

// Injectable boundary for tests. The server supplies the readiness/alignment
// permission; a public RPC cannot assert that the frontend is aligned.
class AfeCaptureEngine {
 public:
  virtual ~AfeCaptureEngine() = default;
  virtual AfeCapture capture(const AfeRequest&, const std::atomic<bool>& cancel) = 0;
};
std::unique_ptr<AfeCaptureEngine> make_linux_afe_engine(
    uint64_t maximum_bytes, const std::string& device = "/dev/daphne-afe-dma");

} // namespace daphne_dma
