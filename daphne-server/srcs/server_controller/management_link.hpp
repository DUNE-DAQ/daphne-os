#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
struct ManagementLinkTime { uint64_t host_unix_ns; uint64_t monotonic_ns; };
class ManagementLinkIo {
 public:
  virtual ~ManagementLinkIo() = default;
  virtual std::string read_file(const char* relative_path, size_t maximum_bytes) = 0;
  virtual ManagementLinkTime now() = 0;
};
// Fourteen fixed metrics, bounded inputs, individual quality/time and ifindex
// bracketing. No cached fallback, counter epoch/rates, or network setters.
daphne::ManagementLinkStatus read_management_link(ManagementLinkIo& io, uint32_t expected_index);
// Pins one sysfs NIC directory. No scans, subprocesses, packets or hard syscall
// deadline. Called inside the existing management-identity read bracket.
daphne::ManagementLinkStatus read_management_link_linux(const std::string& interface, uint32_t expected_index);
}  // namespace daphne_sc
