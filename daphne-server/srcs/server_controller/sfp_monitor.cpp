#include "server_controller/sfp_monitor.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <exception>
#include <limits>
#include <stdexcept>

namespace daphne_sc {
namespace {
using Bytes = std::vector<uint8_t>;
void require(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
uint16_t word(const Bytes& bytes, size_t p) { return (uint16_t(bytes.at(p)) << 8) | bytes.at(p + 1); }
int signed_word(uint16_t v) { return int(v) - ((v & 0x8000) ? 65536 : 0); }
bool checksum(const Bytes& b, size_t first, size_t last) {
  unsigned sum = 0;
  for (size_t i = first; i < last; ++i) sum += b.at(i);
  return (sum & 255) == b.at(last);
}
std::string ascii(const Bytes& b, size_t first, size_t count) {
  // SFF-8472 permits all-zero unspecified vendor fields; not embedded NULs.
  if (std::all_of(b.begin() + first, b.begin() + first + count, [](uint8_t v) { return v == 0; })) return {};
  std::string s;
  for (size_t i = first; i < first + count; ++i) {
    require(b.at(i) >= 32 && b.at(i) <= 126, "SFP inventory contains non-printable ASCII");
    s += char(b[i]);
  }
  while (!s.empty() && s.back() == ' ') s.pop_back();
  return s;
}
std::string raw(const Bytes& b) { return {b.begin(), b.end()}; }
Bytes read(const SfpIO& io, uint8_t device, unsigned offset, unsigned count) {
  require((device == 0x50 || device == 0x51) && count && offset + count <= 128,
          "SFP read outside allow-listed lower EEPROM region");
  Bytes result;
  while (count) {
    const auto n = std::min(count, 32u);
    const auto b = io.read_eeprom(device, uint8_t(offset), n);
    require(b.size() == n, "Short SFP EEPROM read");
    result.insert(result.end(), b.begin(), b.end());
    offset += n;
    count -= n;
  }
  return result;
}
class Route {
 public:
  explicit Route(const SfpIO& io) : io_(io), previous_(io.read_mux()) {
    require((previous_ & 0xc0) == 0 && (previous_ == 0 || (previous_ & (previous_ - 1)) == 0),
            "SFP mux has an unexpected multi-channel/unused route; unchanged");
  }
  ~Route() {
    if (!armed_) return;
    try { restore(); } catch (...) { try { io_.write_mux(0); } catch (...) {} }
  }
  void select(unsigned channel) {
    selected_ = uint8_t(1u << channel);
    armed_ = true; // A failed write may have reached the device.
    set(0);
    set(selected_);
  }
  void verify() { require(io_.read_mux() == selected_, "SFP mux changed during acquisition"); }
  uint8_t previous() const { return previous_; }
  void restore() { if (armed_) { set(0); set(previous_); armed_ = false; } }
 private:
  void set(uint8_t route) {
    io_.write_mux(route); // Separate completed transfer/STOP before readback or downstream access.
    require(io_.read_mux() == route, "SFP mux route readback mismatch");
  }
  const SfpIO& io_;
  uint8_t previous_, selected_ = 0;
  bool armed_ = false;
};
void invalidate(daphne::SFPMonitor& r, const std::string& error, bool identity) {
  r.set_diagnostic_quality(daphne::MEASUREMENT_ERROR);
  r.set_message(error);
  r.clear_temperature_c(); r.clear_vcc_v(); r.clear_tx_bias_ma();
  r.clear_tx_power_mw(); r.clear_rx_power_mw();
  r.clear_data_ready(); r.clear_tx_disabled(); r.clear_tx_fault(); r.clear_loss_of_signal();
  for (auto& q : *r.mutable_quantities()) {
    q.set_quality(daphne::MEASUREMENT_ERROR); q.clear_value();
    q.set_threshold_quality(daphne::MEASUREMENT_ERROR);
    q.clear_high_alarm(); q.clear_low_alarm(); q.clear_high_warning(); q.clear_low_warning();
    q.clear_high_alarm_flag(); q.clear_low_alarm_flag(); q.clear_high_warning_flag(); q.clear_low_warning_flag();
    q.set_detail(error);
  }
  if (identity) {
    r.set_identity_quality(daphne::MEASUREMENT_ERROR);
    r.clear_present(); r.clear_vendor(); r.clear_part(); r.clear_revision(); r.clear_serial(); r.clear_date_code();
    r.clear_vendor_oui(); r.clear_nominal_signaling_rate_mbd(); r.clear_wavelength_nm(); r.clear_dom_supported();
    r.clear_rate_select_raw();
  }
}
double ieee_float(const Bytes& b, size_t p) {
  static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559, "IEEE binary32 required");
  const uint32_t bits = (uint32_t(word(b, p)) << 16) | word(b, p + 2);
  float value;
  std::memcpy(&value, &bits, 4);
  require(std::isfinite(value), "Invalid SFP external floating-point calibration");
  return value;
}
double convert(const Bytes& constants, bool external, unsigned index, uint16_t code) {
  constexpr std::array<double, 5> scale{{1.0 / 256, 0.0001, 0.002, 0.0001, 0.0001}};
  double v = index == 0 ? signed_word(code) : code;
  if (external) {
    if (index == 4) {
      v = 0;
      for (size_t p = 56; p <= 72; p += 4) v = v * code + ieee_float(constants, p);
    } else {
      constexpr std::array<size_t, 4> slopes{{84, 88, 76, 80}};
      const auto p = slopes.at(index);
      const auto slope = word(constants, p);
      require(slope != 0, "Zero SFP external calibration slope");
      v = v * (slope / 256.0) + signed_word(word(constants, p + 2));
    }
  }
  v *= scale.at(index);
  require(std::isfinite(v), "Non-finite calibrated SFP diagnostic");
  return v;
}
void identity(daphne::SFPMonitor& r, const Bytes& a0) {
  r.set_a0_raw(raw(a0));
  r.set_base_checksum_valid(checksum(a0, 0, 63));
  r.set_extended_checksum_valid(checksum(a0, 64, 95));
  require(r.base_checksum_valid() && r.extended_checksum_valid(), "SFP identity checksum failure; presence is unknown");
  require(a0[0] == 3 && a0[1] == 4, "Unsupported module identifier/extended identifier");
  r.set_vendor(ascii(a0, 20, 16)); r.set_part(ascii(a0, 40, 16));
  r.set_revision(ascii(a0, 56, 4)); r.set_serial(ascii(a0, 68, 16));
  r.set_date_code(ascii(a0, 84, 8));
  r.set_diagnostic_type(a0[92]); r.set_enhanced_options(a0[93]); r.set_standard_revision(a0[94]);
  const unsigned oui = (unsigned(a0[37]) << 16) | (unsigned(a0[38]) << 8) | a0[39];
  if (oui) r.set_vendor_oui(oui);
  const unsigned rate = a0[12] == 255 ? a0[66] * 250u : a0[12] * 100u;
  if (rate) r.set_nominal_signaling_rate_mbd(rate);
  if (!(a0[8] & 0x0c) && word(a0, 60)) r.set_wavelength_nm(word(a0, 60));
  r.set_dom_supported(bool(a0[92] & 0x40));
  r.set_present(true);
  r.set_identity_quality(daphne::MEASUREMENT_GOOD);
}
void diagnostics(daphne::SFPMonitor& r, const Bytes& a0, const SfpIO& io) {
  const auto type = a0[92], options = a0[93];
  if (!(type & 0x40) || (type & 0x84)) {
    r.set_calibration(daphne::SFP_CALIBRATION_UNSUPPORTED);
    r.set_message(!(type & 0x40) ? "Identified module does not advertise digital diagnostics" :
        "Legacy/address-change diagnostics unsupported: no general-call, address or module-control writes");
    return;
  }
  const bool external = type & 0x10;
  require(((type & 0x30) == 0x10) || ((type & 0x30) == 0x20), "SFP calibration mode missing or contradictory");
  r.set_calibration(external ? daphne::SFP_CALIBRATION_EXTERNAL : daphne::SFP_CALIBRATION_INTERNAL);
  r.set_rx_power_is_oma(!(type & 8));
  r.set_diagnostic_eeprom_readable(false);
  const auto constants = read(io, 0x51, 0, 96);
  r.set_a2_static_raw(raw(constants));
  r.set_diagnostic_checksum_valid(checksum(constants, 0, 95));
  require(r.diagnostic_checksum_valid(), "SFP diagnostic checksum mismatch (may reflect startup-only checksum after enhanced-control changes); values withheld");
  const auto before = read(io, 0x51, 110, 1)[0];
  const auto live = read(io, 0x51, 96, 16);
  const auto after = read(io, 0x51, 110, 1)[0];
  r.set_diagnostic_eeprom_readable(true);
  r.set_a2_monitor_raw(raw(live));
  r.set_status_a2_0x6e(live[14]); r.set_status_a2_0x6f(live[15]);
  r.set_data_ready(!((before | live[14] | after) & 1));
  if (!r.data_ready()) {
    r.set_message("SFP Data_Not_Ready asserted; no diagnostic values reported");
    return;
  }
  require(before == live[14] && after == live[14], "SFP status changed while diagnostics were read");
  r.set_diagnostics_observed_monotonic_ns(io.now());
  r.set_rate_select_raw((live[14] >> 3) & 7);
  if (options & 0x40) r.set_tx_disabled(bool(live[14] & 0xc0)); // Hard OR soft disable.
  if (options & 0x20) r.set_tx_fault(bool(live[14] & 4));
  if (options & 0x10) r.set_loss_of_signal(bool(live[14] & 2));
  unsigned alarms = 0, warnings = 0;
  if (options & 0x80) {
    alarms = word(read(io, 0x51, 112, 2), 0);
    warnings = word(read(io, 0x51, 116, 2), 0);
    r.set_alarm_flags(alarms); r.set_warning_flags(warnings);
    r.set_flags_observed_monotonic_ns(io.now());
    if ((alarms | warnings) & 0xffc0) {
      io.wait(100000000);
      const auto second_a = word(read(io, 0x51, 112, 2), 0);
      const auto second_w = word(read(io, 0x51, 116, 2), 0);
      r.set_alarm_flags_second(second_a); r.set_warning_flags_second(second_w);
      r.set_flags_second_monotonic_ns(io.now());
      require(r.flags_second_monotonic_ns() >= r.flags_observed_monotonic_ns() &&
          r.flags_second_monotonic_ns() - r.flags_observed_monotonic_ns() >= 100000000,
          "SFP flag confirmation delay was not met");
      alarms |= second_a; warnings |= second_w;
    }
  }
  constexpr std::array<const char*, 5> names{{"temperature", "vcc", "tx_bias", "tx_power", "rx_power"}};
  constexpr std::array<const char*, 5> units{{"degC", "V", "mA", "mW", "mW"}};
  r.set_diagnostic_quality(daphne::MEASUREMENT_GOOD);
  for (unsigned i = 0; i < 5; ++i) {
    auto& q = *r.add_quantities();
    q.set_name(names[i]); q.set_units(units[i]); q.set_raw_code(word(live, i * 2));
    q.set_quality(daphne::MEASUREMENT_ERROR); q.set_threshold_quality(daphne::MEASUREMENT_ERROR);
    if (options & 0x80) {
      q.set_high_alarm_flag(alarms & (0x8000u >> (2 * i)));
      q.set_low_alarm_flag(alarms & (0x4000u >> (2 * i)));
      q.set_high_warning_flag(warnings & (0x8000u >> (2 * i)));
      q.set_low_warning_flag(warnings & (0x4000u >> (2 * i)));
    }
    try {
      const auto v = convert(constants, external, i, q.raw_code());
      require((i == 0 && v >= -128 && v < 128) || (i != 0 && v >= 0), "SFP calibrated value outside physical encoding range");
      if (i == 3 && r.has_tx_disabled() && r.tx_disabled()) {
        q.set_quality(daphne::MEASUREMENT_UNAVAILABLE);
        q.set_detail("TX power is not valid while TX is disabled; raw code retained");
        if (r.diagnostic_quality() == daphne::MEASUREMENT_GOOD) r.set_diagnostic_quality(daphne::MEASUREMENT_UNAVAILABLE);
      } else {
        q.set_value(v); q.set_quality(daphne::MEASUREMENT_GOOD);
        switch (i) {
          case 0: r.set_temperature_c(v); break;
          case 1: r.set_vcc_v(v); break;
          case 2: r.set_tx_bias_ma(v); break;
          case 3: r.set_tx_power_mw(v); break;
          case 4: r.set_rx_power_mw(v); break;
        }
      }
    } catch (const std::exception& e) { q.set_detail(e.what()); r.set_diagnostic_quality(daphne::MEASUREMENT_ERROR); }
    try {
      const auto ha = convert(constants, external, i, word(constants, i * 8));
      const auto la = convert(constants, external, i, word(constants, i * 8 + 2));
      const auto hw = convert(constants, external, i, word(constants, i * 8 + 4));
      const auto lw = convert(constants, external, i, word(constants, i * 8 + 6));
      require(la <= lw && lw <= hw && hw <= ha, "SFP factory thresholds not ordered");
      q.set_high_alarm(ha); q.set_low_alarm(la); q.set_high_warning(hw); q.set_low_warning(lw);
      q.set_threshold_quality(daphne::MEASUREMENT_GOOD);
    } catch (const std::exception& e) { q.set_detail(q.detail() + " Thresholds: " + e.what()); }
  }
  r.set_message("SFF-8472 module diagnostics; check per-quantity quality. Sequential reads, not common-time data. "
      "Optional flags are observed values/union of confirmation reads; vendor latching semantics, no alarm-control writes. "
      "Successful monitoring is not proof of link readiness");
}
} // namespace
const char* sfp_connector(unsigned channel) {
  constexpr std::array<const char*, 6> names{{"GTH2", "GTH1", "GTH0", "TMG", "GTH3", "GTR"}};
  if (channel >= names.size()) throw std::invalid_argument("SFP mux channel outside 0..5");
  return names[channel];
}
void evaluate_sfp_temperature_alarm(daphne::SFPMonitor& r, const TemperatureAlarmPolicy& policy, uint64_t now) {
  daphne::TemperatureStatus t;
  t.set_name(r.name() + "_SFP");
  t.set_temperature_c(std::numeric_limits<double>::quiet_NaN());
  t.set_quality(r.has_temperature_c() ? daphne::MEASUREMENT_GOOD :
      (r.diagnostic_quality() == daphne::MEASUREMENT_ERROR ? daphne::MEASUREMENT_ERROR : daphne::MEASUREMENT_UNAVAILABLE));
  t.set_valid(r.has_temperature_c());
  if (r.has_temperature_c()) {
    t.set_temperature_c(r.temperature_c());
    t.set_observed_monotonic_ns(r.diagnostics_observed_monotonic_ns());
    t.set_observed_host_unix_ns(r.observed_host_unix_ns());
  }
  evaluate_temperature_alarm(t, policy, now);
  *r.mutable_temperature_alarm() = t.alarm();
}
daphne::SFPMonitor collect_sfp_port(unsigned channel, const SfpIO& io, const std::string& source) {
  daphne::SFPMonitor r;
  r.set_name(sfp_connector(channel)); // Validate before any IO.
  r.set_mux_address(0x72); r.set_mux_channel(channel); r.set_a0_address(0x50); r.set_a2_address(0x51);
  r.set_source(source); r.set_identity_quality(daphne::MEASUREMENT_ERROR);
  r.set_diagnostic_quality(daphne::MEASUREMENT_UNAVAILABLE);
  require(io.read_mux && io.write_mux && io.read_eeprom && io.now && io.wait, "Missing SFP transport/clock");
  r.set_acquisition_started_monotonic_ns(io.now());
  try {
    Route route(io);
    r.set_previous_mux_route(route.previous());
    r.set_mux_restored(false);
    try {
      route.select(channel);
      r.set_identity_eeprom_readable(false);
      const auto a0 = read(io, 0x50, 0, 96);
      r.set_identity_eeprom_readable(true);
      identity(r, a0);
      try { diagnostics(r, a0, io); }
      catch (const std::exception& e) { invalidate(r, e.what(), false); }
      const auto after = read(io, 0x50, 0, 96);
      if (after != a0) throw std::runtime_error("SFP identity changed during acquisition; possible hot swap");
    } catch (const std::exception& e) { invalidate(r, e.what(), true); }
    try { route.verify(); }
    catch (const std::exception& e) { invalidate(r, e.what(), true); }
    route.restore(); // Restoration failure invalidates even an otherwise good sample.
    r.set_mux_restored(true);
  } catch (const std::exception& e) { invalidate(r, e.what(), true); }
  r.set_observed_monotonic_ns(io.now());
  if (!r.acquisition_started_monotonic_ns() || r.observed_monotonic_ns() < r.acquisition_started_monotonic_ns() ||
      r.diagnostics_observed_monotonic_ns() > r.observed_monotonic_ns())
    invalidate(r, "Invalid SFP monotonic observation clock", true);
  return r;
}
} // namespace daphne_sc
