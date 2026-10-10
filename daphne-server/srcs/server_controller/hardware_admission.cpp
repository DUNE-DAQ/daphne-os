#include "server_controller/hardware_admission.hpp"
#include "server_controller/devmem_mmio.hpp"
#include <atomic>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

namespace daphne_sc {
namespace {
std::atomic<bool> raw_dma{false};
std::string read_state(const std::filesystem::path& path) {
  std::ifstream in(path);
  std::string value;
  if (!(in >> value)) return {};
  return value;
}
}
void require_applied_overlay() {
  if (read_state("/sys/class/fpga_manager/fpga0/state") != "operating")
    throw std::runtime_error("FPGA manager is not operating; refusing MMIO");
  const std::filesystem::path root("/sys/kernel/config/device-tree/overlays");
  if (std::filesystem::is_directory(root)) {
    for (const auto& entry : std::filesystem::directory_iterator(root))
      if (read_state(entry.path() / "status") == "applied") return;
  }
  throw std::runtime_error("No applied dynamic PL overlay; refusing MMIO");
}
void require_live_gateware(const GatewareIdentity& expected, GatewareMode mode) {
  require_applied_overlay();
  DevMemWindowMmio32 mmio(kGatewareCapabilitiesAddress, 32);
  const auto current = probe_gateware_identity(mmio);
  validate_gateware_identity(current, mode, expected.build_id);
  if (current.capabilities != expected.capabilities)
    throw std::runtime_error("Gateware capabilities changed; restart and reconfigure");
}
void set_raw_dma_register_policy(bool enabled) { raw_dma.store(enabled); }
void validate_legacy_register_address(uint64_t a) {
  if (!raw_dma.load()) return;
  bool allowed = false;
  // Exact retained register words from FpgaRegDict and the raw-DMA contract.
  if (a == 0x80000000ULL) allowed = true;
  for (uint64_t afe = 0; afe < 5; ++afe)
    for (uint64_t off : {4ULL, 8ULL, 12ULL})
      if (a == 0x80000000ULL + afe * 12 + off) allowed = true;
  if (a >= 0x84000000ULL && a <= 0x8400000CULL && !(a & 3)) allowed = true;
  if (a == 0x88000000ULL || a == 0x88000004ULL ||
      (a >= 0x8800000CULL && a <= 0x88000030ULL && !(a & 3))) allowed = true;
  if (a >= 0x8C000000ULL && a <= 0x8C00000CULL && !(a & 3)) allowed = true;
  if ((a >= 0x94000000ULL && a <= 0x94000048ULL && !(a & 3)) ||
      a == kGatewareCapabilitiesAddress ||
      (a >= kGatewareIdentityMagicAddress && a <= kGatewareIdentityBuildAddress && !(a & 3))) allowed = true;
  if (!allowed) throw std::runtime_error("REGISTER_UNAVAILABLE: legacy MMIO window is absent in raw-dma");
}
} // namespace daphne_sc
