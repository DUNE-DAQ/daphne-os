#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
struct HostResourceTime { uint64_t host_unix_ns; uint64_t monotonic_ns; };
struct RootFilesystemSpace {
  uint64_t fragment_bytes;
  uint64_t blocks;
  uint64_t free_blocks;
  uint64_t available_blocks;
  bool read_only;
};
class HostResourceIo {
 public:
  virtual ~HostResourceIo() = default;
  virtual std::string read_file(const char* path, size_t maximum_bytes) = 0;
  virtual RootFilesystemSpace root_filesystem() = 0;
  virtual HostResourceTime now() = 0;
};
// Pure collector with injectable Linux observations. Six typed results, no
// cached fallback or health inference. No value/timestamp on failed reads.
std::vector<daphne::HostResourceObservation> read_host_resources(HostResourceIo& io);
// Fixed /proc/uptime, /proc/loadavg, /proc/meminfo and statvfs("/") only.
// Bounded input bytes; no subprocesses, writes, scans or hard syscall deadline.
void add_host_resources(daphne::SystemStatusSnapshot& status);
}  // namespace daphne_sc
