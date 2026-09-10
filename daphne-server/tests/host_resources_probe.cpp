#include "server_controller/host_resources.hpp"
#include <google/protobuf/text_format.h>
#include <iostream>

int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "Usage: host_resources_probe (read-only /proc and root statvfs, no hardware or network access)\n";
    return 2;
  }
  daphne::SystemStatusSnapshot status;
  daphne_sc::add_host_resources(status);
  // DebugString is deliberately not parseable in Protobuf 30. Use the actual
  // text-format serializer for this fixed-source, non-private probe output.
  std::string output;
  if (!google::protobuf::TextFormat::PrintToString(status, &output)) return 1;
  std::cout << output;
  for (const auto& value : status.host_resources())
    if (value.quality() != daphne::MEASUREMENT_GOOD) return 1;
  return status.host_resources_size() == 6 ? 0 : 1;
}
