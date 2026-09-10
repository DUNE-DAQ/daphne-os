// Explicit SFP diagnostics, never automatic CTest: mux selection/restoration,
// EEPROM pointer reads only. No module control, TX-disable, reset or BIAS writes.
#include "server_controller/sfp_monitor.hpp"
#include "server_controller/gateware.hpp"
#include "server_controller/readonly_mmio.hpp"
#include <iostream>

int main(int argc, char** argv) {
  try {
    if (argc != 3 || std::string(argv[1]) != "--read-sfp-self-trigger")
      throw std::invalid_argument("Usage: sfp_probe --read-sfp-self-trigger EXPECTED_BUILD_ID");
    size_t used = 0;
    const auto expected = std::stoul(argv[2], &used, 0);
    if (used != std::string(argv[2]).size() || expected > 0x0fffffff)
      throw std::invalid_argument("Invalid expected build ID");
    daphne_sc::ReadOnlyMmio mmio(daphne_sc::kGatewareIdentityMagicAddress, 16);
    const auto id = daphne_sc::probe_gateware_identity(mmio);
    daphne_sc::validate_gateware_identity(id, daphne_sc::GatewareMode::kSelfTrigger, expected);
    daphne::SystemStatusSnapshot result;
    daphne_sc::add_sfp_status(result, {});
    std::cout << result.DebugString();
    bool identified = false;
    for (const auto& port : result.sfps()) {
      if (port.has_mux_restored() && !port.mux_restored()) return 2;
      identified |= port.identity_quality() == daphne::MEASUREMENT_GOOD;
    }
    return identified ? 0 : 3; // No responding verified module is not a successful wiring qualification.
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
