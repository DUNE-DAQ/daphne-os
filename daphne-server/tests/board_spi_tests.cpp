#include "BoardSPI.hpp"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
namespace fs = std::filesystem;
void require(bool ok) { if (!ok) throw std::runtime_error("SPI binding test failed"); }
template <typename F> void rejects(F f) { bool failed = false; try { f(); } catch (...) { failed = true; } require(failed); }
int main() {
  auto pattern = (fs::temp_directory_path() / "daphne-spi-test-XXXXXX").string();
  const auto* directory = mkdtemp(pattern.data());
  require(directory);
  const fs::path root(directory), devices = root / "devices", dev = root / "dev";
  struct Cleanup { fs::path path; ~Cleanup() { std::error_code ec; fs::remove_all(path, ec); } } cleanup{root};
  fs::create_directories(devices); fs::create_directories(dev); fs::create_directories(root / "spidev");
  auto create = [&](const std::string& name, const std::string& address) {
    const auto controller = root / address;
    fs::create_directories(controller / "spidev@0");
    std::ofstream(controller / "compatible", std::ios::binary) << "xlnx,xps-spi-2.00.a" << '\0';
    std::ofstream(controller / "spidev@0/reg", std::ios::binary) << std::string(4, '\0');
    fs::create_directories(devices / name);
    fs::create_directory_symlink(controller / "spidev@0", devices / name / "of_node");
    fs::create_directory_symlink(root / "spidev", devices / name / "driver");
    std::ofstream(dev / ("spidev" + name.substr(3))).put('\n');
  };
  rejects([&] { board_current_spi_device(devices, dev); });
  create("spi0.0", "spi@ff050000");
  rejects([&] { board_current_spi_device(devices, dev); });
  create("spi42.0", "axi_quad_spi@9c020000");
  require(board_current_spi_device(devices, dev) == (dev / "spidev42.0").string());
  fs::remove(dev / "spidev42.0");
  rejects([&] { board_current_spi_device(devices, dev); });
  std::ofstream(dev / "spidev42.0").put('\n');
  std::ofstream(root / "axi_quad_spi@9c020000/spidev@0/reg") << "bad";
  rejects([&] { board_current_spi_device(devices, dev); });
  std::ofstream(root / "axi_quad_spi@9c020000/spidev@0/reg", std::ios::binary) << std::string(4, '\0');
  fs::remove(devices / "spi42.0/driver");
  rejects([&] { board_current_spi_device(devices, dev); });
  fs::create_directory_symlink(root / "spidev", devices / "spi42.0/driver");
  std::ofstream(root / "axi_quad_spi@9c020000/compatible") << "not-xlnx,xps-spi-2.00.a" << '\0';
  rejects([&] { board_current_spi_device(devices, dev); });
  create("spi43.0", "axi_quad_spi@9c020000");
  rejects([&] { board_current_spi_device(devices, dev); });
  std::cout << "Current SPI controller/CS/driver identity, renumbering, missing and ambiguous cases passed\n";
}
