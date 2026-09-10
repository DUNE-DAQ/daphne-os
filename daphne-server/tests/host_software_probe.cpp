#include "server_controller/host_software.hpp"
#include <google/protobuf/text_format.h>
#include <iostream>

int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "Usage: host_software_probe (uname and selected os-release fields only; no hardware access)\n";
    return 2;
  }
  daphne::SystemStatusSnapshot status;
  daphne_sc::add_host_software(status);
  std::string output;
  if (!google::protobuf::TextFormat::PrintToString(status, &output)) return 1;
  std::cout << output;
  if (status.host_software_size() != 7) return 1;
  for (const auto& item : status.host_software())
    if (item.quality() != daphne::MEASUREMENT_GOOD && item.quality() != daphne::MEASUREMENT_UNAVAILABLE) return 1;
  return status.host_software(0).quality() == daphne::MEASUREMENT_GOOD ? 0 : 1;
}
