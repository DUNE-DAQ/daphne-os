#include "server_controller/hdmezz_protocol.hpp"

#include <iostream>
#include <limits>
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

Driver::MonitoringSnapshot goodMonitor() {
    Driver::MonitoringSnapshot s;
    s.afeBlock = 2; s.driverStateAvailable = s.enabled = s.configured = true;
    s.quality = Driver::MonitorQuality::Good;
    s.rails = {{{5.0, -1.5, 4.25, true}, {3.2, 2.5, 0.0, false}}};
    s.alerts = {{{true, false, 0x8009, 130}, {true, false, 0x8001, 140}}};
    s.acquisitionStartedNs = 100; s.observedNs = s.lastGoodNs = 200;
    s.stateObservedNs = 300; s.sampleAttempt = 7; s.activeConfigurationVerified = true;
    return s;
}

void checkMasked(const daphne::cmd_readHDMezzStatus_response& out) {
    check(!out.success() && !out.active_configuration_verified() && !out.power_requests_off_confirmed(),
          "failed measurement claimed success/configuration/power proof");
    for (int n = 4; n <= 11; ++n)
        check(!out.GetReflection()->HasField(out, out.GetDescriptor()->FindFieldByNumber(n)),
              "non-GOOD sample retained optional numerical/power observation");
}

