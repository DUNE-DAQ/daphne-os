#include "server_controller/runtime_state.hpp"
#include <atomic>
#include <iostream>
#include <stdexcept>
#include <thread>

void require(bool ok) { if (!ok) throw std::runtime_error("Runtime-state assertion failed"); }
template<class F> void fails(F function) {
  bool failed = false;
  try { function(); } catch (const std::logic_error&) { failed = true; }
  require(failed);
}
int main() {
  using namespace daphne_sc;
  std::atomic<uint64_t> now{1};
  auto clock = [&] { return ObservationTime{now.load(), 100}; };
  RuntimeState state("instance-a", "boot-a", clock);
  require(!state.snapshot().applied_configuration_valid());
  require(state.snapshot().last_configuration_result().outcome() == daphne::CONFIGURATION_NEVER_ATTEMPTED);
  state.tick();
  require(state.snapshot().heartbeat_sequence() == 1);
  now = 2'000'000'001;
  require(state.snapshot().heartbeat_sequence() == 1); // Reads do not tick.
  state.tick();
  state.tick();
  require(state.snapshot().heartbeat_sequence() == 2);
  now = 1;
  state.tick();
  require(state.snapshot().heartbeat_sequence() == 2); // Never underflow on clock reversal.
  now = 3'000'000'001;
  fails([&] { state.begin_configuration(); });
  state.begin_operation(202, 123, 456);
  fails([&] { state.begin_operation(202, 0, 0); });
  state.begin_configuration();
  require(state.snapshot().configuration_in_progress());
  fails([&] { state.end_operation(); });
  state.hardware_started();
  fails([&] { state.finish_configuration(true, "bad evidence", "xyz", true); });
  state.finish_configuration(true, "done", std::string(64, 'a'), true);
  state.end_operation();
  auto good = state.snapshot();
  require(good.applied_configuration_valid());
  require(good.applied_configuration_hash() == std::string(64, 'a'));
  require(good.last_configuration_result().task_id() == 123);
  require(good.last_configuration_result().request_msg_id() == 456);
  require(good.last_configuration_result().completed_host_unix_ns() == 100);
  require(!good.executor_busy());

  state.begin_operation(202, 124, 457);
  state.begin_configuration();
  state.finish_configuration(false, "invalid preflight");
  state.end_operation();
  require(state.snapshot().applied_configuration_valid()); // Rejected request cannot invalidate prior success.
  require(state.snapshot().last_configuration_result().outcome() == daphne::CONFIGURATION_REJECTED);

  state.begin_operation(202, 125, 458);
  state.begin_configuration();
  state.hardware_started();
  state.finish_configuration(false, "failed write");
  state.end_operation();
  require(!state.snapshot().applied_configuration_valid());
  require(state.snapshot().applied_configuration_hash() == std::string(64, 'a')); // Retained historic digest, explicitly invalid.
  require(state.snapshot().last_configuration_result().outcome() == daphne::CONFIGURATION_FAILED);

  state.begin_operation(202, 126, 459);
  state.begin_configuration();
  state.hardware_started();
  std::thread protection([&] { state.invalidate("protective event"); });
  protection.join();
  state.finish_configuration(true, "done", std::string(64, 'b'), true);
  state.end_operation();
  require(!state.snapshot().applied_configuration_valid());
  require(state.snapshot().invalidation_reason() == "protective event");

  state.begin_operation(202, 127, 460);
  state.begin_configuration();
  state.hardware_started();
  state.finish_configuration(true, "partial", {}, false);
  state.end_operation();
  require(!state.snapshot().applied_configuration_valid());
  require(state.snapshot().last_configuration_result().outcome() == daphne::CONFIGURATION_SUCCEEDED);

  RuntimeState restarted("instance-b", "boot-a", clock);
  require(!restarted.snapshot().applied_configuration_valid());
  require(restarted.snapshot().applied_configuration_hash().empty());
  require(restarted.snapshot().heartbeat_sequence() == 0);
  auto original = state.snapshot();
  daphne::ServerState copy;
  require(copy.ParseFromString(original.SerializeAsString()));
  require(copy.SerializeAsString() == original.SerializeAsString());
  std::cout << "Runtime heartbeat, correlation, preflight/failure, partial scope, protection race, restart and wire checks passed\n";
}
