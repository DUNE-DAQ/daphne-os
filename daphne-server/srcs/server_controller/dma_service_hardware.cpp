#include "server_controller/dma_service.hpp"
#include "server_controller/hardware_admission.hpp"
#include "server_controller/devmem_mmio.hpp"
#include "Daphne.hpp"
#include "defines.hpp"
#include <filesystem>

namespace daphne_sc {
DmaService::DmaService(Daphne& d, GatewareIdentity id, DmaServiceOptions opts,
                       std::unique_ptr<daphne_dma::AfeCaptureEngine> engine)
    : DmaService(id, opts, engine ? std::move(engine) : daphne_dma::make_linux_afe_engine(opts.maximum_job_bytes),
        [&d, id, readback = std::make_shared<AfeReadbackVerifier>(opts.afe_readback_policy, "DMA admission")]
        (const std::vector<uint32_t>& channels, bool) {
          require_live_gateware(id, GatewareMode::kRawDma);
          DevMemWindowMmio32 clocks(0x84000004, 4);
          if ((clocks.read32(0x84000004) & 3) != 3 ||
              d.getAfe()->getPowerState() != 1 || !d.getFrontEnd()->getDelayCtrlReady())
            throw std::runtime_error("FRONTEND_NOT_READY: clocks/power/IDELAY missing");
          std::array<bool, 5> visited{};
          for (auto ch : channels) {
            const auto a = ch / 8;
            if (visited.at(a)) continue;
            visited[a] = true;
            const auto pl = afe_definitions::AFE_board2PL_map.at(a);
            for (const auto& f : std::vector<std::pair<std::string, uint32_t>>{
                {"SERIALIZED_DATA_RATE",1}, {"ADC_RESOLUTION_RESET",0}, {"ADC_OUTPUT_FORMAT",0},
                {"LSB_MSB_FIRST",0}, {"ADC_COMPLETE_PDN",0}, {"LVDS_OUTPUT_DISABLE",0},
                {"ADC_PDN_CH",0}, {"PARTIAL_PDN",0}, {"POWER-DOWN_LVDS",0},
                {"TEST_PATTERN_MODES",0}, {"SYNC_PATTERN",0}})
              readback->check(a, f.first, f.second, d.getAfe()->getAFEFunction(pl, f.first),
                              "DMA frontend/format readback changed: " + f.first);
          }
        }, {}, [id] { require_live_gateware(id, GatewareMode::kRawDma); },
        [] { return std::filesystem::exists("/dev/daphne-afe-dma"); }) {
  scanner_ = [this, &d](const daphne::AfeDelaySweepRequest& req, const std::atomic<bool>& cancel) {
    return run_dma_eye_scan(d, *engine_, identity_, options_, req, cancel);
  };
}
}
