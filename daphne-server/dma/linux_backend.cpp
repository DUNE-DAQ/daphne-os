#include "capture.hpp"
#include <cerrno>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <system_error>
#include <unistd.h>

namespace daphne_dma {
static_assert(sizeof(daphne_dma_config) == 32, "DMA config ABI layout");
static_assert(sizeof(daphne_dma_status) == 112, "DMA status ABI layout");
static_assert(sizeof(daphne_dma_block_info) == 32, "DMA block ABI layout");
namespace {
class LinuxBackend final : public Backend {
 public:
  explicit LinuxBackend(uint32_t path) {
    if (path > 2) throw std::invalid_argument("invalid DMA route");
    const auto name = "/dev/daphne-dma" + std::to_string(path);
    fd_ = ::open(name.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd_ < 0) throw std::system_error(errno, std::generic_category(), "open " + name);
  }
  ~LinuxBackend() override { ::close(fd_); }
  void prepare(const daphne_dma_config& c) override {
    call(DAPHNE_DMA_PREPARE, const_cast<daphne_dma_config*>(&c));
  }
  void start() override { call(DAPHNE_DMA_START); }
  void stop() override { call(DAPHNE_DMA_STOP); }
  void abort() override { call(DAPHNE_DMA_ABORT); }
  daphne_dma_status status() override {
    daphne_dma_status s{};
    call(DAPHNE_DMA_STATUS, &s);
    return s;
  }
  daphne_dma_block_info block(uint32_t index) override {
    daphne_dma_block_info b{};
    b.abi = DAPHNE_DMA_ABI;
    b.index = index;
    call(DAPHNE_DMA_BLOCK, &b);
    return b;
  }
  size_t read(void* target, size_t size) override {
    ssize_t n;
    do { n = ::read(fd_, target, size); } while (n < 0 && errno == EINTR);
    if (n < 0) throw std::system_error(errno, std::generic_category(), "DMA read");
    return size_t(n);
  }
 private:
  int fd_ = -1;
  void call(unsigned long op, void* data = nullptr) {
    // Mutating ioctl is not retried: it may already have committed its effect.
    if (::ioctl(fd_, op, data) < 0)
      throw std::system_error(errno, std::generic_category(), "DMA ioctl " + std::to_string(op));
  }
};
}
std::unique_ptr<Backend> linux_backend(uint32_t path) {
  return std::make_unique<LinuxBackend>(path);
}
}
