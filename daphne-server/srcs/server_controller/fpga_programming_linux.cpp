#include "server_controller/fpga_health.hpp"
#include "server_controller/board_monitor.hpp"

#include <array>
#include <charconv>
#include <fstream>
#include <stdexcept>
#include <vector>

namespace daphne_sc {
namespace {
namespace fs = std::filesystem;
std::string bounded_read(const fs::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("Unavailable sysfs observation");
  std::array<char, 513> buffer{};
  input.read(buffer.data(), buffer.size());
  if (input.bad() || input.gcount() > 512)
    throw std::runtime_error("Invalid sysfs observation");
  return {buffer.data(), static_cast<size_t>(input.gcount())};
}
std::string text(const fs::path& path) {
  auto result = bounded_read(path);
  if (!result.empty() && result.back() == '\n') result.pop_back();
  if (result.empty() || result.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -x:") != std::string::npos)
    throw std::runtime_error("Invalid sysfs text");
  return result;
}
uint32_t config_word(const fs::path& path) {
  const auto value = text(path);
  if (value.size() < 3 || value.size() > 10 || value.substr(0, 2) != "0x")
    throw std::runtime_error("Invalid configuration status");
  uint32_t result = 0;
  const auto parsed = std::from_chars(value.data() + 2, value.data() + value.size(), result, 16);
  if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size())
    throw std::runtime_error("Invalid configuration status");
  return result;
}
bool compatible(const fs::path& path) {
  const auto value = bounded_read(path);
  size_t start = 0;
  bool found = false;
  while (start < value.size()) {
    const auto end = value.find('\0', start);
    if (end == std::string::npos || end == start)
      throw std::runtime_error("Invalid device-tree compatible");
    if (value.substr(start, end - start) == "xlnx,zynqmp-pcap-fpga") found = true;
    start = end + 1;
  }
  return found;
}
bool valid_state(const std::string& state) {
  static constexpr const char* states[] = {
    "unknown", "power off", "power up", "reset", "firmware request",
    "firmware request error", "parse header", "parse header error",
    "write init", "write init error", "write", "write error",
    "write complete", "write complete error", "operating"};
  for (const auto* allowed : states) if (state == allowed) return true;
  return false;
}
}

daphne::FpgaProgrammingStatus read_fpga_programming_status(const fs::path& root) {
  daphne::FpgaProgrammingStatus result;
  result.set_acquisition_started_monotonic_ns(monotonic_time_ns());
  result.set_source("Linux ZynqMP FPGA manager state; platform-device configuration STAT via PM firmware");
  result.set_message("Manager state is cached; manager-class status is intentionally not used (unsupported callback can return empty). "
                     "Configuration STAT is a separate sampled read, not continuous integrity or data-path proof");
  fs::path selected;
  try {
    std::vector<fs::path> matches;
    if (fs::exists(root)) {
      unsigned count = 0;
      for (const auto& entry : fs::directory_iterator(root)) {
        if (++count > 16) throw std::runtime_error("Excess manager entries");
        const auto name = entry.path().filename().string();
        if (name.size() <= 4 || name.substr(0, 4) != "fpga" ||
            name.find_first_not_of("0123456789", 4) != std::string::npos) continue;
        if (compatible(entry.path() / "device/of_node/compatible") &&
            text(entry.path() / "name") == "Xilinx ZynqMP FPGA Manager")
          matches.push_back(entry.path());
      }
    }
    if (matches.empty()) return result;
    if (matches.size() != 1) throw std::runtime_error("Ambiguous FPGA manager");
    selected = matches.front();
  } catch (const std::exception&) {
    result.set_manager_quality(daphne::MEASUREMENT_ERROR);
    result.set_configuration_quality(daphne::MEASUREMENT_ERROR);
    result.set_message("ZynqMP manager discovery failed or is ambiguous; no path/exception details exported");
    return result;
  }
  std::string original_state;
  try {
    original_state = text(selected / "state");
    auto state = original_state;
    const auto suffix = state.find(": 0x");
    if (suffix != std::string::npos) {
      const auto error = state.substr(suffix + 4);
      uint32_t code = 0;
      const auto parsed = std::from_chars(error.data(), error.data() + error.size(), code, 16);
      if (error.empty() || error.size() > 8 || parsed.ec != std::errc{} || parsed.ptr != error.data() + error.size() || code == 0)
        throw std::runtime_error("Invalid manager error code");
      result.set_manager_error_raw(code);
      state.resize(suffix);
    }
    if (!valid_state(state)) throw std::runtime_error("Unrecognized manager state");
    result.set_manager_state(state);
    result.set_manager_quality(daphne::MEASUREMENT_GOOD);
    result.set_manager_observed_monotonic_ns(monotonic_time_ns());
  } catch (const std::exception&) {
    result.set_manager_quality(daphne::MEASUREMENT_ERROR);
    result.clear_manager_error_raw();
  }
  // Do not initiate PM configuration readback while the kernel reports a load,
  // reset or unknown state. This is only a sampled prerequisite, not a lock.
  if (result.manager_quality() != daphne::MEASUREMENT_GOOD || result.manager_state() != "operating" || result.has_manager_error_raw()) return result;
  try {
    const auto raw = config_word(selected / "device/status");
    result.set_configuration_status_raw(raw); // A measured zero retains presence.
    result.set_configuration_quality(daphne::MEASUREMENT_GOOD);
    result.set_configuration_observed_monotonic_ns(monotonic_time_ns());
    const auto after = text(selected / "state");
    if (after != original_state) {
      result.set_manager_quality(daphne::MEASUREMENT_ERROR);
      result.set_configuration_quality(daphne::MEASUREMENT_ERROR);
      result.set_message("Manager state changed across configuration readback; retry with programming stopped");
    }
  } catch (const std::exception&) {
    result.set_configuration_quality(daphne::MEASUREMENT_ERROR);
  }
  return result;
}
}
