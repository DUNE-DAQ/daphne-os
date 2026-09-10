#include "server_controller/fpga_status.hpp"
#include "server_controller/board_monitor.hpp"
#include <google/protobuf/text_format.h>
#include <iostream>

// Explicit read-only diagnostic, NEVER an automatic hardware test. No Daphne
// constructor, configuration, network, SPI, I2C, service or fan-control writes.
int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "Usage: fan_register_probe MODE ABI_HEX BUILD_HEX\n";
    return 2;
  }
  try {
    using namespace daphne_sc;
    const auto mode = parse_gateware_mode(argv[1]);
    const GatewareIdentity admitted{kGatewareIdentityMagic, parse_gateware_build_id(argv[2]),
        uint32_t(mode), parse_gateware_build_id(argv[3])};
    if (!supports_fan_registers(admitted)) return 2;
    daphne::SystemStatusSnapshot status;
    const bool ok = collect_fpga_status(status, mode, admitted, nullptr);
    status.set_success(ok);
    status.mutable_server_state()->set_observed_monotonic_ns(monotonic_time_ns());
    std::string output;
    if (!google::protobuf::TextFormat::PrintToString(status, &output)) return 1;
    std::cout << output;
    if (!ok || status.fans_size() != 2) return 1;
    for (unsigned i = 0; i < 2; ++i)
      if (!fan_registers_consistent(status.fans(i), i) || !status.fans(i).identity_bracket_verified()) return 1;
    return 0;
  } catch (const std::exception&) {
    std::cerr << "Fan register probe failed; diagnostic details suppressed\n";
    return 1;
  }
}
