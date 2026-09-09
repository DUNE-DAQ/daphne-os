#include "BoardI2C.hpp"

#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>

std::string board_ps_i2c_adapter(const std::filesystem::path& devices,
                               const std::filesystem::path& dev) {
  namespace fs = std::filesystem;
  std::vector<fs::path> matches;
  for (const auto& entry : fs::directory_iterator(devices)) {
    const auto name = entry.path().filename().string();
    if (name.rfind("i2c-", 0) != 0 || name.size() <= 4 ||
        name.find_first_not_of("0123456789", 4) != std::string::npos) continue;
    const auto node = entry.path() / "of_node";
    if (!fs::exists(node)) continue;
    if (fs::canonical(node).filename() != "i2c@ff030000") continue;
    std::ifstream file(node / "compatible", std::ios::binary);
    if (!file) throw std::runtime_error("Cannot verify PS I2C controller compatibility");
    const std::string compatible{std::istreambuf_iterator<char>(file), {}};
    // Require a complete NUL-separated OF compatible entry, not a substring.
    bool cadence = false;
    for (size_t begin = 0; begin < compatible.size();) {
      const auto end = compatible.find('\0', begin);
      if (end == std::string::npos) break;
      cadence |= compatible.substr(begin, end - begin) == "cdns,i2c-r1p14";
      begin = end + 1;
    }
    if (!cadence) throw std::runtime_error("Unexpected PS I2C controller compatibility");
    if (!fs::exists(dev / name)) throw std::runtime_error("PS I2C adapter has no device node");
    matches.push_back(dev / name);
  }
  if (matches.size() != 1)
    throw std::runtime_error("Expected exactly one PS I2C controller at ff030000; no bus fallback or scan");
  return matches.front().string();
}
