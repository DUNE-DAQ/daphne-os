#include <cstdlib>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <zmq.hpp>

#include "CLI/CLI.hpp"
#include "Daphne.hpp"
#include "server_controller/devmem_mmio.hpp"
#include "server_controller/gateware.hpp"
#include "server_controller/handlers.hpp"
#include "server_controller/monitoring.hpp"
#include "server_controller/router_server.hpp"

int main(int argc, char* argv[]) {
  CLI::App app{"daphneServer"};

  std::string bind_endpoint = "tcp://*:9876";
  std::string gateware_mode_value;
  std::string expected_gateware_build_id_value;
  bool disable_monitoring = false;
  bool no_mezzanines = false;
  int monitor_period_ms = 200;
  daphne_sc::TemperatureAlarmPolicy temperature_policy;

  daphne_sc::RouterServerOptions server_opts;

  app.add_option("--bind", bind_endpoint, "ZeroMQ bind endpoint")->default_val(bind_endpoint);
  app.add_option("--gateware-mode", gateware_mode_value,
                 "Expected gateware variant: self-trigger or full-stream")
      ->required();
  app.add_option("--expected-gateware-build-id", expected_gateware_build_id_value,
                 "Optional expected 32-bit gateware build ID (decimal or 0x-prefixed hex)");
  app.add_flag("--disable-monitoring", disable_monitoring, "Disable background I2C monitoring threads");
  app.add_flag("--no-mezzanines", no_mezzanines,
               "Operator declares no mezzanines fitted: skip mux and downstream driver initialization")
      ->envname("DAPHNE_NO_MEZZANINES");
  app.add_option("--monitor-period-ms", monitor_period_ms, "Monitoring period in milliseconds")
      ->default_val(monitor_period_ms);
  app.add_option("--temperature-warning-c", temperature_policy.warning_c,
                 "Provisional warning threshold in Celsius; monitoring only")
      ->default_val(temperature_policy.warning_c)->envname("DAPHNE_TEMP_WARNING_C");
  app.add_option("--temperature-high-c", temperature_policy.high_c,
                 "Provisional high threshold in Celsius; monitoring only")
      ->default_val(temperature_policy.high_c)->envname("DAPHNE_TEMP_HIGH_C");
  app.add_option("--temperature-critical-c", temperature_policy.critical_c,
                 "Provisional critical threshold in Celsius; no automatic shutdown")
      ->default_val(temperature_policy.critical_c)->envname("DAPHNE_TEMP_CRITICAL_C");
  app.add_option("--temperature-maximum-age-ms", temperature_policy.maximum_age_ms,
                 "Maximum temperature observation age for alarm evaluation")
      ->default_val(temperature_policy.maximum_age_ms)->envname("DAPHNE_TEMP_MAXIMUM_AGE_MS");

  app.add_option("--sndhwm", server_opts.sndhwm, "ZMQ SNDHWM")->default_val(server_opts.sndhwm);
  app.add_option("--rcvhwm", server_opts.rcvhwm, "ZMQ RCVHWM")->default_val(server_opts.rcvhwm);
  app.add_option("--sndbuf", server_opts.sndbuf, "ZMQ SNDBUF bytes")->default_val(server_opts.sndbuf);
  app.add_option("--max-envelope-bytes", server_opts.max_envelope_bytes, "Max incoming envelope bytes")
      ->default_val(server_opts.max_envelope_bytes);

  try {
    app.parse(argc, argv);
  } catch (const CLI::ParseError& e) {
    return app.exit(e);
  }

  constexpr int kConfigurationErrorExit = 78;
  daphne_sc::GatewareMode gateware_mode;
  std::optional<uint32_t> expected_gateware_build_id;
  try {
    daphne_sc::validate_temperature_alarm_policy(temperature_policy);
    gateware_mode = daphne_sc::parse_gateware_mode(gateware_mode_value);
    if (!expected_gateware_build_id_value.empty()) {
      expected_gateware_build_id =
          daphne_sc::parse_gateware_build_id(expected_gateware_build_id_value);
    }
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return kConfigurationErrorExit;
  }

  daphne_sc::GatewareIdentity identity;
  try {
    constexpr size_t kIdentityWindowLength =
        daphne_sc::kGatewareIdentityBuildAddress -
        daphne_sc::kGatewareIdentityMagicAddress + sizeof(uint32_t);
    daphne_sc::DevMemWindowMmio32 identity_mmio(
        daphne_sc::kGatewareIdentityMagicAddress, kIdentityWindowLength);
    identity = daphne_sc::probe_gateware_identity(identity_mmio);
    daphne_sc::validate_gateware_identity(identity, gateware_mode, expected_gateware_build_id);
  } catch (const std::exception& e) {
    // This check intentionally happens before Daphne construction because its
    // hardware drivers can write MMIO/I2C/SPI registers during initialization.
    std::cerr << "Gateware admission failed before hardware initialization: " << e.what() << '\n';
    return kConfigurationErrorExit;
  }
  if (!expected_gateware_build_id) {
    std::cerr << "WARNING: --expected-gateware-build-id was not supplied; "
                 "mode and ABI are enforced, but this build is not pinned\n";
  }

  std::shared_ptr<daphne_sc::Mmio32> full_stream_mmio;
  if (gateware_mode == daphne_sc::GatewareMode::kFullStream) {
    try {
      full_stream_mmio = std::make_shared<daphne_sc::DevMemWindowMmio32>(
          daphne_sc::kFullStreamMuxBaseAddress,
          daphne_sc::kFullStreamMuxWindowLength);
      // Fail closed on every process start.  A previous server may have died
      // while streaming, so do not construct Daphne (which can touch the
      // front-end hardware) until the stream domain has acknowledged idle.
      daphne_sc::disable_full_stream_outputs(*full_stream_mmio);
    } catch (const std::exception& e) {
      std::cerr << "Failed to map and quiesce the full-stream mux before hardware initialization: "
                << e.what() << '\n';
      return kConfigurationErrorExit;
    }
  }

  zmq::context_t context(1);
  const auto runtime = daphne_sc::make_process_runtime_state();
  Daphne daphne(!no_mezzanines, runtime);

  std::vector<std::thread> monitor_threads;
  if (!disable_monitoring) {
    daphne_sc::MonitoringOptions opts;
    opts.period = std::chrono::milliseconds(monitor_period_ms);
    monitor_threads = daphne_sc::start_monitoring(daphne, opts);
  }

  std::cout << "Starting daphneServer\n";
  std::cout << "Bind: " << bind_endpoint << "\n";
  std::cout << "Gateware: " << daphne_sc::gateware_mode_name(gateware_mode)
            << ", register ABI 0x" << std::hex << identity.abi << ", build 0x"
            << identity.build_id << std::dec << "\n";
  if (disable_monitoring) {
    std::cout << "Monitoring: disabled\n";
  } else {
    std::cout << "Monitoring period: " << monitor_period_ms << " ms\n";
  }

  const auto handlers = daphne_sc::make_v2_handlers(gateware_mode, full_stream_mmio, identity, temperature_policy);
  daphne_sc::run_router_server(context, bind_endpoint, daphne, handlers, server_opts);

  for (auto& t : monitor_threads) {
    if (t.joinable()) t.join();
  }

  return 0;
}
