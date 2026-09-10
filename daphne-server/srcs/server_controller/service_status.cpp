#include "server_controller/service_status.hpp"

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <fstream>
#include <limits>
#include <map>
#include <mutex>
#include <poll.h>
#include <spawn.h>
#include <sstream>
#include <stdexcept>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>

#include "server_controller/board_monitor.hpp"
#include "server_controller/software_build.hpp"
#include "server_controller/host_software.hpp"

extern char** environ;
namespace daphne_sc {
namespace {
using Properties = std::map<std::string, std::string>;

uint64_t number(const std::string& value, uint64_t maximum = UINT64_MAX) {
  if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
    throw std::runtime_error("Invalid numeric service property");
  const auto result = std::stoull(value);
  if (result > maximum) throw std::runtime_error("Service property overflow");
  return result;
}
std::string token(const Properties& props, const char* key, bool required = true) {
  const auto it = props.find(key);
  if (it == props.end() || it->second.empty()) {
    if (required) throw std::runtime_error(std::string("Missing service property: ") + key);
    return {};
  }
  const auto& value = it->second;
  if (value.size() > 80 || value.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_-") != std::string::npos)
    throw std::runtime_error(std::string("Invalid service property: ") + key);
  return value;
}

std::string query_systemd() {
  int pipe_fds[2];
  if (pipe2(pipe_fds, O_CLOEXEC) != 0) throw std::runtime_error("Cannot create service-status pipe");
  posix_spawn_file_actions_t actions;
  int error = posix_spawn_file_actions_init(&actions);
  if (error) { close(pipe_fds[0]); close(pipe_fds[1]); throw std::runtime_error("Cannot prepare service-status query"); }
  error = posix_spawn_file_actions_adddup2(&actions, pipe_fds[1], STDOUT_FILENO);
  if (!error) error = posix_spawn_file_actions_addclose(&actions, pipe_fds[0]);
  if (!error) error = posix_spawn_file_actions_addclose(&actions, pipe_fds[1]);
  if (!error) error = posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
  std::vector<std::string> args{"/usr/bin/systemctl", "show", "--no-pager", "--no-ask-password",
      "--property=Id,LoadState,ActiveState,SubState,Result,UnitFileState,MainPID,NRestarts,ExecMainCode,"
      "ExecMainStatus,ConditionResult,InvocationID,ActiveEnterTimestampMonotonic,ExecMainStartTimestampMonotonic"};
  for (auto unit : kServiceUnits) args.emplace_back(unit);
  std::vector<char*> argv;
  for (auto& arg : args) argv.push_back(arg.data());
  argv.push_back(nullptr);
  pid_t child = -1;
  if (!error) error = posix_spawn(&child, argv[0], &actions, nullptr, argv.data(), environ);
  posix_spawn_file_actions_destroy(&actions);
  close(pipe_fds[1]);
  if (error) { close(pipe_fds[0]); throw std::runtime_error("Cannot execute allow-listed systemctl query"); }

  std::string output;
  int child_status = 0;
  bool exited = false, eof = false;
  const auto deadline = monotonic_time_ns() + 1'000'000'000ULL;
  try {
    if (fcntl(pipe_fds[0], F_SETFL, O_NONBLOCK) < 0) throw std::runtime_error("Cannot read service-status pipe");
    while (!exited || !eof) {
      if (monotonic_time_ns() >= deadline) throw std::runtime_error("Service-status query exceeded 1 second");
      pollfd descriptor{pipe_fds[0], POLLIN | POLLHUP, 0};
      if (poll(&descriptor, 1, 10) < 0 && errno != EINTR) throw std::runtime_error("Service-status poll failed");
      char bytes[4096];
      for (;;) {
        const auto count = read(pipe_fds[0], bytes, sizeof(bytes));
        if (count > 0) {
          output.append(bytes, count);
          if (output.size() > 32768) throw std::runtime_error("Service-status output exceeded limit");
        } else if (!count) { eof = true; break; }
        else if (errno == EINTR) continue;
        else if (errno == EAGAIN || errno == EWOULDBLOCK) break;
        else throw std::runtime_error("Service-status read failed");
      }
      if (!exited) {
        const auto result = waitpid(child, &child_status, WNOHANG);
        if (result == child) exited = true;
        else if (result < 0 && errno != EINTR) throw std::runtime_error("Service-status child wait failed");
      }
    }
    if (!WIFEXITED(child_status) || WEXITSTATUS(child_status) != 0)
      throw std::runtime_error("systemctl show failed; no service-health inference");
  } catch (...) {
    close(pipe_fds[0]);
    if (!exited) {
      kill(child, SIGKILL);
      while (waitpid(child, &child_status, 0) < 0 && errno == EINTR) {}
    }
    throw;
  }
  close(pipe_fds[0]);
  return output;
}

std::string read_assignment(const char* path, const char* key) {
  std::ifstream file(path);
  std::string line, prefix = std::string(key) + "=";
  while (std::getline(file, line)) {
    if (line.rfind(prefix, 0) != 0) continue;
    auto value = line.substr(prefix.size());
    if (value.size() >= 2 && ((value.front() == '"' && value.back() == '"') ||
                            (value.front() == '\'' && value.back() == '\'')))
      value = value.substr(1, value.size() - 2);
    if (value.size() > 160 || std::any_of(value.begin(), value.end(), [](unsigned char c) { return c < 32 || c > 126; })) return {};
    return value; // Never expand or execute content from environment files.
  }
  return {};
}
}  // namespace

std::vector<daphne::ServiceStatus> parse_service_status(const std::string& output,
                                                      uint64_t host_ns, uint64_t mono_ns) {
  if (!mono_ns || output.size() > 32768) throw std::runtime_error("Invalid service observation");
  std::map<std::string, Properties> units;
  std::istringstream input(output);
  Properties current;
  auto finish = [&] {
    if (current.empty()) return;
    const auto id = current.find("Id");
    if (id == current.end() || std::find(kServiceUnits.begin(), kServiceUnits.end(), id->second) == kServiceUnits.end())
      throw std::runtime_error("Unexpected service identity");
    if (!units.emplace(id->second, current).second) throw std::runtime_error("Duplicate service identity");
    current.clear();
  };
  std::string line;
  while (std::getline(input, line)) {
    if (line.empty()) { finish(); continue; }
    const auto equals = line.find('=');
    if (equals == std::string::npos || !current.emplace(line.substr(0, equals), line.substr(equals + 1)).second)
      throw std::runtime_error("Malformed or duplicate service property");
  }
  finish();
  std::vector<daphne::ServiceStatus> result;
  for (auto name : kServiceUnits) {
    daphne::ServiceStatus item;
    item.set_name(name);
    item.set_quality(daphne::MEASUREMENT_ERROR);
    const auto unit = units.find(name);
    if (unit == units.end()) { item.set_message("Unit missing from systemctl observation"); result.push_back(item); continue; }
    try {
      const auto& props = unit->second;
      daphne::ServiceStatus parsed;
      parsed.set_name(name);
      parsed.set_load_state(token(props, "LoadState"));
      parsed.set_active_state(token(props, "ActiveState"));
      parsed.set_sub_state(token(props, "SubState"));
      parsed.set_result(token(props, "Result", false));
      parsed.set_unit_file_state(token(props, "UnitFileState", false));
      auto numeric = [&](const char* key, auto setter, uint64_t maximum = UINT64_MAX) {
        const auto found = props.find(key);
        if (found != props.end() && !found->second.empty()) setter(number(found->second, maximum));
      };
      numeric("MainPID", [&](uint64_t value) { parsed.set_main_pid(value); }, UINT32_MAX);
      numeric("NRestarts", [&](uint64_t value) { parsed.set_automatic_restarts(value); });
      numeric("ExecMainCode", [&](uint64_t value) { parsed.set_exec_main_code(value); }, INT32_MAX);
      numeric("ExecMainStatus", [&](uint64_t value) { parsed.set_exec_main_status(value); }, INT32_MAX);
      numeric("ActiveEnterTimestampMonotonic", [&](uint64_t value) { parsed.set_active_enter_monotonic_ns(value * 1000); }, UINT64_MAX / 1000);
      numeric("ExecMainStartTimestampMonotonic", [&](uint64_t value) { parsed.set_exec_main_start_monotonic_ns(value * 1000); }, UINT64_MAX / 1000);
      const auto condition = props.find("ConditionResult");
      if (condition != props.end()) {
        if (condition->second != "yes" && condition->second != "no") throw std::runtime_error("Invalid service condition result");
        parsed.set_condition_result(condition->second == "yes");
      }
      const auto invocation = props.find("InvocationID");
      if (invocation != props.end() && !invocation->second.empty()) {
        if (invocation->second.size() != 32 || invocation->second.find_first_not_of("0123456789abcdef") != std::string::npos)
          throw std::runtime_error("Invalid service invocation identity");
        parsed.set_invocation_id(invocation->second);
      }
      parsed.set_quality(daphne::MEASUREMENT_GOOD);
      parsed.set_observed_host_unix_ns(host_ns);
      parsed.set_observed_monotonic_ns(mono_ns);
      parsed.set_message("systemd show observation; active/success is not sensor or timing health");
      item = parsed;
    } catch (const std::exception& e) { item.set_message(e.what()); }
    result.push_back(item);
  }
  return result;
}

void add_service_status(daphne::SystemStatusSnapshot& status) {
  // One query per second maximum. Cached observations retain their actual
  // read times; neither a request nor a failed query refreshes old evidence.
  static std::mutex mutex;
  static uint64_t attempted_ns = 0;
  static std::vector<daphne::ServiceStatus> cached;
  std::lock_guard<std::mutex> lock(mutex);
  const auto now = monotonic_time_ns();
  if (!attempted_ns || now < attempted_ns || now - attempted_ns >= 1'000'000'000ULL) {
    attempted_ns = now;
    try {
      const auto output = query_systemd();
      cached = parse_service_status(output, host_unix_time_ns(), monotonic_time_ns());
    } catch (const std::exception& e) {
      cached.clear();
      for (auto unit : kServiceUnits) {
        daphne::ServiceStatus item;
        item.set_name(unit);
        item.set_quality(daphne::MEASUREMENT_ERROR);
        item.set_message(e.what());
        cached.push_back(item);
      }
    }
  }
  for (const auto& item : cached) {
    *status.add_services() = item;
    if (item.name() == "daphne.service" && item.quality() == daphne::MEASUREMENT_GOOD &&
        item.has_main_pid() && item.main_pid() == static_cast<uint32_t>(getpid())) {
      status.set_server_instance_id(item.invocation_id());
      const auto start = item.exec_main_start_monotonic_ns();
      if (item.has_exec_main_start_monotonic_ns() && start && now >= start)
        status.set_server_uptime_ms((now - start) / 1'000'000);
    }
  }
}

void add_host_status(daphne::SystemStatusSnapshot& status, bool mezzanine_access_enabled) {
  *status.mutable_server_build() = server_build_info();
  utsname identity{};
  if (uname(&identity) == 0) {
    status.set_hostname(identity.nodename);
  }
  add_host_software(status);
  const auto app = read_assignment("/run/daphne-gateware/active.env", "APP");
  if (!app.empty() && app.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") == std::string::npos) {
    auto* configured = status.add_ps_values();
    configured->set_name("ConfiguredGatewareApp");
    configured->set_value(app);
    configured->set_valid(true);
    configured->set_source("/run/daphne-gateware/active.env:APP");
    configured->set_observed_unix_ns(host_unix_time_ns());
    configured->set_message("Configured app, not an independently observed xmutil inventory");
  }
  auto* population = status.add_ps_values();
  population->set_name("MezzanineAccessPolicy");
  population->set_value(mezzanine_access_enabled ? "enabled; population not inferred" : "disabled; operator declares none fitted");
  population->set_valid(true);
  population->set_source("daphneServer --no-mezzanines / DAPHNE_NO_MEZZANINES");
  population->set_observed_unix_ns(host_unix_time_ns());
  population->set_message("Operator configuration, not a bus scan or device-presence measurement");
}
}  // namespace daphne_sc
