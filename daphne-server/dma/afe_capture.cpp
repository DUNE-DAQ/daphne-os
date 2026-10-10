#include "afe_capture.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <poll.h>
#include <stdexcept>
#include <sys/ioctl.h>
#include <unistd.h>

namespace daphne_dma {

AfeLayout afe_layout(const AfeRequest& req, uint64_t maximum_bytes) {
  if (req.channels.empty() || !req.length || !req.count)
    throw std::invalid_argument("DMA requires channels and nonzero L/count");
  if (req.timeout_ms < 10 || req.timeout_ms > 600000)
    throw std::invalid_argument("DMA timeout must be in 10..600000 ms");
  AfeLayout result;
  result.ticks = uint64_t(req.length) * req.count;
  if (result.ticks > std::numeric_limits<uint32_t>::max())
    throw std::invalid_argument("DMA tick count exceeds the controller ABI");
  for (const auto ch : req.channels) {
    if (ch >= 40 || (result.mask & (uint64_t(1) << ch)))
      throw std::invalid_argument("DMA channels must be unique canonical IDs 0..39");
    result.mask |= uint64_t(1) << ch;
    result.channels[ch / 16].push_back(ch);
  }
  for (size_t r = 0; r < 3; ++r) {
    std::sort(result.channels[r].begin(), result.channels[r].end());
    result.bytes[r] = result.ticks * result.channels[r].size() * 2;
    if (result.bytes[r] > (256ULL << 20))
      throw std::invalid_argument("DMA route exceeds the driver limit");
    result.total_bytes += result.bytes[r];
  }
  if (result.total_bytes > maximum_bytes)
    throw std::invalid_argument("DMA request exceeds the advertised byte budget");
  return result;
}

void validate_afe_completion(const AfeRequest& req, const AfeLayout& layout,
                             const daphne_afe_dma_status& s) {
  uint32_t routes = 0;
  for (size_t r = 0; r < 3; ++r) if (layout.bytes[r]) routes |= 1U << r;
  if (s.abi != DAPHNE_AFE_DMA_ABI || s.state != DAPHNE_AFE_COMPLETE ||
      s.error || s.hardware_error || !s.guards_ok || s.format != 1 ||
      s.build_id != req.build_id || s.channel_mask != layout.mask ||
      s.captured_ticks != layout.ticks || s.active_routes != routes ||
      s.flags != DAPHNE_AFE_ALIGNED)
    throw std::runtime_error("DMA completion failed ABI/count/identity/guard validation");
  // The kernel validates callback results and residue before COMPLETE.
  for (size_t r = 0; r < 3; ++r) {
    const uint64_t transfer = (layout.bytes[r] + 15) & ~uint64_t(15);
    if (s.valid_bytes[r] != layout.bytes[r] || s.transfer_bytes[r] != transfer ||
        s.received_bytes[r] != transfer || s.accepted_beats[r] != transfer / 16 ||
        (layout.bytes[r] && ((s.dma_status[r] & 0x770U) || !(s.dma_status[r] & 8U))))
      throw std::runtime_error("DMA route byte/beat/status mismatch");
  }
}

namespace {
void checked_ioctl(int fd, unsigned long command, void* arg = nullptr) {
  int rc;
  do { rc = ::ioctl(fd, command, arg); } while (rc < 0 && errno == EINTR);
  if (rc < 0) throw std::runtime_error(std::string("AFE DMA ioctl: ") + std::strerror(errno));
}
daphne_afe_dma_status status(int fd) {
  daphne_afe_dma_status s{};
  checked_ioctl(fd, DAPHNE_AFE_STATUS, &s);
  return s;
}
void abort_and_prove_halt(int fd) {
  checked_ioctl(fd, DAPHNE_AFE_ABORT);
  const auto s = status(fd);
  if (s.state == DAPHNE_AFE_QUARANTINED)
    throw std::runtime_error("DMA_QUARANTINED: do not unload the FPGA overlay");
  for (size_t r = 0; r < 3; ++r)
    if (!(s.dma_status[r] & 1U) || (s.dma_control[r] & 5U))
      throw std::runtime_error("DMA_QUARANTINED: halt unproven; do not unload the FPGA overlay");
}
class LinuxAfeEngine final : public AfeCaptureEngine {
 public:
  LinuxAfeEngine(uint64_t limit, std::string device) : limit_(limit), device_(std::move(device)) {}
  AfeCapture capture(const AfeRequest& req, const std::atomic<bool>& cancel) override {
    static_assert(sizeof(daphne_afe_dma_config) == 32, "AFE config UAPI layout");
    static_assert(sizeof(daphne_afe_dma_status) == 208, "AFE status UAPI layout");
    AfeCapture result;
    result.layout = afe_layout(req, limit_);
    if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
    const int fd = ::open(device_.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) throw std::runtime_error(std::string("open ") + device_ + ": " + std::strerror(errno));
    bool prepared = false;
    try {
      daphne_afe_dma_config cfg{};
      cfg.abi = DAPHNE_AFE_DMA_ABI;
      cfg.flags = DAPHNE_AFE_ALIGNED;
      cfg.length = req.length; cfg.count = req.count; cfg.timeout_ms = req.timeout_ms;
      cfg.expected_build_id = req.build_id; cfg.channel_mask = result.layout.mask;
      // PREPARE may partially claim resources before failing. The kernel
      // performs its own failure cleanup; ABORT is still required on close.
      prepared = true;
      checked_ioctl(fd, DAPHNE_AFE_PREPARE, &cfg);
      if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
      checked_ioctl(fd, DAPHNE_AFE_START);
      const auto deadline = std::chrono::steady_clock::now() +
          std::chrono::milliseconds(req.timeout_ms + 2000);
      for (;;) {
        if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
        result.status = status(fd);
        if (result.status.state != DAPHNE_AFE_RUNNING) break;
        if (std::chrono::steady_clock::now() >= deadline)
          throw std::runtime_error("DMA userspace watchdog expired");
        pollfd pfd{fd, POLLIN | POLLERR | POLLHUP, 0};
        if (::poll(&pfd, 1, 20) < 0 && errno != EINTR)
          throw std::runtime_error("DMA poll failed");
      }
      validate_afe_completion(req, result.layout, result.status);
      for (uint32_t r = 0; r < 3; ++r) {
        if (!result.layout.bytes[r]) continue;
        checked_ioctl(fd, DAPHNE_AFE_SELECT_ROUTE, &r);
        auto& raw = result.raw[r];
        raw.resize(static_cast<size_t>(result.layout.bytes[r]));
        size_t offset = 0;
        while (offset < raw.size()) {
          if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
          const auto n = ::read(fd, raw.data() + offset,
                                std::min<size_t>(raw.size() - offset, 1U << 20));
          if (n < 0 && errno == EINTR) continue;
          if (n <= 0) throw std::runtime_error("DMA short/failed payload read");
          offset += static_cast<size_t>(n);
        }
      }
      abort_and_prove_halt(fd);
      prepared = false;
      ::close(fd);
      return result;
    } catch (const std::exception& error) {
      std::string message = error.what();
      if (prepared) {
        try { checked_ioctl(fd, DAPHNE_AFE_ABORT); }
        catch (const std::exception& abort_error) { message += "; DMA_QUARANTINED: ABORT failed: "; message += abort_error.what(); }
        try { if (status(fd).state == DAPHNE_AFE_QUARANTINED) message += "; DMA_QUARANTINED: do not unload overlay"; }
        catch (...) { message += "; DMA_QUARANTINED: status unavailable"; }
      }
      ::close(fd); // The driver retains quarantined buffers independently.
      throw std::runtime_error(message);
    }
  }
 private:
  uint64_t limit_;
  std::string device_;
};
} // namespace

std::unique_ptr<AfeCaptureEngine> make_linux_afe_engine(uint64_t bytes, const std::string& device) {
  return std::make_unique<LinuxAfeEngine>(bytes, device);
}
void verify_linux_afe_idle(const std::string& device) {
  const int fd = ::open(device.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) throw std::runtime_error("DMA idle not proven: driver unavailable or owned");
  try {
    const auto s = status(fd);
    if (s.abi != 1 || s.state == DAPHNE_AFE_QUARANTINED || s.state == DAPHNE_AFE_RUNNING ||
        s.state == DAPHNE_AFE_PREPARED || (s.hardware_status & 1))
      throw std::runtime_error("DMA_QUARANTINED: idle not proven; keep overlay loaded");
    for (size_t r = 0; r < 3; ++r)
      if (!(s.dma_status[r] & 1) || (s.dma_control[r] & 5))
        throw std::runtime_error("DMA_QUARANTINED: halt not proven; keep overlay loaded");
  } catch (...) { ::close(fd); throw; }
  ::close(fd);
}
} // namespace daphne_dma
