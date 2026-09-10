#include "server_controller/afe_global.hpp"
#include "server_controller/board_monitor.hpp"
#include "server_controller/fpga_status.hpp"
#include <google/protobuf/text_format.h>
#include <iostream>

// Standalone read-only probe: no Daphne constructor, configuration, service,
// networking, SPI or I2C calls. Uses the server's actual admission/collection path.
int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "Usage: afe_global_probe MODE ABI_HEX BUILD_HEX (read-only FPGA status)\n";
    return 2;
  }
  try {
    const auto mode = daphne_sc::parse_gateware_mode(argv[1]);
    const auto abi = daphne_sc::parse_gateware_build_id(argv[2]);
    const auto build = daphne_sc::parse_gateware_build_id(argv[3]);
    const daphne_sc::GatewareIdentity admitted{daphne_sc::kGatewareIdentityMagic, abi, uint32_t(mode), build};
    if (!daphne_sc::supports_afe_global(admitted)) return 2;
    daphne::SystemStatusSnapshot status;
    const bool ok = daphne_sc::collect_fpga_status(status, mode, admitted, nullptr);
    status.set_success(ok);
    // This monotonic time permits independent freshness checks without using UTC.
    status.mutable_server_state()->set_observed_monotonic_ns(daphne_sc::monotonic_time_ns());
    // Exercise the actual health assessor on fresh AFE evidence. Other health
    // inputs (network, temperatures, applied configuration) are not collected
    // by this standalone probe and must not be fabricated as passing.
    *status.mutable_fpga_health() = daphne_sc::assess_fpga_health(
        status, {}, daphne_sc::monotonic_time_ns());
    std::string output;
    if (!google::protobuf::TextFormat::PrintToString(status, &output)) return 1;
    std::cout << output;
    return ok && daphne_sc::afe_global_consistent(status.afe_global()) &&
        status.afe_global().identity_bracket_verified() ? 0 : 1;
  } catch (const std::exception&) {
    std::cerr << "AFE global probe failed; diagnostic details suppressed\n";
    return 1;
  }
}
