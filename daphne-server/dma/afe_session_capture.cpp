#include "afe_capture.hpp"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <thread>
#include <unistd.h>

namespace daphne_dma {
namespace {
void session_ioctl(int fd, unsigned long op, void* arg = nullptr) {
  if (::ioctl(fd, op, arg) < 0)
    throw std::runtime_error("Session ioctl errno=" + std::to_string(errno) + ": " + std::strerror(errno));
}
void healthy(const daphne_afe_session_status& s, uint64_t session) {
  if (s.abi != 1 || s.session != session || s.state == DAPHNE_SESSION_QUARANTINED)
    throw std::runtime_error("DMA_QUARANTINED: session identity/idle proof unavailable");
  if (s.error || s.hardware_error || s.state == DAPHNE_SESSION_ERROR)
    throw std::runtime_error("Persistent DMA error=" + std::to_string(s.error));
}
class Session final : public AfePersistentSession {
 public:
  Session(const AfePersistentRequest& r, uint64_t limit, std::unique_ptr<AfeSessionBackend> backend)
      : request_(r), backend_(std::move(backend)) {
    layout_ = afe_layout(r.trigger.capture, limit);
    if (!r.target || r.trigger.capture.count != 1 || r.trigger.pretrigger >= r.trigger.capture.length ||
        r.trigger.source > 2 || r.trigger.period_ticks != 8192)
      throw std::invalid_argument("Invalid persistent session geometry/N/source");
    daphne_afe_session_config c{};
    c.abi = 1; c.flags = (r.pattern ? DAPHNE_AFE_PATTERN : DAPHNE_AFE_ALIGNED) |
        (r.trigger.source == 0 ? DAPHNE_AFE_SESSION_AUTO : 0);
    c.length = r.trigger.capture.length; c.pretrigger = r.trigger.pretrigger;
    c.period_ticks = r.trigger.period_ticks; c.source = r.trigger.source;
    c.expected_build_id = r.trigger.capture.build_id; c.channel_mask = layout_.mask;
    c.target_events = r.target; c.budget_bytes = r.ring_budget;
    c.trigger_timeout_ms = r.trigger.capture.timeout_ms; c.pressure_timeout_ms = r.pressure_timeout_ms;
    // Driver normalizes ring size and slots; N never controls reservation size.
    try {
      config_ = backend_->prepare(c);
      if (config_.abi != 1 || !config_.session || config_.slots < 2 || config_.slots > 32 ||
          (config_.slots & (config_.slots - 1)) || config_.length != c.length || config_.pretrigger != c.pretrigger ||
          config_.source != c.source || config_.channel_mask != c.channel_mask || config_.target_events != c.target_events ||
          config_.flags != c.flags || config_.period_ticks != c.period_ticks || config_.expected_build_id != c.expected_build_id)
        throw std::runtime_error("Invalid normalized session config");
      backend_->start();
    } catch (...) {
      // PREPARE/START can partially succeed. Close invokes kernel cleanup.
      backend_->close(); throw;
    }
  }
  bool next(AfeCapture& out, const std::atomic<bool>& cancel) override {
    if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
    if (delivered_ == request_.target) return false;
    const auto s = status(); healthy(s, config_.session);
    daphne_afe_session_event e{};
    if (!backend_->get(e)) return false;
    // The ID stays owned on every exceptional path until cancellation/close.
    if (e.id.reserved || e.reserved || e.hardware_error || e.id.session != config_.session ||
        e.id.sequence != delivered_ + 1 || !e.id.generation || e.id.slot >= config_.slots ||
        e.id.slot != (e.id.sequence - 1) % config_.slots ||
        e.id.generation != (e.id.sequence - 1) / config_.slots + 1 ||
        e.channel_mask != layout_.mask || e.length != config_.length || e.pretrigger != config_.pretrigger ||
        e.source != config_.source || e.timestamp_valid > 1 || e.trigger_index < e.pretrigger ||
        e.fence_end < e.first_cursor || e.fence_end - e.first_cursor < e.length ||
        e.fence_end - e.first_cursor >= uint64_t(e.length) + config_.period_ticks ||
        e.fence_end % config_.period_ticks)
      throw std::runtime_error("Persistent event ID/window/contract mismatch");
    out = {}; out.layout = layout_; out.event = e; out.status.format = 1;
    const auto copy_begin = std::chrono::steady_clock::now();
    for (uint32_t r = 0; r < 3; ++r) {
      if (e.valid_bytes[r] != layout_.bytes[r]) throw std::runtime_error("Persistent route size mismatch");
      auto& raw = out.raw[r]; raw.resize(layout_.bytes[r]);
      for (uint64_t offset = 0; offset < raw.size();) {
        if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
        const uint32_t count = std::min<uint64_t>(raw.size() - offset, DAPHNE_AFE_SESSION_READ_MAX);
        backend_->read(e.id, r, offset, raw.data() + offset, count); offset += count;
      }
    }
    out.copy_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - copy_begin).count();
    // No DDR pointer escapes READ. RELEASE after the complete bounded copy.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(request_.cleanup_timeout_ms);
    while (!backend_->release(e.id)) {
      healthy(status(), config_.session);
      if (cancel.load()) throw std::runtime_error("DMA_CANCELLED");
      if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("Session RELEASE busy timeout");
      backend_->wait();
    }
    ++delivered_; return true;
  }
  daphne_afe_session_status status() override {
    const auto s = backend_->status();
    if (s.abi != 1 || s.session != config_.session || s.target_events != request_.target || s.slots != config_.slots ||
        s.state > DAPHNE_SESSION_QUARANTINED || s.released > s.delivered || s.delivered > s.completed ||
        s.completed > s.accepted || s.accepted > request_.target)
      throw std::runtime_error("DMA_QUARANTINED: session status identity/counters invalid");
    return s;
  }
  void finish(bool cancel) override {
    if (closed_) return;
    if (cancel) backend_->cancel();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(request_.cleanup_timeout_ms);
    for (;;) {
      const auto s = status();
      if (s.abi != 1 || s.session != config_.session || s.state == DAPHNE_SESSION_QUARANTINED)
        throw std::runtime_error("DMA_QUARANTINED: session stop unavailable");
      const bool terminal = s.state == DAPHNE_SESSION_COMPLETE || s.state == DAPHNE_SESSION_ABORTED || s.state == DAPHNE_SESSION_ERROR;
      if (terminal) {
        if (!s.guards_ok) throw std::runtime_error("DMA_QUARANTINED: session guards invalid");
        if (cancel || (s.released == request_.target && delivered_ == request_.target)) break;
      }
      if (std::chrono::steady_clock::now() >= deadline)
        throw std::runtime_error("DMA_QUARANTINED: session stop/release watchdog expired");
      backend_->wait();
    }
    backend_->close(); closed_ = true;
  }
 private:
  AfePersistentRequest request_;
  AfeLayout layout_;
  daphne_afe_session_config config_{};
  std::unique_ptr<AfeSessionBackend> backend_;
  uint64_t delivered_ = 0;
  bool closed_ = false;
};
class LinuxSessionBackend final : public AfeSessionBackend {
 public:
  explicit LinuxSessionBackend(std::string device) : device_(std::move(device)) {
    fd_ = ::open(device_.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd_ < 0) throw std::runtime_error("Open session driver: " + std::string(std::strerror(errno)));
  }
  ~LinuxSessionBackend() override { if (fd_ >= 0) ::close(fd_); }
  daphne_afe_session_config prepare(daphne_afe_session_config c) override {
    session_ioctl(fd_, DAPHNE_AFE_SESSION_PREPARE, &c); return c;
  }
  void start() override { session_ioctl(fd_, DAPHNE_AFE_SESSION_START); }
  bool get(daphne_afe_session_event& e) override {
    daphne_afe_session_batch b{}; b.abi = 1; b.capacity = 1; b.entries = reinterpret_cast<uintptr_t>(&e);
    if (::ioctl(fd_, DAPHNE_AFE_SESSION_GET, &b) < 0) {
      if (errno == EAGAIN || errno == EBUSY) return false;
      if (errno == ENODATA) throw std::runtime_error("Persistent producer completed with missing READY events");
      throw std::runtime_error("Session GET: " + std::string(std::strerror(errno)));
    }
    if (b.count != 1) throw std::runtime_error("Invalid GET count");
    return true;
  }
  void read(const daphne_afe_event_id& id, uint32_t route, uint64_t offset, char* buffer, uint32_t bytes) override {
    daphne_afe_session_read q{}; q.id = id; q.abi = 1; q.route = route; q.offset = offset;
    q.length = bytes; q.buffer = reinterpret_cast<uintptr_t>(buffer);
    session_ioctl(fd_, DAPHNE_AFE_SESSION_READ, &q);
    if (q.copied != bytes) throw std::runtime_error("Persistent DMA short read");
  }
  bool release(const daphne_afe_event_id& id) override {
    daphne_afe_session_batch b{}; b.abi = 1; b.capacity = b.count = 1; b.entries = reinterpret_cast<uintptr_t>(&id);
    if (::ioctl(fd_, DAPHNE_AFE_SESSION_RELEASE, &b) == 0) return true;
    if (errno == EBUSY) return false;
    throw std::runtime_error("Session RELEASE: " + std::string(std::strerror(errno)));
  }
  daphne_afe_session_status status() override {
    daphne_afe_session_status s{}; s.abi = 1;
    session_ioctl(fd_, DAPHNE_AFE_SESSION_STATUS, &s); return s;
  }
  void cancel() override { session_ioctl(fd_, DAPHNE_AFE_SESSION_CANCEL); }
  void wait() override {
    // HUP and IN may coexist; GET always gets a chance before termination.
    // A bounded sleep also avoids spinning on level-triggered HUP after STOP.
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  void close() override {
    if (fd_ >= 0) { const int fd = fd_; fd_ = -1; ::close(fd); }
    verify_linux_afe_idle(device_);
  }
 private:
  std::string device_; int fd_ = -1;
};
} // namespace
std::unique_ptr<AfePersistentSession> make_persistent_session(const AfePersistentRequest& r, uint64_t limit,
                                                            std::unique_ptr<AfeSessionBackend> backend) {
  return std::make_unique<Session>(r, limit, std::move(backend));
}
daphne_afe_session_caps linux_session_caps(const std::string& device) {
  daphne_afe_session_caps c{};
  const int fd = ::open(device.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) return c;
  const int rc = ::ioctl(fd, DAPHNE_AFE_SESSION_CAPS, &c); ::close(fd);
  if (rc || c.abi != 1 || (c.features & 31) != 31 || c.format != 1 ||
      c.slots < 2 || c.slots > 32 || (c.slots & (c.slots - 1)) || c.batch_max != 16 ||
      c.read_max != DAPHNE_AFE_SESSION_READ_MAX || !c.target_max) return {};
  return c;
}
std::unique_ptr<AfePersistentSession> open_linux_persistent(const AfePersistentRequest& r, uint64_t limit,
                                                          const std::string& device) {
  return make_persistent_session(r, limit, std::make_unique<LinuxSessionBackend>(device));
}
} // namespace daphne_dma
