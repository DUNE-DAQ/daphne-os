#include "server_controller/ams_temperature.hpp"

#include <array>
#include <cmath>
#include <fstream>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "server_controller/board_monitor.hpp"

namespace daphne_sc {
namespace {
namespace fs = std::filesystem;

std::string read_text(const fs::path& path) {
  std::ifstream file(path);
  if (!file) throw std::runtime_error("Cannot read " + path.string());
  std::ostringstream text;
  text << file.rdbuf();
  if (file.bad()) throw std::runtime_error("Read failed: " + path.string());
  auto value = text.str();
  const auto begin = value.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) return {};
  return value.substr(begin, value.find_last_not_of(" \t\r\n") - begin + 1);
}

bool decimal(const std::string& text) {
  return !text.empty() && text.find_first_not_of("0123456789") == std::string::npos;
}

double read_celsius(const fs::path& path) {
  std::istringstream input(read_text(path));
  input.imbue(std::locale::classic());
  double milli_celsius;
  if (!(input >> milli_celsius)) throw std::runtime_error("Invalid IIO temperature input");
  input >> std::ws;
  if (!input.eof() || !std::isfinite(milli_celsius) || milli_celsius < -273150)
    throw std::runtime_error("Invalid IIO temperature input");
  // Linux IIO ABI: in_tempY_input is already scaled, in millidegrees Celsius.
  return milli_celsius / 1000.0;
}
}  // namespace

void add_ams_temperatures(daphne::SystemStatusSnapshot& status, const fs::path& root) {
  constexpr std::array<const char*, 3> labels{{"Temp_LPD", "Temp_FPD", "Temp_PL"}};
  std::vector<fs::path> devices;
  std::string discovery_error;
  try {
    if (fs::exists(root)) {
      for (const auto& entry : fs::directory_iterator(root)) {
        const auto name = entry.path().filename().string();
        // Device numbering is dynamic; match the chip identity instead.
        if (name.rfind("iio:device", 0) != 0 || !decimal(name.substr(10))) continue;
        if (read_text(entry.path() / "name") == "xilinx-ams") devices.push_back(entry.path());
      }
    }
  } catch (const std::exception& e) {
    discovery_error = e.what();
  }

  for (const auto* label : labels) {
    auto* result = status.add_temperatures();
    result->set_name(label);
    result->set_temperature_c(std::numeric_limits<double>::quiet_NaN());
    result->set_valid(false);
    result->set_quality(daphne::MEASUREMENT_UNAVAILABLE);
    result->set_source(std::string("Linux IIO xilinx-ams / ") + label);
    if (!discovery_error.empty()) {
      result->set_quality(daphne::MEASUREMENT_ERROR);
      result->set_message("IIO discovery failed: " + discovery_error);
      continue;
    }
    if (devices.size() != 1) {
      if (devices.size() > 1) result->set_quality(daphne::MEASUREMENT_ERROR);
      result->set_message(devices.empty() ? "No xilinx-ams IIO device discovered"
                                         : "Ambiguous xilinx-ams device identity");
      continue;
    }
    try {
      std::vector<fs::path> inputs;
      for (const auto& entry : fs::directory_iterator(devices.front())) {
        const auto name = entry.path().filename().string();
        if (name.rfind("in_temp", 0) != 0 || name.size() <= 13 ||
            name.compare(name.size() - 6, 6, "_label") != 0 ||
            !decimal(name.substr(7, name.size() - 13))) continue;
        if (read_text(entry.path()) == label)
          inputs.push_back(devices.front() / (name.substr(0, name.size() - 6) + "_input"));
      }
      if (inputs.empty()) {
        result->set_message("Named AMS temperature channel is unavailable");
        continue;
      }
      if (inputs.size() != 1) throw std::runtime_error("Ambiguous AMS temperature label");
      result->set_source(std::string("Linux IIO xilinx-ams / ") + label + " / " + inputs.front().string());
      const double value = read_celsius(inputs.front());
      result->set_observed_host_unix_ns(host_unix_time_ns());
      result->set_observed_monotonic_ns(monotonic_time_ns());
      result->set_temperature_c(value);
      result->set_valid(true);
      result->set_quality(daphne::MEASUREMENT_GOOD);
      result->set_message("SoC die temperature; sampled on request, not board ambient. "
                          "Times are host observations, not ADC conversion times");
    } catch (const std::exception& e) {
      result->set_quality(daphne::MEASUREMENT_ERROR);
      result->set_message(e.what());
    }
  }
}
}  // namespace daphne_sc
