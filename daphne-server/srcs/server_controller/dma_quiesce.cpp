#include "server_controller/hardware_admission.hpp"
#include "server_controller/devmem_mmio.hpp"
#include "../../dma/afe_capture.hpp"
#include <iostream>
int main() {
  try {
    daphne_sc::require_applied_overlay();
    daphne_sc::DevMemWindowMmio32 mmio(daphne_sc::kGatewareCapabilitiesAddress, 32);
    const auto identity = daphne_sc::probe_gateware_identity(mmio);
    daphne_sc::validate_gateware_identity(identity, daphne_sc::GatewareMode::kRawDma);
    daphne_dma::verify_linux_afe_idle();
    std::cout << "AFE DMA driver released; all three engines halted\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "Refusing raw DMA overlay unload: " << e.what() << '\n';
    return 78;
  }
}
