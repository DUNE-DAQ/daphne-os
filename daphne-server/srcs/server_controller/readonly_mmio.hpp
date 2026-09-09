#pragma once

#include "server_controller/gateware.hpp"

namespace daphne_sc {
// Separate read-only mapping: diagnostic requests cannot obtain a write path.
class ReadOnlyMmio final : public Mmio32 {
 public:
  ReadOnlyMmio(uint64_t base, size_t length, const char* device = "/dev/mem");
  ~ReadOnlyMmio();
  ReadOnlyMmio(const ReadOnlyMmio&) = delete;
  ReadOnlyMmio& operator=(const ReadOnlyMmio&) = delete;
  uint32_t read32(uint64_t address) override;
  void write32(uint64_t, uint32_t) override;
 private:
  uint64_t base_;
  size_t length_;
  size_t offset_;
  size_t map_length_;
  int fd_;
  void* mapping_;
};
}
