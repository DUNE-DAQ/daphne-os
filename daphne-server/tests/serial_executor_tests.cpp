#include "server_controller/serial_executor.hpp"
#include "server_controller/runtime_state.hpp"
#include <atomic>
#include <chrono>
#include <future>
#include <iostream>
#include <stdexcept>
#include <thread>

void require(bool ok) { if (!ok) throw std::runtime_error("Serial executor assertion failed"); }
int main() {
  using namespace daphne_sc;
  using namespace std::chrono_literals;
  std::atomic<uint64_t> now{1};
  RuntimeState state("fixture-instance", "fixture-boot", [&] { return ObservationTime{now.load(), 100}; });
  std::promise<void> started, release;
  auto gate = release.get_future().share();
  SerialExecutor<int> executor(1);
  // Unblock the worker even if an assertion throws before the normal release.
  struct Release { std::promise<void>& p; ~Release() { try { p.set_value(); } catch (...) {} } } cleanup{release};
  require(executor.try_submit([&](const auto& publish) {
    state.begin_operation(202, 10, 20);
    state.begin_configuration();
    state.hardware_started();
    started.set_value();
    if (gate.wait_for(2s) != std::future_status::ready) throw std::runtime_error("Test gate timed out");
    state.finish_configuration(true, "fixture completed", std::string(64, 'c'), true);
    state.end_operation();
    publish(1);
  }));
  require(started.get_future().wait_for(2s) == std::future_status::ready);
  require(state.snapshot().configuration_in_progress());
  state.tick();
  now = 2'000'000'001;
  state.tick();
  require(state.snapshot().heartbeat_sequence() == 2);
  require(state.snapshot().configuration_in_progress()); // Heartbeat/status independent of blocked worker.
  require(executor.try_submit([&](const auto& publish) {
    require(!state.snapshot().configuration_in_progress());
    require(state.snapshot().applied_configuration_valid());
    publish(2);
  }));
  require(!executor.try_submit([](const auto&) { throw std::runtime_error("Rejected work must never run"); }));
  release.set_value();
  int expected = 1, reply = 0;
  const auto deadline = std::chrono::steady_clock::now() + 2s;
  while (expected <= 2 && std::chrono::steady_clock::now() < deadline) {
    if (executor.try_take(reply)) { require(reply == expected); ++expected; }
    else std::this_thread::yield();
  }
  require(expected == 3);
  executor.stop();
  require(!executor.try_submit([](const auto&) {}));
  require(executor.unhandled_errors() == 0);

  // Shutdown must release a worker blocked by bounded reply backpressure.
  SerialExecutor<int> backpressure(1);
  std::promise<void> first_reply;
  require(backpressure.try_submit([&](const auto& publish) {
    publish(1);
    first_reply.set_value();
    publish(2);
  }));
  require(first_reply.get_future().wait_for(2s) == std::future_status::ready);
  backpressure.stop();
  require(backpressure.try_take(reply) && reply == 1);
  require(!backpressure.try_take(reply));
  std::cout << "Serialized execution, responsive bookkeeping, bounded queues, ordering and shutdown backpressure checks passed\n";
}
