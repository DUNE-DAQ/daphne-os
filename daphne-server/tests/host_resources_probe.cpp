#include "server_controller/host_resources.hpp"
#include <iostream>

int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "Usage: host_resources_probe (read-only /proc and root statvfs, no hardware or network access)\n";
    return 2;
  }
  daphne::SystemStatusSnapshot status;
  daphne_sc::add_host_resources(status);
  std::cout << status.DebugString(); // Fixed-source host metrics only; no private identity.
  for (const auto& value : status.host_resources())
    if (value.quality() != daphne::MEASUREMENT_GOOD) return 1;
  return status.host_resources_size() == 6 ? 0 : 1;
}
