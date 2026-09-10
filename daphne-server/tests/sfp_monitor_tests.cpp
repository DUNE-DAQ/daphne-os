#include "server_controller/sfp_monitor.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace daphne_sc;
using Bytes = std::vector<uint8_t>;
void check(bool ok) { if (!ok) throw std::runtime_error("SFP test assertion failed"); }
void near(double a, double b) { check(std::abs(a - b) < 1e-9); }
void put(Bytes& b, size_t p, uint16_t v) { b.at(p) = v >> 8; b.at(p + 1) = v; }
void sum(Bytes& b, unsigned first, unsigned last) {
  unsigned v = 0; for (unsigned i = first; i < last; ++i) v += b.at(i); b.at(last) = v;
}
void fp(Bytes& b, unsigned p, float f) {
  uint32_t bits; std::memcpy(&bits, &f, 4); put(b, p, bits >> 16); put(b, p + 2, bits);
}
struct Fake {
  Bytes a0 = Bytes(128), a2 = Bytes(128);
  uint8_t mux = 0;
  unsigned writes = 0, reads = 0, mux_reads = 0, a0_reads = 0, a2_reads = 0;
  unsigned fail_write = 0, fail_read = 0, fail_mux_read = 0;
  bool short_read = false, hot_swap = false, disturbed = false, persistent_write_failure = false;
  uint64_t now = 1000000000;
  std::vector<uint8_t> routes;
  Fake() {
    a0[0] = 3; a0[1] = 4;
    for (auto p : {20,40,56,68,84}) {
      const unsigned n = p == 56 ? 4 : p == 84 ? 8 : 16;
      std::fill_n(a0.begin() + p, n, ' ');
    }
    const std::string vendor = "TEST VENDOR";
    std::copy(vendor.begin(), vendor.end(), a0.begin() + 20);
    a0[92] = 0x68; a0[93] = 0xf0; a0[94] = 0x0c;
    // Default valid internal diagnostics; negative temperature tests signed decode.
    put(a2, 96, uint16_t(-10 * 256)); put(a2, 98, 33000); put(a2, 100, 5000);
    put(a2, 102, 12000); put(a2, 104, 5000);
    for (unsigned i = 0; i < 5; ++i) {
      put(a2, i * 8, i ? 60000 : 100 * 256); put(a2, i * 8 + 2, i ? 0 : uint16_t(-40 * 256));
      put(a2, i * 8 + 4, i ? 50000 : 85 * 256); put(a2, i * 8 + 6, 0);
    }
    sums();
  }
  void sums() { sum(a0, 0, 63); sum(a0, 64, 95); sum(a2, 0, 95); }
  SfpIO io() {
    return {
      [&] { if (++mux_reads == fail_mux_read) throw std::runtime_error("Mux read failure"); return mux; },
      [&](uint8_t value) {
        check(!(value & 0xc0) && (!value || !(value & (value - 1))));
        routes.push_back(value); ++writes; mux = value; // Fault can occur after hardware changed.
        if (writes == fail_write || persistent_write_failure) throw std::runtime_error("Mux write failure");
      },
      [&](uint8_t address, uint8_t offset, size_t count) {
        check((address == 0x50 || address == 0x51) && count && count <= 32 && offset + count <= 128);
        check(mux && !(mux & (mux - 1)) && !(mux & 0xc0));
        ++reads;
        if (reads == fail_read) throw std::runtime_error("EEPROM transport failure");
        auto& b = address == 0x50 ? a0 : a2;
        if (address == 0x50) {
          ++a0_reads;
          if (hot_swap && a0_reads == 4) { a0[20] ^= 1; sums(); }
        } else ++a2_reads;
        Bytes result(b.begin() + offset, b.begin() + offset + count);
        if (short_read) result.pop_back();
        if (disturbed && a0_reads == 6) mux = 2;
        now += 1000;
        return result;
      },
      [&] { return ++now; },
      [&](uint64_t ns) { now += ns; }
    };
  }
  daphne::SFPMonitor run(unsigned ch = 0) { return collect_sfp_port(ch, io(), "synthetic"); }
};
void good(const daphne::SFPMonitor& r) {
  check(r.identity_quality() == daphne::MEASUREMENT_GOOD && r.has_present() && r.present());
  check(r.has_mux_restored() && r.mux_restored());
  check(r.diagnostic_quality() == daphne::MEASUREMENT_GOOD);
  check(r.has_temperature_c() && r.has_vcc_v() && r.has_tx_bias_ma() && r.has_tx_power_mw() && r.has_rx_power_mw());
  check(r.has_data_ready() && r.data_ready() && r.has_tx_disabled() && !r.tx_disabled());
  check(r.quantities_size() == 5);
  check(r.observed_monotonic_ns() > r.acquisition_started_monotonic_ns());
  daphne::SFPMonitor decoded;
  check(decoded.ParseFromString(r.SerializeAsString()) && decoded.has_loss_of_signal() && !decoded.loss_of_signal());
}
int main() {
  for (uint8_t old : {0,1,2,4,8,16,32}) for (unsigned channel = 0; channel < 6; ++channel) {
    Fake f; f.mux = old; const auto r = f.run(channel); good(r);
    check(r.name() == sfp_connector(channel) && r.mux_channel() == channel);
    check(f.mux == old && f.routes == Bytes({0,uint8_t(1u << channel),0,old}));
    check(r.has_previous_mux_route() && r.previous_mux_route() == old);
    near(r.temperature_c(), -10); near(r.vcc_v(), 3.3); near(r.tx_bias_ma(), 10);
    near(r.tx_power_mw(), 1.2); near(r.rx_power_mw(), .5);
    near(r.quantities(0).low_alarm(), -40); near(r.quantities(0).high_warning(), 85);
  }
  for (uint8_t old : {3,63,64,128,255}) {
    Fake f; f.mux = old; auto r = f.run(); check(f.writes == 0 && !r.has_present() && !r.has_mux_restored());
  }
  for (unsigned fail = 1; fail <= 4; ++fail) {
    Fake f; f.mux = 32; f.fail_write = fail; auto r = f.run();
    check(f.mux == 32 && r.identity_quality() == daphne::MEASUREMENT_ERROR && !r.has_temperature_c());
  }
  for (unsigned fail = 1; fail <= 6; ++fail) {
    Fake f; f.mux = 16; f.fail_mux_read = fail; auto r = f.run();
    check(f.mux == 16 && !r.has_temperature_c());
  }
  for (unsigned fail = 1; fail <= 14; ++fail) {
    Fake f; f.fail_read = fail; auto r = f.run();
    check(f.mux == 0 && r.mux_restored() && !r.has_temperature_c());
  }
  { Fake f; f.short_read = true; auto r = f.run(); check(!r.has_present() && r.mux_restored()); }
  { Fake f; f.persistent_write_failure = true; auto r = f.run(); check(!r.mux_restored() && !r.has_present()); }
  { Fake f; f.hot_swap = true; auto r = f.run(); check(!r.has_present() && !r.has_temperature_c() && r.mux_restored()); }
  { Fake f; f.disturbed = true; auto r = f.run(); check(!r.has_present() && !r.has_temperature_c() && f.mux == 0); }
  for (unsigned bad : {0,63,95}) {
    Fake f; f.a0[bad] ^= 1; auto r = f.run(); check(!r.has_present() && f.a2_reads == 0 && r.mux_restored());
  }
  { Fake f; f.a0[0] = 0x0d; f.sums(); auto r = f.run(); check(!r.has_present() && f.a2_reads == 0); }
  { Fake f; f.a0[37] = 0x12; f.a0[38] = 0x34; f.a0[39] = 0x56; f.a0[12] = 103; put(f.a0, 60, 850);
    f.sums(); auto r = f.run(); good(r);
    check(r.vendor_oui() == 0x123456 && r.nominal_signaling_rate_mbd() == 10300 && r.wavelength_nm() == 850);
    check(r.dom_supported() && r.identity_eeprom_readable() && r.diagnostic_eeprom_readable());
    f.a0[12] = 255; f.a0[66] = 200; f.a0[8] = 4; f.sums(); r = f.run();
    check(r.nominal_signaling_rate_mbd() == 50000 && !r.has_wavelength_nm());
    f.a0[12] = 0; std::fill_n(f.a0.begin()+37, 3, 0); f.sums(); r = f.run();
    check(!r.has_nominal_signaling_rate_mbd() && !r.has_vendor_oui());
  }
  { Fake f; std::fill_n(f.a0.begin() + 56, 4, 0); f.sums(); auto r = f.run(); good(r); check(r.revision().empty()); }
  { Fake f; f.a0[21] = 0; f.sums(); auto r = f.run(); check(!r.has_present()); }
  { Fake f; f.a2[95] ^= 1; auto r = f.run(); check(r.present() && !r.diagnostic_checksum_valid() && !r.has_temperature_c()); }
  for (unsigned type : {0,0x64,0xe0}) {
    Fake f; f.a0[92] = type; f.sums(); auto r = f.run();
    check(r.present() && r.diagnostic_quality() == daphne::MEASUREMENT_UNAVAILABLE && f.a2_reads == 0);
  }
  for (unsigned type : {0x40,0x70}) {
    Fake f; f.a0[92] = type; f.sums(); auto r = f.run();
    check(r.present() && r.diagnostic_quality() == daphne::MEASUREMENT_ERROR && f.a2_reads == 0);
  }
  { Fake f; f.a2[110] = 1; auto r = f.run(); check(r.present() && r.has_data_ready() && !r.data_ready() && !r.has_temperature_c()); }
  { Fake f; f.a2[110] = 0x46; auto r = f.run();
    check(r.tx_disabled() && r.tx_fault() && r.loss_of_signal() && !r.has_tx_power_mw() && r.has_temperature_c()); }
  { Fake f; f.a0[93] = 0; f.sums(); auto r = f.run();
    check(!r.has_tx_disabled() && !r.has_tx_fault() && !r.has_loss_of_signal() && !r.has_alarm_flags()); }
  { Fake f; put(f.a2, 112, 0x8000); put(f.a2, 116, 0x0040); auto r = f.run(); good(r);
    check(r.quantities(0).high_alarm_flag() && r.quantities(4).low_warning_flag());
    check(r.alarm_flags_second() == 0x8000 && r.flags_second_monotonic_ns() - r.flags_observed_monotonic_ns() >= 100000000); }
  { Fake f; auto io = f.io(); io.now = [] { return uint64_t(0); };
    auto r = collect_sfp_port(0, io, "synthetic"); check(!r.has_temperature_c() && !r.has_present() && r.mux_restored()); }
  { Fake f; for (unsigned i = 96; i <= 105; ++i) f.a2[i] = 0; auto r = f.run(); good(r);
    check(r.has_temperature_c() && r.temperature_c() == 0 && r.has_rx_power_mw() && r.rx_power_mw() == 0); }
  { Fake f; f.a0[92] = 0x50; // External, OMA. Nontrivial slopes/offsets and polynomial.
    for (unsigned p : {76,80,84,88}) { put(f.a2,p,512); put(f.a2,p+2,256); }
    fp(f.a2, 56, 0); fp(f.a2, 60, 0); fp(f.a2, 64, 0); fp(f.a2, 68, 2); fp(f.a2, 72, 10);
    f.sums(); auto r = f.run(); good(r);
    check(r.calibration() == daphne::SFP_CALIBRATION_EXTERNAL && r.rx_power_is_oma());
    near(r.temperature_c(), -19); near(r.vcc_v(), 6.6256); near(r.tx_bias_ma(), 20.512);
    near(r.tx_power_mw(), 2.4256); near(r.rx_power_mw(), 1.001);
    fp(f.a2, 72, std::numeric_limits<float>::quiet_NaN()); f.sums(); r = f.run();
    check(r.has_temperature_c() && !r.has_rx_power_mw() && r.quantities(4).quality() == daphne::MEASUREMENT_ERROR);
  }
  { Fake f; bool failed = false; try { f.run(6); } catch (...) { failed = true; } check(failed && f.writes == 0 && f.mux_reads == 0); }
  { daphne::SFPMonitor r;
    evaluate_sfp_temperature_alarm(r, {}, 10); check(r.temperature_alarm().state() == daphne::TEMPERATURE_ALARM_MISSING);
    r.set_diagnostic_quality(daphne::MEASUREMENT_ERROR);
    evaluate_sfp_temperature_alarm(r, {}, 10); check(r.temperature_alarm().state() == daphne::TEMPERATURE_ALARM_INVALID);
    r.set_temperature_c(85); r.set_diagnostics_observed_monotonic_ns(1);
    evaluate_sfp_temperature_alarm(r, {}, 10); check(r.temperature_alarm().state() == daphne::TEMPERATURE_ALARM_WARNING);
    evaluate_sfp_temperature_alarm(r, {}, 6000000000); check(r.temperature_alarm().state() == daphne::TEMPERATURE_ALARM_STALE);
  }
  std::cout << "SFP 6-route/42-restoration, checksums, unsupported, signed/internal/external calibration, flags, hot-swap and failure tests passed\n";
}
