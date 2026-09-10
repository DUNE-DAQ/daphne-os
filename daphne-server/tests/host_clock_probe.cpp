#include "server_controller/host_clock.hpp"
#include <google/protobuf/text_format.h>
#include <iostream>

int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "Usage: host_clock_probe (read-only clocks and adjtimex modes=0; no time adjustment, files, services, network or FPGA access)\n";
    return 2;
  }
  daphne::SystemStatusSnapshot status;
  daphne_sc::add_host_clock(status);
  std::string output;
  if (!google::protobuf::TextFormat::PrintToString(status, &output)) return 1;
  std::cout << output;
  // Reporting an unsynchronized kernel is a valid observation, not probe failure.
  return status.host_time().clock().quality() == daphne::MEASUREMENT_GOOD &&
      status.host_time().kernel().quality() == daphne::MEASUREMENT_GOOD ? 0 : 1;
}
