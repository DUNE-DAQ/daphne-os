#include "server_controller/hdmezz_protocol.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Driver = I2CMezzDrivers::HDMezzDriver;
using Quality = Driver::ReadbackQuality;
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
Driver::ConfigurationSnapshot good() {
    Driver::ConfigurationSnapshot s;
    s.afeBlock = 3; s.enabled = true; s.configured = true;
    s.requestedSettingsAvailable = true;
    s.requested = {0.036, 0.3, 0.2, 0.2, 0.12, 0.05};
    s.currentLsb = {0.001, 0.002}; s.maxPower = {0.6, 0.165};
    s.requestedShuntCal = {0x1234, 0x2345};
    s.observedShuntCal = s.requestedShuntCal;
    s.quality = Quality::Good;
    s.acquisitionStartedNs = 100; s.observedNs = 200;
    s.detail = "fixture: cached targets and actual calibration pair";
    return s;
}
}

int main() {
    try {
        daphne::cmd_readHDMezzBlockConfig_response out, wire;
        auto s = good();
        check(daphne_sc::fill_hdmezz_configuration(s, out), "good pair rejected");
        check(wire.ParseFromString(out.SerializeAsString()), "wire parse failed");
        check(wire.success() && wire.afeblock() == 3 && wire.block_enabled() && wire.driver_configured(),
              "lost driver bookkeeping");
        check(wire.calibration_readback_quality() == daphne::HDMEZZ_READBACK_GOOD &&
              wire.observed_monotonic_ns() == 200 && wire.acquisition_started_monotonic_ns() == 100,
              "lost readback quality/time");
        check(wire.shunt_cal_5v() == 0x1234 && wire.shunt_cal_3v3() == 0x2345 &&
              wire.requested_shunt_cal_5v() == 0x1234 && wire.calibration_matches_requested(),
              "requested and actual calibration not independently mapped");
        check(wire.requested_settings_available() && wire.r_shunt_5v() > 0.035 &&
              wire.r_shunt_3v3() > 0.299 && wire.current_lsb_3v3() > 0.0019,
              "cached settings lost");

        s.observedShuntCal = {0x3456, 0}; s.configured = false;
        check(daphne_sc::fill_hdmezz_configuration(s, out), "valid mismatch/reset readback rejected");
        check(!out.calibration_matches_requested() && out.shunt_cal_5v() == 0x3456 &&
              out.shunt_cal_3v3() == 0 && out.requested_shunt_cal_5v() == 0x1234 &&
              !out.driver_configured(), "mismatch concealed or claimed configured");

        for (auto quality : {Quality::Unavailable, Quality::Error, Quality::Invalid}) {
            s = good(); s.quality = quality;
            check(!daphne_sc::fill_hdmezz_configuration(s, out), "failed sample accepted");
            check(!out.success() && !out.calibration_matches_requested() &&
                  out.shunt_cal_5v() == 0 && out.shunt_cal_3v3() == 0 &&
                  out.observed_monotonic_ns() == 0 && out.requested_shunt_cal_5v() == 0x1234,
                  "error response retained old/partial readback or lost requested cache");
        }
        for (unsigned fault = 0; fault < 8; ++fault) {
            s = good();
            switch (fault) {
                case 0: s.enabled = false; break;
                case 1: s.acquisitionStartedNs = 0; break;
                case 2: s.observedNs = 99; break;
                case 3: s.observedNs = 101 + Driver::kMaxConfigurationReadNs; break;
                case 4: s.observedShuntCal[0] |= 0x8000u; break;
                case 5: s.observedShuntCal[1] |= 0x8000u; break;
                case 6: s.requestedSettingsAvailable = false; break;
                case 7: s.afeBlock = 5; break;
            }
            check(!daphne_sc::fill_hdmezz_configuration(s, out) &&
                  out.calibration_readback_quality() == daphne::HDMEZZ_READBACK_INVALID &&
                  out.observed_monotonic_ns() == 0 && out.shunt_cal_5v() == 0,
                  "inconsistent good sample not rejected");
        }
        s = {};
        check(!daphne_sc::fill_hdmezz_configuration(s, out) && !out.requested_settings_available() &&
              out.requested_shunt_cal_5v() == 0 && out.r_shunt_5v() == 0 &&
              out.calibration_readback_quality() == daphne::HDMEZZ_READBACK_UNAVAILABLE,
              "absent driver fabricated configuration");

        // Wire compatibility: none of the fifteen existing field numbers moved.
        const std::vector<std::string> oldNames = {"success", "message", "afeBlock", "r_shunt_5V",
            "r_shunt_3V3", "max_current_5V_scale", "max_current_3V3_scale", "max_current_5V_shutdown",
            "max_current_3V3_shutdown", "max_power_5V", "max_power_3V3", "current_lsb_5V",
            "current_lsb_3V3", "shunt_cal_5V", "shunt_cal_3V3"};
        for (size_t i = 0; i < oldNames.size(); ++i) {
            const auto* field = out.GetDescriptor()->FindFieldByName(oldNames[i]);
            check(field && field->number() == static_cast<int>(i + 1), "legacy field renumbered");
        }
        std::cout << "PASS calibration protobuf mapping, failures, presence, timing and legacy field numbers\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL " << e.what() << '\n';
        return 1;
    }
}
