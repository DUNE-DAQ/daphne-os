#include "BoardI2C.hpp"

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace fs = std::filesystem;
void require(bool value) { if (!value) throw std::runtime_error("I2C identity test failed"); }
template <typename F> void rejects(F function) {
  bool failed = false;
  try { function(); } catch (const std::exception&) { failed = true; }
  require(failed);
}
int main() {
  std::string pattern = (fs::temp_directory_path() / "daphne-i2c-test-XXXXXX").string();
  const auto* directory = mkdtemp(pattern.data());
  require(directory);
  const fs::path root(directory), devices = root / "devices", dev = root / "dev";
  struct Cleanup { fs::path path; ~Cleanup() { std::error_code ec; fs::remove_all(path, ec); } } cleanup{root};
  fs::create_directories(devices);
  fs::create_directories(dev);
  auto adapter = [&](const char* number, const char* address) {
    fs::create_directories(devices / number);
    fs::create_directories(root / address);
    fs::create_directory_symlink(root / address, devices / number / "of_node");
    std::ofstream(root / address / "compatible", std::ios::binary) << "cdns,i2c-r1p14" << '\0';
    std::ofstream(dev / number).put('\n');
  };
  rejects([&] { board_ps_i2c_adapter(devices, dev); });
  adapter("i2c-1", "i2c@9c000000"); // PL bus must never be the PS fallback.
  rejects([&] { board_ps_i2c_adapter(devices, dev); });
  adapter("i2c-42", "i2c@ff030000");
  require(board_ps_i2c_adapter(devices, dev) == (dev / "i2c-42").string());
  fs::remove(dev / "i2c-42");
  rejects([&] { board_ps_i2c_adapter(devices, dev); });
  std::ofstream(dev / "i2c-42").put('\n');
  std::ofstream(root / "i2c@ff030000/compatible") << "not-cdns,i2c-r1p14" << '\0';
  rejects([&] { board_ps_i2c_adapter(devices, dev); });
  adapter("i2c-43", "i2c@ff030000");
  rejects([&] { board_ps_i2c_adapter(devices, dev); });
  std::cout << "PS I2C identity, renumbering, missing, incompatible and ambiguous cases passed\n";
}
