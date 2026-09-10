#include "server_controller/host_clock.hpp"
#include "server_controller/timesync.hpp"
#include <google/protobuf/text_format.h>
#include <iostream>
int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "Usage: timesync_probe (read-only local clocks and timesync1; no service activation, clock changes, network peers or private output)\n";
    return 2;
  }
  daphne::SystemStatusSnapshot status;
  daphne_sc::add_host_clock(status);
  daphne_sc::add_timesync_status(status);
  std::string output;
  if (!google::protobuf::TextFormat::PrintToString(status, &output)) return 1;
  std::cout << output;
  return status.host_time().timesync().quality() == daphne::MEASUREMENT_GOOD &&
      status.host_time().timesync().last_sample().quality() != daphne::MEASUREMENT_ERROR ? 0 : 1;
}
