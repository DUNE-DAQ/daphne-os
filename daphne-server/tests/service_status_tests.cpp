#include <iostream>
#include <stdexcept>
#include <utility>

#include "server_controller/service_status.hpp"

void require(bool value) { if (!value) throw std::runtime_error("Service status test failed"); }
template <typename F> void rejects(F function) {
  bool failed = false;
  try { function(); } catch (const std::exception&) { failed = true; }
  require(failed);
}
int main() {
  using namespace daphne_sc;
  const std::string target =
      "Id=daphne-runtime.target\nLoadState=loaded\nActiveState=active\nSubState=active\n"
      "UnitFileState=enabled\nConditionResult=yes\nActiveEnterTimestampMonotonic=120\n";
  const std::string server =
      "Id=daphne.service\nLoadState=loaded\nActiveState=active\nSubState=running\n"
      "UnitFileState=disabled\nConditionResult=yes\nResult=success\nMainPID=123\nNRestarts=0\n"
      "ExecMainCode=0\nExecMainStatus=0\nInvocationID=0123456789abcdef0123456789abcdef\n"
      "ExecMainStartTimestampMonotonic=100\n";
  auto readings = parse_service_status(target + "\n" + server, 1000, 200000);
  require(readings.size() == 8);
  const auto& t = readings[0];
  require(t.quality() == daphne::MEASUREMENT_GOOD && !t.has_main_pid() && !t.has_automatic_restarts());
  require(t.active_enter_monotonic_ns() == 120000 && t.condition_result());
  const auto& s = readings[7];
  require(s.quality() == daphne::MEASUREMENT_GOOD && s.main_pid() == 123);
  require(s.has_automatic_restarts() && s.automatic_restarts() == 0);
  require(s.unit_file_state() == "disabled" && s.active_state() == "active");
  require(s.exec_main_start_monotonic_ns() == 100000 && s.observed_monotonic_ns() == 200000);
  require(readings[1].quality() == daphne::MEASUREMENT_ERROR && !readings[1].has_main_pid());
  require(!readings[1].observed_monotonic_ns());
  daphne::ServiceStatus decoded;
  require(decoded.ParseFromString(s.SerializeAsString()) && decoded.has_automatic_restarts());
  require(decoded.ParseFromString(t.SerializeAsString()) && !decoded.has_automatic_restarts());
  rejects([&] { parse_service_status(server + "\n" + server, 1, 2); });
  rejects([&] { parse_service_status("Id=ssh.service\n", 1, 2); });
  rejects([&] { parse_service_status(server + "MainPID=1\n", 1, 2); });
  rejects([&] { parse_service_status("no equals", 1, 2); });
  rejects([&] { parse_service_status(server, 1, 0); });
  rejects([&] { parse_service_status(std::string(32769, 'x'), 1, 2); });
  for (const auto& change : {std::pair<std::string, std::string>{"MainPID=123", "MainPID=-1"},
                            {"MainPID=123", "MainPID=4294967296"},
                            {"NRestarts=0", "NRestarts=18446744073709551616"},
                            {"ConditionResult=yes", "ConditionResult=maybe"},
                            {"ActiveState=active", "ActiveState="},
                            {"ExecMainStartTimestampMonotonic=100", "ExecMainStartTimestampMonotonic=18446744073709551615"},
                            {"0123456789abcdef0123456789abcdef", "not-an-invocation-id"}}) {
    auto corrupt = server;
    corrupt.replace(corrupt.find(change.first), change.first.size(), change.second);
    const auto bad = parse_service_status(corrupt, 1, 2)[7];
    require(bad.quality() == daphne::MEASUREMENT_ERROR && !bad.has_main_pid() && !bad.observed_monotonic_ns());
  }
  auto oneshot = server;
  oneshot.replace(oneshot.find("SubState=running"), 16, "SubState=exited");
  const auto exited = parse_service_status(oneshot, 1, 2)[7];
  require(exited.sub_state() == "exited" && exited.result() == "success" && exited.quality() == daphne::MEASUREMENT_GOOD);
  // An exited oneshot and a failed service are observations, not parser errors.
  auto failure = server;
  failure.replace(failure.find("ActiveState=active"), 18, "ActiveState=failed");
  require(parse_service_status(failure, 1, 2)[7].active_state() == "failed");
  std::cout << "Service identity, states, optional fields, timestamps, failures, bounds and wire tests passed\n";
}
