#include "BoardSPI.hpp"
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace {
std::string bytes(const std::filesystem::path& path) {
  std::ifstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("Cannot verify current-monitor SPI device tree");
  return {std::istreambuf_iterator<char>(f), {}};
}
bool compatible(const std::string& value, const std::string& expected) {
  for (size_t start = 0; start < value.size();) {
    const auto end = value.find('\0', start);
    if (end == std::string::npos) break;
    if (value.substr(start, end - start) == expected) return true;
    start = end + 1;
  }
  return false;
}
}
std::string board_current_spi_device(const std::filesystem::path& devices,
                                      const std::filesystem::path& dev) {
  namespace fs = std::filesystem;
  std::vector<fs::path> matches;
  for (const auto& entry : fs::directory_iterator(devices)) {
    const auto name = entry.path().filename().string();
    if (name.size() < 6 || name.rfind("spi", 0) != 0 || name.substr(name.size() - 2) != ".0" ||
        name.substr(3, name.size() - 5).find_first_not_of("0123456789") != std::string::npos) continue;
    if (!fs::exists(entry.path() / "of_node")) continue;
    const auto node = fs::canonical(entry.path() / "of_node");
    if (node.parent_path().filename() != "axi_quad_spi@9c020000") continue;
    if (!compatible(bytes(node.parent_path() / "compatible"), "xlnx,xps-spi-2.00.a") ||
        bytes(node / "reg") != std::string(4, '\0'))
      throw std::runtime_error("Unexpected current-monitor SPI controller or chip select");
    if (!fs::exists(entry.path() / "driver") || fs::canonical(entry.path() / "driver").filename() != "spidev")
      throw std::runtime_error("Current-monitor SPI device is not owned by spidev; no MMIO fallback");
    const auto device = dev / ("spidev" + name.substr(3));
    if (!fs::exists(device)) throw std::runtime_error("Current-monitor spidev node missing");
    matches.push_back(device);
  }
  if (matches.size() != 1)
    throw std::runtime_error("Expected one current-monitor SPI device at 9c020000 CS0; no bus fallback");
  return matches.front().string();
}
