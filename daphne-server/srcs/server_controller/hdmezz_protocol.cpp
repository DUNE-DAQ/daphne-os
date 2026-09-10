#include "server_controller/hdmezz_protocol.hpp"

#include <cmath>
#include <limits>

namespace daphne_sc {
bool fill_hdmezz_status(
    const I2CMezzDrivers::HDMezzDriver::MonitoringSnapshot& s,
    daphne::cmd_readHDMezzStatus_response& out) {
    using Driver = I2CMezzDrivers::HDMezzDriver;
    using Quality = Driver::MonitorQuality;
    out.Clear();
    out.set_afeblock(s.afeBlock);
    out.set_message(s.detail);
    out.set_driver_state_available(s.driverStateAvailable);
    if (s.driverStateAvailable) {
        out.set_block_enabled(s.enabled);
        out.set_driver_configured(s.configured);
        out.set_state_observed_monotonic_ns(s.stateObservedNs);
    }
    out.set_acquisition_started_monotonic_ns(s.acquisitionStartedNs);
    out.set_last_good_monotonic_ns(s.lastGoodNs);
    out.set_sample_attempt(s.sampleAttempt);
    out.set_protective_action_attempted(s.protectiveActionAttempted);
    // Alert evidence is historical and survives numerical sample errors/staleness.
    for (size_t rail = 0; rail < 2; ++rail) {
        if (!s.alerts[rail].available) continue;
        auto* history = rail ? out.mutable_alert_history_3v3() : out.mutable_alert_history_5v();
        history->set_software_latched(s.alerts[rail].latched);
        history->set_mask_enable_raw(s.alerts[rail].maskEnableRaw);
        history->set_observed_monotonic_ns(s.alerts[rail].observedNs);
        if (rail) out.set_alert_3v3(s.alerts[rail].latched);
        else out.set_alert_5v(s.alerts[rail].latched);
    }
    auto quality = s.quality;
    const auto invalid = [&] {
        quality = Quality::Invalid;
        out.set_message("Inconsistent mezzanine monitoring evidence");
    };
    if (quality == Quality::Good || quality == Quality::Stale) {
        if (s.afeBlock > 4 || !s.driverStateAvailable || !s.enabled || !s.configured ||
            !s.sampleAttempt || !s.acquisitionStartedNs || s.observedNs < s.acquisitionStartedNs ||
            s.observedNs - s.acquisitionStartedNs > Driver::kMaxMonitorAcquisitionNs ||
            s.lastGoodNs != s.observedNs || !s.stateObservedNs || s.stateObservedNs < s.observedNs)
            invalid();
        else if (s.stateObservedNs - s.observedNs > Driver::kMaxMonitorAgeNs)
            quality = Quality::Stale;
        else if (quality == Quality::Stale)
            invalid(); // A stale label also needs age evidence.
    }
    if (quality == Quality::Good) {
        bool valid = s.activeConfigurationVerified;
        for (size_t rail = 0; rail < 2; ++rail) {
            const auto& r = s.rails[rail];
            const auto& a = s.alerts[rail];
            for (const double value : {r.voltage, r.current, r.power})
                valid = valid && std::isfinite(value) && std::abs(value) <= std::numeric_limits<float>::max();
            valid = valid && r.voltage >= 0 && r.power >= 0 && a.available && a.observedNs &&
                a.observedNs >= s.acquisitionStartedNs && a.observedNs <= s.observedNs &&
                (a.maskEnableRaw & 0xFFE7u) == 0x8001u &&
                a.latched == ((a.maskEnableRaw & 0x10u) != 0);
        }
        const bool alert = s.alerts[0].latched || s.alerts[1].latched;
        valid = valid && s.alerts[0].observedNs <= s.alerts[1].observedNs &&
            s.protectiveActionAttempted == alert &&
            s.powerRequestsOffConfirmed == (!s.rails[0].powerRequested && !s.rails[1].powerRequested) &&
            (!alert || s.powerRequestsOffConfirmed);
        if (!valid) invalid();
    }
    switch (quality) {
        case Quality::Good: out.set_monitor_quality(daphne::HDMEZZ_MONITOR_GOOD); break;
        case Quality::Unavailable: out.set_monitor_quality(daphne::HDMEZZ_MONITOR_UNAVAILABLE); break;
        case Quality::Error: out.set_monitor_quality(daphne::HDMEZZ_MONITOR_ERROR); break;
        case Quality::Invalid: out.set_monitor_quality(daphne::HDMEZZ_MONITOR_INVALID); break;
        case Quality::Stale: out.set_monitor_quality(daphne::HDMEZZ_MONITOR_STALE); break;
        default: quality = Quality::Invalid; out.set_monitor_quality(daphne::HDMEZZ_MONITOR_INVALID); break;
    }
    if (quality == Quality::Good || quality == Quality::Stale) out.set_observed_monotonic_ns(s.observedNs);
    const bool good = quality == Quality::Good;
    if (good) {
        out.set_power5v(s.rails[0].powerRequested); out.set_power3v3(s.rails[1].powerRequested);
        out.set_measured_voltage5v(s.rails[0].voltage); out.set_measured_voltage3v3(s.rails[1].voltage);
        out.set_measured_current5v(s.rails[0].current); out.set_measured_current3v3(s.rails[1].current);
        out.set_measured_power5v(s.rails[0].power); out.set_measured_power3v3(s.rails[1].power);
        out.set_active_configuration_verified(true);
        out.set_power_requests_off_confirmed(s.powerRequestsOffConfirmed);
    }
    out.set_success(good); // Old clients must not accept missing samples as successful zeroes.
    return good;
}

bool fill_hdmezz_configuration(
    const I2CMezzDrivers::HDMezzDriver::ConfigurationSnapshot& s,
    daphne::cmd_readHDMezzBlockConfig_response& out) {
    using Driver = I2CMezzDrivers::HDMezzDriver;
    using Quality = Driver::ReadbackQuality;
    out.Clear();
    out.set_afeblock(s.afeBlock);
    out.set_block_enabled(s.enabled);
    out.set_driver_configured(s.configured);
    out.set_requested_settings_available(s.requestedSettingsAvailable);
    out.set_message(s.detail);
    if (s.requestedSettingsAvailable) {
        out.set_r_shunt_5v(s.requested.rShunt5V);
        out.set_r_shunt_3v3(s.requested.rShunt3V3);
        out.set_max_current_5v_scale(s.requested.maxCurrentScale5V);
        out.set_max_current_3v3_scale(s.requested.maxCurrentScale3V3);
        out.set_max_current_5v_shutdown(s.requested.maxCurrentShutdown5V);
        out.set_max_current_3v3_shutdown(s.requested.maxCurrentShutdown3V3);
        out.set_max_power_5v(s.maxPower[0]); out.set_max_power_3v3(s.maxPower[1]);
        out.set_current_lsb_5v(s.currentLsb[0]); out.set_current_lsb_3v3(s.currentLsb[1]);
        out.set_requested_shunt_cal_5v(s.requestedShuntCal[0]);
        out.set_requested_shunt_cal_3v3(s.requestedShuntCal[1]);
    }
    auto quality = s.quality;
    if (quality == Quality::Good && (s.afeBlock > 4 || !s.enabled ||
        !s.requestedSettingsAvailable || !s.acquisitionStartedNs ||
        s.observedNs < s.acquisitionStartedNs ||
        s.observedNs - s.acquisitionStartedNs > Driver::kMaxConfigurationReadNs ||
        (s.observedShuntCal[0] & 0x8000u) || (s.observedShuntCal[1] & 0x8000u))) {
        quality = Quality::Invalid;
        out.set_message("Inconsistent calibration readback evidence");
    }
    switch (quality) {
        case Quality::Good: out.set_calibration_readback_quality(daphne::HDMEZZ_READBACK_GOOD); break;
        case Quality::Unavailable: out.set_calibration_readback_quality(daphne::HDMEZZ_READBACK_UNAVAILABLE); break;
        case Quality::Error: out.set_calibration_readback_quality(daphne::HDMEZZ_READBACK_ERROR); break;
        case Quality::Invalid: out.set_calibration_readback_quality(daphne::HDMEZZ_READBACK_INVALID); break;
    }
    out.set_acquisition_started_monotonic_ns(s.acquisitionStartedNs);
    const bool good = quality == Quality::Good;
    if (good) {
        out.set_shunt_cal_5v(s.observedShuntCal[0]);
        out.set_shunt_cal_3v3(s.observedShuntCal[1]);
        out.set_observed_monotonic_ns(s.observedNs);
        out.set_calibration_matches_requested(s.requestedSettingsAvailable &&
                                             s.observedShuntCal == s.requestedShuntCal);
    }
    // Legacy consumers must not accept missing readback as successful zero codes.
    out.set_success(good);
    return good;
}
}
