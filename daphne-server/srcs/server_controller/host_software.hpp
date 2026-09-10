#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
struct HostSoftwareTime { uint64_t host_unix_ns; uint64_t monotonic_ns; };
class HostSoftwareIo {
 public:
  virtual ~HostSoftwareIo() = default;
  virtual std::string kernel_release() = 0;
  virtual std::string read_file(const char* path, size_t maximum_bytes) = 0;
  virtual HostSoftwareTime now() = 0;
};
// Seven fresh observations. Missing fields remain unavailable, never defaults.
// /etc/os-release takes precedence; use /usr/lib/os-release only on ENOENT.
// Do not merge files, execute assignments, or infer current rootfs integrity.
std::vector<daphne::HostSoftwareObservation> read_host_software(HostSoftwareIo& io);
// Fixed uname + release-file reads only, no subprocess/hardware/network writes.
// Bounded regular-file reads; normal os-release symlinks are supported. No hard
// syscall deadline or atomic snapshot across uname and the release file.
void add_host_software(daphne::SystemStatusSnapshot& status);
}  // namespace daphne_sc
