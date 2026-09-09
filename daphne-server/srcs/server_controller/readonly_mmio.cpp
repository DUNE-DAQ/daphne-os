#include "server_controller/readonly_mmio.hpp"

#include <atomic>
#include <fcntl.h>
#include <limits>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>

namespace daphne_sc {
ReadOnlyMmio::ReadOnlyMmio(uint64_t base, size_t length, const char* device)
    : base_(base), length_(length), fd_(-1), mapping_(MAP_FAILED) {
  const long page = sysconf(_SC_PAGESIZE);
  if (page <= 0 || base % 4 || length == 0 || length % 4 ||
      length > static_cast<size_t>(page) || base > static_cast<uint64_t>(std::numeric_limits<off_t>::max()))
    throw std::invalid_argument("Invalid read-only register window");
  offset_ = base % static_cast<uint64_t>(page);
  map_length_ = offset_ + length;
  fd_ = open(device, O_RDONLY | O_SYNC | O_CLOEXEC);
  if (fd_ < 0) throw std::runtime_error("Cannot open read-only register device");
  mapping_ = mmap(nullptr, map_length_, PROT_READ, MAP_SHARED, fd_, base - offset_);
  if (mapping_ == MAP_FAILED) {
    close(fd_);
    throw std::runtime_error("Cannot map read-only register window");
  }
}
ReadOnlyMmio::~ReadOnlyMmio() {
  munmap(mapping_, map_length_);
  close(fd_);
}
uint32_t ReadOnlyMmio::read32(uint64_t address) {
  if (address < base_ || address % 4 || address - base_ > length_ - 4)
    throw std::out_of_range("Read outside the qualified register window");
  const auto* ptr = reinterpret_cast<volatile const uint32_t*>(
      static_cast<const char*>(mapping_) + offset_ + (address - base_));
  std::atomic_thread_fence(std::memory_order_seq_cst);
  const auto value = *ptr;
  std::atomic_thread_fence(std::memory_order_seq_cst);
  return value;
}
void ReadOnlyMmio::write32(uint64_t, uint32_t) {
  throw std::logic_error("Writes are forbidden on a read-only register window");
}
}
