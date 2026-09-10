#include "DaphneI2CDrivers.hpp"

namespace I2CMezzDrivers {
uint64_t HDMezzDriver::monitorClockUnlocked() const noexcept {
    try { return clock_(); } catch (...) { return 0; }
}

void HDMezzDriver::invalidateMonitoringUnlocked(uint8_t afe, MonitorQuality quality,
                                               const std::string& detail) {
    auto& sample = monitoring_[afe];
    sample.quality = quality;
    sample.detail = detail;
    sample.rails = {};
    sample.acquisitionStartedNs = sample.observedNs = 0;
    sample.activeConfigurationVerified = false;
    sample.protectiveActionAttempted = sample.powerRequestsOffConfirmed = false;
    // Retain lastGoodNs/attempt history, and never clear alert evidence here.
}

HDMezzDriver::MonitoringSnapshot HDMezzDriver::monitoringSnapshotUnlocked(
    uint8_t afe, uint64_t now) const {
    auto result = monitoring_[afe];
    result.afeBlock = afe;
    result.driverStateAvailable = true;
    result.enabled = enabled_afeBlocks[afe];
    result.configured = configured_afeBlocks[afe];
    result.stateObservedNs = now;
    result.alerts = alert_history_[afe];
    if (result.quality == MonitorQuality::Good) {
        if (!result.enabled || !result.configured) {
            result.quality = MonitorQuality::Unavailable;
            result.detail = "Block is disabled or unconfigured";
        } else if (!now || now < result.observedNs) {
            result.quality = MonitorQuality::Invalid;
            result.detail = "Invalid monotonic clock for cached mezzanine sample";
        } else if (now - result.observedNs > kMaxMonitorAgeNs) {
            result.quality = MonitorQuality::Stale;
            result.detail = "Mezzanine sample exceeds the 5 s freshness limit";
        }
    }
    if (result.quality != MonitorQuality::Good) {
        result.rails = {};
        result.activeConfigurationVerified = false;
        result.powerRequestsOffConfirmed = false;
    }
    return result;
}

HDMezzDriver::MonitoringSnapshot HDMezzDriver::monitoringSnapshot(uint8_t afe) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afe);
    return monitoringSnapshotUnlocked(afe, monitorClockUnlocked());
}

void HDMezzDriver::clearCachedAlerts(uint8_t afe) {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afe);
    alert_history_[afe] = {};
    invalidateMonitoringUnlocked(afe, MonitorQuality::Unavailable,
        "Software alert history cleared; awaiting a new hardware observation");
}

uint16_t HDMezzDriver::readAlertStatusUnlocked(uint8_t afe, size_t rail) {
    const auto address = I2C_drivers_defines::HDMezzAddressMap.at(
        rail == 0 ? "INA232_5V_ADDR" : "INA232_3V3_ADDR");
    const auto raw = readINA232RegisterUnlocked(afe, address,
        I2C_drivers_defines::HDMezzAddressMap.at("INA232_MASK_ENABLE_REG"));
    auto& history = alert_history_[afe][rail];
    history.available = true;
    history.latched = history.latched || (raw & 0x0010u);
    history.maskEnableRaw = raw;
    history.observedNs = monitorClockUnlocked();
    // Retain the observation BEFORE attempting power removal: that operation can fail.
    if (raw & 0x0010u) setPowerRequestsUnlocked(afe, false, false);
    return raw;
}