void testMonitoringProtocol() {
    using MQ = Driver::MonitorQuality;
    daphne::cmd_readHDMezzStatus_response out, wire;
    auto s = goodMonitor();
    check(daphne_sc::fill_hdmezz_status(s, out), "good monitor rejected");
    check(wire.ParseFromString(out.SerializeAsString()), "status wire parse failed");
    check(wire.success() && wire.monitor_quality() == daphne::HDMEZZ_MONITOR_GOOD && wire.afeblock() == 2 &&
          wire.driver_state_available() && wire.block_enabled() && wire.driver_configured() &&
          wire.sample_attempt() == 7 && wire.last_good_monotonic_ns() == 200 &&
          wire.acquisition_started_monotonic_ns() == 100 && wire.observed_monotonic_ns() == 200 &&
          wire.state_observed_monotonic_ns() == 300, "metadata mapping mismatch");
    check(wire.power5v() && !wire.power3v3() && wire.measured_voltage5v() == 5.0f &&
          wire.measured_current5v() == -1.5f && wire.measured_power3v3() == 0 &&
          wire.has_measured_power3v3() && wire.has_power3v3() && wire.has_alert_3v3() &&
          wire.has_alert_history_5v() && wire.alert_history_5v().mask_enable_raw() == 0x8009 &&
          wire.alert_history_5v().observed_monotonic_ns() == 130, "zero/false/signed values or history lost");
    const std::vector<std::string> names = {"success", "message", "afeBlock", "power5V", "power3V3",
        "measured_voltage5V", "measured_voltage3V3", "measured_current5V", "measured_current3V3",
        "measured_power5V", "measured_power3V3", "alert_5V", "alert_3V3"};
    for (size_t i = 0; i < names.size(); ++i) {
        const auto* f = out.GetDescriptor()->FindFieldByName(names[i]);
        const int type = i == 1 ? 9 : i == 2 ? 13 : (i >= 5 && i <= 10) ? 2 : 8;
        check(f && f->number() == static_cast<int>(i + 1) && static_cast<int>(f->type()) == type,
              "legacy status field number/type changed");
        if (i >= 3) check(f->has_presence(), "legacy observation has no explicit presence");
    }
    for (MQ quality : {MQ::Unavailable, MQ::Error, MQ::Invalid, MQ::Stale}) {
        s = goodMonitor(); s.quality = quality;
        s.stateObservedNs = s.observedNs + Driver::kMaxMonitorAgeNs + 1;
        s.alerts[0].latched = true; s.alerts[0].maskEnableRaw = 0x8011;
        s.protectiveActionAttempted = true;
        check(!daphne_sc::fill_hdmezz_status(s, out), "non-GOOD status accepted");
        checkMasked(out);
        check(out.has_alert_5v() && out.alert_5v() && out.has_alert_history_5v() &&
              out.alert_history_5v().observed_monotonic_ns() == 130 && out.protective_action_attempted(),
              "failed/stale sample lost alert or attempt history");
        check(out.observed_monotonic_ns() == (quality == MQ::Stale ? 200 : 0),
              "completed sample timestamp provenance incorrect");
    }
    // Pure mapping also catches stale snapshots if a caller did not pre-classify age.
    s = goodMonitor(); s.stateObservedNs = s.observedNs + Driver::kMaxMonitorAgeNs;
    check(daphne_sc::fill_hdmezz_status(s, out), "inclusive age boundary rejected");
    ++s.stateObservedNs;
    check(!daphne_sc::fill_hdmezz_status(s, out) && out.monitor_quality() == daphne::HDMEZZ_MONITOR_STALE,
          "expired GOOD sample not downgraded");
    checkMasked(out);
    for (int fault = 0; fault < 24; ++fault) {
        s = goodMonitor();
        switch (fault) {
            case 0: s.driverStateAvailable = false; break;
            case 1: s.enabled = false; break;
            case 2: s.configured = false; break;
            case 3: s.acquisitionStartedNs = 0; break;
            case 4: s.observedNs = 99; break;
            case 5: s.observedNs = s.lastGoodNs = s.stateObservedNs = 100 + Driver::kMaxMonitorAcquisitionNs + 1; break;
            case 6: s.stateObservedNs = 0; break;
            case 7: s.stateObservedNs = 199; break;
            case 8: s.lastGoodNs = 199; break;
            case 9: s.sampleAttempt = 0; break;
            case 10: s.activeConfigurationVerified = false; break;
            case 11: s.rails[0].current = std::numeric_limits<double>::quiet_NaN(); break;
            case 12: s.rails[1].power = std::numeric_limits<double>::infinity(); break;
            case 13: s.rails[1].voltage = -1; break;
            case 14: s.rails[0].power = -1; break;
            case 15: s.rails[0].current = static_cast<double>(std::numeric_limits<float>::max()) * 2; break;
            case 16: s.alerts[0].available = false; break;
            case 17: s.alerts[1].observedNs = 99; break;
            case 18: s.alerts[0].maskEnableRaw |= 0x20; break;
            case 19: s.alerts[1].maskEnableRaw ^= 1; break;
            case 20: s.alerts[0].latched = true; break;
            case 21: s.powerRequestsOffConfirmed = true; break;
            case 22: s.protectiveActionAttempted = true; break;
            case 23: s.quality = static_cast<MQ>(999); break;
        }
        check(!daphne_sc::fill_hdmezz_status(s, out) && out.monitor_quality() == daphne::HDMEZZ_MONITOR_INVALID,
              "inconsistent good monitoring evidence accepted");
        checkMasked(out);
    }
    s = goodMonitor(); s.alerts[0] = {true, true, 0x8011, 130};
    s.rails[0].powerRequested = false; s.powerRequestsOffConfirmed = s.protectiveActionAttempted = true;
    check(daphne_sc::fill_hdmezz_status(s, out) && out.alert_5v() && out.power_requests_off_confirmed(),
          "fresh alert with verified TCA off rejected");
    s.quality = MQ::Error; s.alerts[0].observedNs = 0; s.alerts[1] = {};
    check(!daphne_sc::fill_hdmezz_status(s, out) && out.has_alert_5v() && out.alert_5v() &&
          out.alert_history_5v().observed_monotonic_ns() == 0 && !out.has_alert_3v3() &&
          !out.has_alert_history_3v3(), "missing time/other rail erased known alert history");
    s = {};
    check(!daphne_sc::fill_hdmezz_status(s, out) && !out.driver_state_available() && !out.block_enabled() &&
          !out.has_alert_5v() && !out.has_alert_history_5v() &&
          out.monitor_quality() == daphne::HDMEZZ_MONITOR_UNAVAILABLE, "missing driver fabricated state");
    checkMasked(out);
    std::cout << "PASS monitoring protobuf quality, stale/missing/invalid masking, alert history and wire presence\n";
}
}

int main() {
    try {
        testMonitoringProtocol();
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
