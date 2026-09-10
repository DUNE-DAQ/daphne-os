#include "server_controller/hdmezz_protocol.hpp"

namespace daphne_sc {
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