HDMezzDriver::MonitoringSnapshot HDMezzDriver::pollMonitoring(uint8_t afe) {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afe);
    if (!enabled_afeBlocks[afe] || !configured_afeBlocks[afe]) {
        invalidateMonitoringUnlocked(afe, MonitorQuality::Unavailable,
            "Block is disabled or unconfigured; monitoring performs no bus access");
        return monitoringSnapshotUnlocked(afe, monitorClockUnlocked());
    }
    MonitoringSnapshot next;
    next.sampleAttempt = monitoring_[afe].sampleAttempt + 1;
    next.lastGoodNs = monitoring_[afe].lastGoodNs;
    next.acquisitionStartedNs = monitorClockUnlocked();
    next.quality = MonitorQuality::Good;
    next.detail = "One locked sequential acquisition; TCA requests and software alert history are not physical power";
    const auto fail = [&](MonitorQuality quality, const char* detail) {
        // Never downgrade a transport/validity failure to merely retained history.
        const auto priority = [](MonitorQuality q) {
            return q == MonitorQuality::Error ? 3 : q == MonitorQuality::Invalid ? 2 :
                   q == MonitorQuality::Unavailable ? 1 : 0;
        };
        if (priority(quality) > priority(next.quality)) {
            next.quality = quality;
            next.detail = detail;
        }
    };
    const std::array<uint8_t, 2> addresses = {
        I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"),
        I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR")};
    // Non-clearing identity/config/calibration/limit words and TCA directions.
    const auto readConfiguration = [&] {
        std::array<uint16_t, 9> words{};
        for (size_t rail = 0; rail < 2; ++rail) {
            for (size_t reg = 0; reg < 4; ++reg) {
                const std::array<uint8_t, 4> registers = {0x3E, 0x00, 0x05, 0x07};
                words[rail * 4 + reg] = readINA232RegisterUnlocked(afe, addresses[rail], registers[reg]);
            }
        }
        words[8] = readTCA9536RegisterUnlocked(afe,
            I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_CONF_REG"));
        return words;
    };
    const auto matchesConfiguration = [&](const std::array<uint16_t, 9>& words) {
        return words[0] == 0x5449 && words[4] == 0x5449 &&
            words[1] == 0x4127u && words[5] == 0x4127u &&
            words[2] == shunt_cal_5V[afe] && words[6] == shunt_cal_3V3[afe] &&
            words[3] == alert_limit_5V[afe] && words[7] == alert_limit_3V3[afe] &&
            (words[8] & 0x0Fu) == 0x0Cu;
    };
    try {
        const auto before = readConfiguration();
        for (size_t rail = 0; rail < 2; ++rail) {
            const auto voltage = readINA232FunctionUnlocked(afe, addresses[rail], "VBUS");
            const auto current = readINA232FunctionUnlocked(afe, addresses[rail], "CURRENT");
            const auto power = readINA232FunctionUnlocked(afe, addresses[rail], "POWER");
            const auto signedCurrent = (current & 0x8000u) ? static_cast<int32_t>(current) - 0x10000
                                                         : static_cast<int32_t>(current);
            const double lsb = rail == 0 ? current_lsb_5V[afe] : current_lsb_3V3[afe];
            next.rails[rail].voltage = voltage * 1.6e-3;
            next.rails[rail].current = signedCurrent * lsb * 1000.0;
            next.rails[rail].power = power * 32.0 * lsb * 1000.0;
        }
        const auto after = readConfiguration();
        if (before != after || !matchesConfiguration(after))
            fail(MonitorQuality::Invalid, "Identity, calibration, monitor/protection settings or TCA directions changed/mismatch");
    } catch (const std::exception&) {
        fail(MonitorQuality::Error, "Incomplete mezzanine measurement/configuration acquisition");
    }

    // A new measurement-consistency check must not suppress the existing protective poll.
    // Keep each rail independent so a failed transfer cannot erase the other rail's alert.
    for (size_t rail = 0; rail < 2; ++rail) {
        if (alert_history_[afe][rail].latched) {
            // Existing policy deliberately avoids repeated clearing reads after latching.
            fail(MonitorQuality::Unavailable, "Retained alert history; current device status intentionally not re-read");
            continue;
        }
        try {
            const auto mask = readAlertStatusUnlocked(afe, rail);
            // Check configuration bits separately from dynamic flags; MemError/OVF invalidate data.
            if ((mask & 0xFC03u) != 0x8001u || (mask & 0x03E4u))
                fail(MonitorQuality::Invalid, "INA232 alert configuration, memory error or arithmetic overflow invalidates the sample");
            if (!alert_history_[afe][rail].observedNs ||
                alert_history_[afe][rail].observedNs < next.acquisitionStartedNs)
                fail(MonitorQuality::Invalid, "Missing alert-observation timestamp");
        } catch (const std::exception&) {
            fail(MonitorQuality::Error, "Mezzanine alert read or protective power-request removal failed");
        }
    }
    try {
        if (alert_history_[afe][0].latched || alert_history_[afe][1].latched) {
            next.protectiveActionAttempted = true;
            setPowerRequestsUnlocked(afe, false, false); // Existing latched-alert behavior, not a new trip policy.
        }
        const auto power = readPowerRequestsUnlocked(afe);
        next.rails[0].powerRequested = power.power5V;
        next.rails[1].powerRequested = power.power3V3;
        next.powerRequestsOffConfirmed = !power.power5V && !power.power3V3;
    } catch (const std::exception&) {
        fail(MonitorQuality::Error, "Mezzanine power-request read/removal was not verified");
    }
    const auto completed = monitorClockUnlocked();
    if (!next.acquisitionStartedNs || completed < next.acquisitionStartedNs ||
        completed - next.acquisitionStartedNs > kMaxMonitorAcquisitionNs)
        fail(MonitorQuality::Invalid, "Invalid or excessive monitoring acquisition interval (100 ms limit)");
    if (alert_history_[afe][0].observedNs > completed ||
        alert_history_[afe][1].observedNs > completed ||
        (next.quality == MonitorQuality::Good &&
         alert_history_[afe][1].observedNs < alert_history_[afe][0].observedNs))
        fail(MonitorQuality::Invalid, "Alert-observation clock lies outside the monitoring interval");
    if (next.quality == MonitorQuality::Good) {
        next.observedNs = completed;
        next.lastGoodNs = completed;
        next.activeConfigurationVerified = true;
    } else {
        next.rails = {}; // No old or partial numerical sample can appear valid.
        next.powerRequestsOffConfirmed = false;
    }
    monitoring_[afe] = next;
    return monitoringSnapshotUnlocked(afe, completed);
}
}
