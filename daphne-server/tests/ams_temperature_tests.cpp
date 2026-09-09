#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

#include "server_controller/ams_temperature.hpp"

namespace {
namespace fs = std::filesystem;
void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}
struct Fixture {
  fs::path root;
  Fixture() {
    std::string pattern = (fs::temp_directory_path() / "daphne-ams-test-XXXXXX").string();
    auto* directory = mkdtemp(pattern.data());
    if (!directory) throw std::runtime_error("Cannot create fixture");
    root = directory;
  }
  ~Fixture() { std::error_code error; fs::remove_all(root, error); }
  void write(const std::string& relative, const std::string& text) {
    auto path = root / relative;
    fs::create_directories(path.parent_path());
    std::ofstream file(path);
    file << text;
    require(bool(file), "Cannot write fixture");
  }
  daphne::SystemStatusSnapshot read() const {
    daphne::SystemStatusSnapshot result;
    daphne_sc::add_ams_temperatures(result, root);
    require(result.temperatures_size() == 3, "Expected three named channels");
    return result;
  }
};
void unavailable(const daphne::TemperatureStatus& item, daphne::MeasurementQuality quality) {
  require(!item.valid() && item.quality() == quality, "Wrong invalid quality");
  require(std::isnan(item.temperature_c()), "Missing value must be NaN, not zero");
  require(!item.observed_monotonic_ns() && !item.observed_host_unix_ns(), "Invented observation time");
  require(!item.message().empty() && !item.source().empty(), "Missing provenance/detail");
}
}  // namespace

int main() {
  Fixture fixture;
  const auto initial = fixture.read();
  for (const auto& item : initial.temperatures())
    unavailable(item, daphne::MEASUREMENT_UNAVAILABLE);
  daphne::SystemStatusSnapshot missing;
  daphne_sc::add_ams_temperatures(missing, fixture.root / "absent");
  unavailable(missing.temperatures(0), daphne::MEASUREMENT_UNAVAILABLE);

  // Ignore unknown devices even when they expose tempting channel labels.
  fixture.write("iio:device0/name", "not-an-ams\n");
  fixture.write("iio:device0/in_temp7_label", "Temp_LPD\n");
  fixture.write("iio:device0/in_temp7_input", "99999\n");
  fixture.write("iio:device42/name", "xilinx-ams\n");
  fixture.write("iio:device42/in_temp107_label", "Temp_LPD\n");
  fixture.write("iio:device42/in_temp107_input", "39494\n");
  fixture.write("iio:device42/in_temp6_label", "Temp_FPD\n");
  fixture.write("iio:device42/in_temp6_input", "0\n");
  fixture.write("iio:device42/in_temp91_label", "Temp_PL\n");
  fixture.write("iio:device42/in_temp91_input", "-1250\n");
  fixture.write("iio:device42/in_temp91_raw", "999999\n"); // Do not double-scale.
  const auto good = fixture.read();
  require(good.temperatures(0).name() == "Temp_LPD", "Wrong sensor order");
  require(good.temperatures(1).name() == "Temp_FPD", "Wrong sensor order");
  require(good.temperatures(2).name() == "Temp_PL", "Wrong sensor order");
  require(good.temperatures(0).temperature_c() == 39.494, "Wrong milliC conversion");
  require(good.temperatures(1).temperature_c() == 0, "Real zero must be valid");
  require(good.temperatures(2).temperature_c() == -1.25, "Negative temperature rejected");
  for (const auto& item : good.temperatures()) {
    require(item.valid() && item.quality() == daphne::MEASUREMENT_GOOD, "Expected good measurement");
    require(item.observed_monotonic_ns() && item.observed_host_unix_ns(), "Missing observation times");
    require(item.source().find("iio:device42/in_temp") != std::string::npos, "Missing actual input path");
  }
  // Every request reads anew; no retained good value after a read error.
  fixture.write("iio:device42/in_temp107_input", "40500\n");
  require(fixture.read().temperatures(0).temperature_c() == 40.5, "Stale cached value");
  for (const auto* bad : {"", "nan", "inf", "40000garbage", "1e9999", "-273151", "3 4"}) {
    fixture.write("iio:device42/in_temp107_input", bad);
    const auto result = fixture.read();
    unavailable(result.temperatures(0), daphne::MEASUREMENT_ERROR);
    require(result.temperatures(1).valid() && result.temperatures(2).valid(), "One bad channel broke others");
  }
  fs::remove(fixture.root / "iio:device42/in_temp107_input");
  unavailable(fixture.read().temperatures(0), daphne::MEASUREMENT_ERROR);
  fs::remove(fixture.root / "iio:device42/in_temp107_label");
  unavailable(fixture.read().temperatures(0), daphne::MEASUREMENT_UNAVAILABLE);
  fixture.write("iio:device42/in_temp92_label", "Temp_PL");
  unavailable(fixture.read().temperatures(2), daphne::MEASUREMENT_ERROR);
  fixture.write("iio:device43/name", "xilinx-ams\n");
  const auto ambiguous = fixture.read();
  for (const auto& item : ambiguous.temperatures()) unavailable(item, daphne::MEASUREMENT_ERROR);
  daphne::SystemStatusSnapshot decoded;
  require(decoded.ParseFromString(ambiguous.SerializeAsString()), "Wire parse failed");
  unavailable(decoded.temperatures(0), daphne::MEASUREMENT_ERROR);
  require(decoded.ParseFromString(good.SerializeAsString()), "Wire parse failed");
  require(decoded.temperatures(0).temperature_c() == 39.494 && decoded.temperatures(0).valid(), "Wire value changed");
  std::cout << "AMS identity, renumbering, units, freshness, missing/error and wire tests passed\n";
}
