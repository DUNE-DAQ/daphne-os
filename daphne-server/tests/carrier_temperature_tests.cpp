#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <utility>

#include "server_controller/carrier_temperature.hpp"

void require(bool value) { if (!value) throw std::runtime_error("Carrier temperature test failed"); }
int main() {
  using namespace daphne_sc;
  std::array<uint16_t, 8> registers{};
  registers[6] = 0x0054;
  registers[7] = 0x0400;
  std::vector<uint8_t> reads;
  auto read = [&](uint8_t address) { reads.push_back(address); return registers.at(address); };
  registers[5] = 0xc1fd;
  require(read_mcp9808_celsius(read) == 31.8125);
  require(reads == std::vector<uint8_t>({6, 7, 1, 5}));
  for (unsigned flags = 0; flags < 8; ++flags) {
    registers[5] = (flags << 13) | 0x1ff0;
    require(read_mcp9808_celsius(read) == -1.0);
    registers[5] = flags << 13;
    require(read_mcp9808_celsius(read) == 0);
  }
  for (auto invalid : {std::pair<unsigned, uint16_t>{6, 0}, {7, 0}, {1, 0x100}}) {
    const auto previous = registers[invalid.first];
    registers[invalid.first] = invalid.second;
    reads.clear();
    bool rejected = false;
    try { read_mcp9808_celsius(read); } catch (const std::exception&) { rejected = true; }
    require(rejected);
    require(reads.back() != 5); // No data read after identity/shutdown failure.
    registers[invalid.first] = previous;
  }
  daphne::TemperatureStatus source;
  source.set_temperature_c(31.8125);
  source.set_quality(daphne::MEASUREMENT_GOOD);
  source.set_source("Carrier U9 MCP9808");
  source.set_message("test");
  daphne::GeneralInfo info, decoded;
  set_general_info_temperature(info, source);
  require(decoded.ParseFromString(info.SerializeAsString()));
  require(decoded.temperature() == 31.8125 && decoded.temperature_quality() == daphne::MEASUREMENT_GOOD);
  source.set_temperature_c(NAN);
  source.set_quality(daphne::MEASUREMENT_ERROR);
  set_general_info_temperature(info, source);
  require(std::isnan(info.temperature()) && info.temperature_quality() == daphne::MEASUREMENT_ERROR);
  std::cout << "Carrier identity, signed decode, flags, zero, shutdown, source and wire tests passed\n";
}
