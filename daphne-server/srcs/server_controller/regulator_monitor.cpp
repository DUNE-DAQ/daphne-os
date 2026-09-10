#include "server_controller/regulator_monitor.hpp"
#include "PmbusLinear.hpp"
#include <limits>
#include <optional>
#include <stdexcept>

namespace daphne_sc {
bool regulator_read_allowed(uint8_t command, unsigned width) {
  if (width == 8) switch (command) {
    case 0x19: case 0x20: case 0x7a: case 0x7b: case 0x7d: case 0x7e: case 0x98: return true;
  }
  if (width == 16) switch (command) {
    case 0x38: case 0x39: case 0x79: case 0x8b: case 0x8c: case 0x8e: case 0xd0: return true;
  }
  return false; // No PAGE, OPERATION, limits, CLEAR_FAULTS, writes, VIN or unqualified 0x80.
}

daphne::RegulatorMonitor unavailable_regulator(unsigned index, const std::string& reason) {
  const auto& route = kRegulatorRoutes.at(index);
  daphne::RegulatorMonitor r;
  r.set_name(route.name); r.set_schematic_reference(route.reference); r.set_address(route.address);
  r.set_source("DAPHNE_Mezz_V2 schematic sheets 11/12; PJT004A0X43-SRZ; PL I2C 9c000000; mandatory SMBus PEC");
  r.set_pec_required(true); r.set_identity_quality(daphne::MEASUREMENT_UNAVAILABLE);
  r.set_voltage_quality(daphne::MEASUREMENT_UNAVAILABLE); r.set_current_quality(daphne::MEASUREMENT_UNAVAILABLE);
  r.set_message(reason);
  auto& t = *r.mutable_temperature();
  t.set_name(std::string(route.reference) + " regulator READ_TEMPERATURE_2");
  t.set_source(r.source()); t.set_temperature_c(std::numeric_limits<double>::quiet_NaN());
  t.set_quality(daphne::MEASUREMENT_UNAVAILABLE); t.set_message(reason);
  auto* missing = r.add_registers();
  missing->set_name("STATUS_MFR_SPECIFIC"); missing->set_command(0x80); missing->set_width_bits(8);
  missing->set_quality(daphne::MEASUREMENT_UNAVAILABLE);
  missing->set_message("Documented command, but repeated PEC read failed on DAPHNE-015; not qualified. Not retried during monitoring; not zero or proof of unsupported hardware");
  return r;
}

namespace {
using Identity = std::array<std::optional<uint16_t>, 4>;
bool supported(const Identity& v) {
  for (auto value : v) if (!value) return false;
  return (*v[0] & 0xfc) == 0x54 && *v[1] == 0x11 && (*v[2] & 0x80) && *v[3] == 0x17;
}
void status_flags(daphne::RegulatorMonitor& r, const std::string& name, uint8_t command, uint16_t raw) {
  auto flag = [&](uint16_t mask, const char* label) {
    if (raw & mask) r.add_asserted_status_flags(name + ": " + label);
  };
  switch (command) {
    case 0x79:
      flag(0x8000, "VOUT"); flag(0x4000, "IOUT_POUT"); flag(0x1000, "MANUFACTURER");
      flag(0x0800, "POWER_NOT_GOOD"); flag(0x0040, "OFF"); flag(0x0020, "VOUT_OV");
      flag(0x0010, "IOUT_OC"); flag(0x0008, "VIN_UV"); flag(0x0004, "TEMPERATURE");
      flag(0x0002, "CML"); flag(0x2781, "OTHER_OR_UNDOCUMENTED_BITS"); break;
    case 0x7a: flag(0x80, "VOUT_OV"); flag(0x10, "VOUT_UV"); flag(0x6f, "UNDOCUMENTED_BITS"); break;
    case 0x7b: flag(0x80, "IOUT_OC_FAULT"); flag(0x20, "IOUT_OC_WARNING"); flag(0x5f, "UNDOCUMENTED_BITS"); break;
    case 0x7d: flag(0x80, "OT_FAULT"); flag(0x40, "OT_WARNING"); flag(0x3f, "UNDOCUMENTED_BITS"); break;
    case 0x7e:
      flag(0x80, "INVALID_COMMAND"); flag(0x40, "INVALID_DATA"); flag(0x20, "PEC_FAILURE");
      flag(0x10, "MEMORY_FAULT"); flag(0x02, "OTHER_COMMUNICATION_FAULT"); flag(0x0d, "UNDOCUMENTED_BITS"); break;
  }
}
} // namespace

daphne::RegulatorMonitor collect_regulator(unsigned index, const RegulatorIO& io) {
  auto r = unavailable_regulator(index, "Acquisition not completed");
  if (!io.read_byte || !io.read_word || !io.now || !io.unix_now)
    throw std::invalid_argument("Incomplete regulator reader");
  const auto started = io.now();
  r.set_acquisition_started_monotonic_ns(started);
  bool stale = false;
  auto last_clock = started;
  auto stamp = [&] {
    const auto now = io.now();
    stale |= !now || now < last_clock;
    last_clock = now;
    return now;
  };
  auto read = [&](const std::string& name, uint8_t command, unsigned width) -> std::optional<uint16_t> {
    if (!regulator_read_allowed(command, width)) throw std::invalid_argument("PMBus read outside qualified allowlist");
    auto* field = r.add_registers();
    field->set_name(name); field->set_command(command); field->set_width_bits(width);
    auto elapsed = [&](uint64_t now) {
      return started && now >= started && now - started <= kRegulatorMaximumAcquisitionNs;
    };
    const auto attempted = stamp();
    if (stale || !elapsed(attempted)) {
      stale = true; field->set_quality(daphne::MEASUREMENT_STALE);
      field->set_message("Acquisition time budget expired or monotonic time invalid; read not attempted");
      return {};
    }
    try {
      const uint16_t value = width == 8 ? io.read_byte(command) : io.read_word(command);
      const auto observed = stamp();
      field->set_raw(value); field->set_observed_monotonic_ns(observed);
      if (stale || !elapsed(observed)) {
        stale = true; field->set_quality(daphne::MEASUREMENT_STALE);
        field->set_message("Read completed outside acquisition age budget; raw evidence retained"); return {};
      }
      field->set_quality(daphne::MEASUREMENT_GOOD);
      return value;
    } catch (const std::exception&) {
      field->set_quality(daphne::MEASUREMENT_ERROR);
      field->set_message("PEC-protected SMBus read failed; no fallback or fault-clear write");
      return {};
    }
  };
  auto identity = [&](const char* suffix) -> Identity {
    return {read(std::string("MFR_SPECIFIC_00_") + suffix, 0xd0, 16),
            read(std::string("PMBUS_REVISION_") + suffix, 0x98, 8),
            read(std::string("CAPABILITY_") + suffix, 0x19, 8),
            read(std::string("VOUT_MODE_") + suffix, 0x20, 8)};
  };
  auto finish = [&] {
    r.set_observed_monotonic_ns(stamp()); r.set_observed_host_unix_ns(io.unix_now());
  };
  const auto before = identity("BEFORE");
  if (!supported(before)) {
    r.set_identity_quality(stale ? daphne::MEASUREMENT_STALE : daphne::MEASUREMENT_ERROR);
    r.set_message("Module type, PMBus 1.1, PEC capability or qualified VOUT_MODE not verified; telemetry not attempted");
    r.mutable_temperature()->set_message(r.message()); finish(); return r;
  }
  const auto cml_before = read("STATUS_CML_BEFORE", 0x7e, 8);
  const auto status_before = read("STATUS_WORD_BEFORE", 0x79, 16);
  const auto voltage = read("READ_VOUT", 0x8b, 16);
  const auto current = read("READ_IOUT", 0x8c, 16);
  const auto temperature = read("READ_TEMPERATURE_2", 0x8e, 16);
  const auto temperature_time = r.registers(r.registers_size() - 1).observed_monotonic_ns();
  read("IOUT_CAL_GAIN", 0x38, 16); read("IOUT_CAL_OFFSET", 0x39, 16); // Raw factory calibration, never applied twice.
  read("STATUS_VOUT", 0x7a, 8); read("STATUS_IOUT", 0x7b, 8); read("STATUS_TEMPERATURE", 0x7d, 8);
  const auto cml_after = read("STATUS_CML_AFTER", 0x7e, 8);
  const auto status_after = read("STATUS_WORD_AFTER", 0x79, 16);
  const auto after = identity("AFTER");
  finish();
  stale |= !started || r.observed_monotonic_ns() < started ||
           r.observed_monotonic_ns() - started > kRegulatorMaximumAcquisitionNs;
  if (stale || before != after || !supported(after)) {
    const auto quality = stale ? daphne::MEASUREMENT_STALE : daphne::MEASUREMENT_ERROR;
    r.set_identity_quality(quality); r.set_voltage_quality(quality); r.set_current_quality(quality);
    r.mutable_temperature()->set_quality(quality);
    r.set_message("Identity/mode bracket failed or acquisition expired; raw evidence retained, decoded measurements withheld");
    r.mutable_temperature()->set_message(r.message()); return r;
  }
  r.set_identity_quality(daphne::MEASUREMENT_GOOD); r.set_identity_bracket_verified(true);
  r.set_voltage_quality(daphne::MEASUREMENT_ERROR); r.set_current_quality(daphne::MEASUREMENT_ERROR);
  if (voltage) {
    const double value = pmbus_linear16(*voltage, *before[3]);
    if (value >= 0 && value <= 6) { r.set_output_voltage_v(value); r.set_voltage_quality(daphne::MEASUREMENT_GOOD); }
  }
  if (current && (*current >> 11) == 28) { // Qualified PJT READ_IOUT exponent -4.
    const double value = pmbus_linear11(*current);
    if (value >= 0 && value <= 6) { r.set_output_current_a(value); r.set_current_quality(daphne::MEASUREMENT_GOOD); }
  }
  auto& t = *r.mutable_temperature();
  t.set_quality(daphne::MEASUREMENT_ERROR);
  t.set_message("READ_TEMPERATURE_2 unavailable/invalid; not an ambient or SoC die measurement");
  if (temperature && (*temperature >> 11) == 0) {
    const double value = pmbus_linear11(*temperature);
    if (value >= -273.15 && value <= 1000) {
      t.set_temperature_c(value); t.set_valid(true); t.set_quality(daphne::MEASUREMENT_GOOD);
      t.set_observed_monotonic_ns(temperature_time); t.set_observed_host_unix_ns(r.observed_host_unix_ns());
      t.set_message("PJT READ_TEMPERATURE_2; sensor placement not independently verified. Host time, not conversion time");
    }
  }
  if (cml_before && cml_after && status_before && status_after)
    r.set_status_changed(cml_before != cml_after || status_before != status_after);
  for (const auto& field : r.registers()) if (field.has_raw() && field.quality() == daphne::MEASUREMENT_GOOD)
    status_flags(r, field.name(), field.command(), field.raw());
  r.set_message("Sequential PEC-checked reads with matching type/revision/mode, not an atomic snapshot or unique module identity. "
                "Check each field: invalid/out-of-range VOUT/IOUT are withheld; factory calibration is raw and not reapplied. "
                "Flags may be latched/historical and are not cleared. VIN and manufacturer-specific status are unqualified; no overall health claim");
  return r;
}
} // namespace daphne_sc
