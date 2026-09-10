#include "BoardI2C.hpp"

#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace {
std::string adapter(const std::filesystem::path& devices,
                    const std::filesystem::path& dev,
                    const char* node_name, const char* expected_compatible) {
  namespace fs = std::filesystem;
  std::vector<fs::path> matches;
  for (const auto& entry : fs::directory_iterator(devices)) {
    const auto name = entry.path().filename().string();
    if (name.rfind("i2c-", 0) != 0 || name.size() <= 4 ||
        name.find_first_not_of("0123456789", 4) != std::string::npos) continue;
    const auto node = entry.path() / "of_node";
    if (!fs::exists(node)) continue;
    if (fs::canonical(node).filename() != node_name) continue;
    std::ifstream file(node / "compatible", std::ios::binary);
    if (!file) throw std::runtime_error("Cannot verify I2C controller compatibility");
    const std::string compatible{std::istreambuf_iterator<char>(file), {}};
    // Require a complete NUL-separated OF compatible entry, not a substring.
    bool matched = false;
    for (size_t begin = 0; begin < compatible.size();) {
      const auto end = compatible.find('\0', begin);
      if (end == std::string::npos) break;
      matched |= compatible.substr(begin, end - begin) == expected_compatible;
      begin = end + 1;
    }
    if (!matched) throw std::runtime_error("Unexpected I2C controller compatibility");
    if (!fs::exists(dev / name)) throw std::runtime_error("I2C adapter has no device node");
    matches.push_back(dev / name);
  }
  if (matches.size() != 1)
    throw std::runtime_error(std::string("Expected exactly one I2C controller ") + node_name + "; no bus fallback or scan");
  return matches.front().string();
}
} // namespace
std::string board_ps_i2c_adapter(const std::filesystem::path& devices, const std::filesystem::path& dev) {
  return adapter(devices, dev, "i2c@ff030000", "cdns,i2c-r1p14");
}
std::string board_pl_i2c_adapter(const std::filesystem::path& devices, const std::filesystem::path& dev) {
  return adapter(devices, dev, "i2c@9c000000", "xlnx,xps-iic-2.00.a");
}
