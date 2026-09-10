#include "server_controller/current_monitor.hpp"
#include "server_controller/current_mux.hpp"
#include "server_controller/board_monitor.hpp"
#include "server_controller/readonly_mmio.hpp"
#include "server_controller/devmem_mmio.hpp"
#include "server_controller/runtime_state.hpp"
#include "BoardSPI.hpp"
#include "SpiDevice.hpp"
#include <chrono>
#include <exception>
#include <mutex>
#include <thread>

namespace daphne_sc {
daphne::cmd_readCurrentMonitor_response read_current_monitor(
    const daphne::cmd_readCurrentMonitor& request, GatewareMode mode,
    std::optional<GatewareIdentity> admitted, bool mezzanines_enabled, RuntimeState* runtime) {
  daphne::cmd_readCurrentMonitor_response response;
  response.set_quality(daphne::CURRENT_MONITOR_ERROR);
  response.set_current_quality(daphne::CURRENT_MONITOR_UNAVAILABLE);
  response.set_current_detail(mezzanines_enabled ?
      "No approved per-channel current calibration loaded; amperes unavailable" :
      "Operator declares no mezzanines fitted; onboard ADC can be read, but no installed/calibrated sensor current is claimed");
  try {
    const auto plan = current_request_selection(request);
    response.set_currentmonitorchannel(plan.physical_channel);
    response.set_carrier_mux_enable(plan.enable);
    response.set_carrier_mux_address(plan.address);
    // Extra serialization for any future callers outside the one hardware worker.
    static std::mutex mutex;
    std::lock_guard<std::mutex> lock(mutex);
    ReadOnlyMmio id_mmio(kGatewareIdentityMagicAddress, 16);
    const auto identity = probe_gateware_identity(id_mmio);
    validate_runtime_gateware(identity, mode, admitted ? std::optional<uint32_t>(admitted->build_id) : std::nullopt, runtime);
    const auto path = board_current_spi_device();
    response.set_source("Carrier U6 ADS1261 / PL SPI 9c020000 CS0 / " + path +
        " / AFE " + std::to_string(plan.afe) + " DA-DB / local channel " + std::to_string(plan.local_channel));
    SpiDevice spi(path, 1000000, 1, 8); // Holds cooperative device lock until mux restoration.
    ADS1261 adc([&](const auto& tx) { return spi.transfer(tx); }, monotonic_time_ns,
        [](uint64_t ns) { std::this_thread::sleep_for(std::chrono::nanoseconds(ns)); });
    adc.initialize(); // Identification before any ADC reset or carrier selection.
    DevMemWindowMmio32 mux_mmio(CurrentMuxTransaction::enable_address, 8);
    CurrentMuxTransaction mux(mux_mmio);
    std::exception_ptr primary_error;
    try {
      response.set_carrier_mux_restored(false);
      mux.select(plan.physical_channel);
      std::this_thread::sleep_for(std::chrono::milliseconds(20)); // Conservative selector/ADC-input settling margin.
      const auto sample = adc.convert(plan.afe);
      mux.verify(plan.physical_channel);
      set_current_sample(response, sample);
      response.set_observed_host_unix_ns(host_unix_time_ns());
    } catch (...) { primary_error = std::current_exception(); }
    // Restore even after a failed/timeout/CRC measurement. Restoration failure
    // wins over a nominally good sample; destructor also attempts safe disconnect.
    mux.restore();
    response.set_carrier_mux_restored(true);
    if (primary_error) std::rethrow_exception(primary_error);
  } catch (const std::exception& e) {
    response.set_success(false);
    response.set_quality(daphne::CURRENT_MONITOR_ERROR);
    response.set_currentvalue(0);
    response.clear_differential_volts();
    response.clear_current_amperes();
    response.set_message(e.what());
  }
  return response;
}
}  // namespace daphne_sc
