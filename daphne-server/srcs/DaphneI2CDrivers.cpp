#include "DaphneI2CDrivers.hpp"
#include "BoardI2C.hpp"
#include "PmbusLinear.hpp"

#include <cmath>
#include <utility>

namespace {

constexpr uint16_t kIna232ManufacturerId = 0x5449;
constexpr uint16_t kIna232DefaultConfiguration = 0x4127;
constexpr uint16_t kIna232OverCurrentAlertConfiguration = 0x8001;
constexpr uint16_t kIna232MaskWritableBits = 0xFC03;
constexpr uint16_t kIna232ConfigurationWritableBits = 0x1FFF;
constexpr double kIna232ShuntVoltageLsb = 2.5e-6;
constexpr double kIna232ShuntPositiveFullScaleVolts = 0x7FFF * kIna232ShuntVoltageLsb;
constexpr std::size_t kAfeBlockCount = 5;

std::string hexValue(uint32_t value, unsigned width) {
    std::ostringstream os;
    os << "0x" << std::hex << std::uppercase << std::setw(width)
       << std::setfill('0') << value;
    return os.str();
}

}  // namespace

I2CMezzDrivers::HDMezzDriver::HDMezzDriver()
    : HDMezzDriver(
          "/dev/i2c-2",
          [](const std::string& path, uint8_t address) {
              return std::make_unique<I2CDevice>(path, address);
          },
          [](std::chrono::milliseconds duration) {
              std::this_thread::sleep_for(duration);
          }) {}

I2CMezzDrivers::HDMezzDriver::HDMezzDriver(
    std::string devicePath,
    DeviceFactory deviceFactory,
    DelayFunction delayFunction,
    ClockFunction clockFunction)
    : device_path_(std::move(devicePath)),
      device_factory_(std::move(deviceFactory)),
      delay_(std::move(delayFunction)),
      clock_(std::move(clockFunction)) {
    if (device_path_.empty()) {
        throw std::invalid_argument("HDMezzDriver I2C device path cannot be empty");
    }
    if (!device_factory_) {
        throw std::invalid_argument("HDMezzDriver device factory cannot be empty");
    }
    if (!delay_) {
        throw std::invalid_argument("HDMezzDriver delay function cannot be empty");
    }
    if (!clock_) {
        throw std::invalid_argument("HDMezzDriver clock function cannot be empty");
    }

    const auto createDevice = [this](uint8_t address, const char* name) {
        auto device = device_factory_(device_path_, address);
        if (!device) {
            throw std::runtime_error(std::string("HDMezzDriver factory returned null for ") + name +
                                     " at " + hexValue(address, 2));
        }
        return device;
    };

    mux_ = createDevice(I2C_drivers_defines::I2CDevicesAddress.at("I2C_EXP_MEZZ"), "mezzanine mux");
    ina_5V_ = createDevice(I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"), "5V INA232");
    ina_3V3_ = createDevice(I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"), "3V3/CE INA232");
    tca9536_ = createDevice(I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_ADDR"), "TCA9536");
    configureCalibrationValuesUnlocked();
}

void I2CMezzDrivers::HDMezzDriver::validateAfeBlock(uint8_t afeBlock) {
    if (afeBlock >= kAfeBlockCount) {
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
}

void I2CMezzDrivers::HDMezzDriver::validateRail(const std::string &rail) {
    if (rail != "5V" && rail != "3V3") {
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

I2CMezzDrivers::HDMezzDriver::RailCalibration
I2CMezzDrivers::HDMezzDriver::calculateRailCalibration(
    double rShunt,
    double maxCurrentScale,
    double maxCurrentShutdown,
    double nominalVoltage) {
    if (!std::isfinite(rShunt) || rShunt <= 0.0) {
        throw std::invalid_argument("Rshunt must be finite and greater than zero");
    }
    if (!std::isfinite(maxCurrentScale) || maxCurrentScale <= 0.0) {
        throw std::invalid_argument("Maximum current scale must be finite and greater than zero");
    }
    if (!std::isfinite(maxCurrentShutdown) || maxCurrentShutdown <= 0.0) {
        throw std::invalid_argument("Maximum current shutdown must be finite and greater than zero");
    }
    if (maxCurrentShutdown > maxCurrentScale) {
        throw std::invalid_argument("Maximum current shutdown cannot exceed the measurement scale");
    }
    if (maxCurrentScale * rShunt > kIna232ShuntPositiveFullScaleVolts) {
        throw std::invalid_argument(
            "Current scale and Rshunt exceed the positive INA232 shunt range");
    }

    const double currentLsb = maxCurrentScale / 32768.0;
    const double shuntCalValue = 0.00512 / (currentLsb * rShunt);
    if (!std::isfinite(shuntCalValue) || shuntCalValue < 1.0 || shuntCalValue > 0x7FFF) {
        throw std::invalid_argument("INA232 shunt calibration value is outside 1..0x7FFF");
    }

    const double maxPower = maxCurrentShutdown * nominalVoltage;
    const double alertLimitValue =
        (maxCurrentShutdown * rShunt) / kIna232ShuntVoltageLsb;
    if (!std::isfinite(alertLimitValue) || alertLimitValue < 1.0 ||
        alertLimitValue > 0x7FFF) {
        throw std::invalid_argument("INA232 shunt-overvoltage alert limit is outside 1..0x7FFF");
    }
    // Preserve exact integer thresholds (for example, 3072) that can land a
    // few ulps below the integer when represented as binary floating point.
    const double quantizedAlertLimit = std::floor(alertLimitValue + 1e-9);

    return RailCalibration{
        currentLsb,
        static_cast<uint16_t>(shuntCalValue),
        maxPower,
        static_cast<uint16_t>(quantizedAlertLimit)
    };
}

void I2CMezzDrivers::HDMezzDriver::configureCalibrationValuesUnlocked(){
    for(std::size_t afeBlock = 0; afeBlock < kAfeBlockCount; ++afeBlock){
        const auto rail5V = calculateRailCalibration(
            r_shunt_5V[afeBlock], max_current_5V_scale[afeBlock],
            max_current_5V_shutdown[afeBlock], 5.0);
        const auto rail3V3 = calculateRailCalibration(
            r_shunt_3V3[afeBlock], max_current_3V3_scale[afeBlock],
            max_current_3V3_shutdown[afeBlock], 3.3);

        current_lsb_5V[afeBlock] = rail5V.currentLsb;
        shunt_cal_5V[afeBlock] = rail5V.shuntCal;
        max_power_5V[afeBlock] = rail5V.maxPower;
        alert_limit_5V[afeBlock] = rail5V.alertLimit;
        current_lsb_3V3[afeBlock] = rail3V3.currentLsb;
        shunt_cal_3V3[afeBlock] = rail3V3.shuntCal;
        max_power_3V3[afeBlock] = rail3V3.maxPower;
        alert_limit_3V3[afeBlock] = rail3V3.alertLimit;
    }
}

void I2CMezzDrivers::HDMezzDriver::requireEnabledUnlocked(uint8_t afeBlock) const {
    if (!enabled_afeBlocks[afeBlock]) {
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled");
    }
}

void I2CMezzDrivers::HDMezzDriver::requireConfiguredUnlocked(uint8_t afeBlock) const {
    requireEnabledUnlocked(afeBlock);
    if (!configured_afeBlocks[afeBlock]) {
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not configured");
    }
}

void I2CMezzDrivers::HDMezzDriver::enableAfeBlock(uint8_t afeBlock, bool enable){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    if (enable && enabled_afeBlocks[afeBlock]) {
        return;
    }
    invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable,
        "Block enable/disable attempted; awaiting a new monitoring sample");

    if (enable) {
        // Force unknown/stale output state safe before doing any INA probing.
        initializeTcaSafeUnlocked(afeBlock);
        probeAfeBlockUnlocked(afeBlock);
        configured_afeBlocks[afeBlock] = false;
        enabled_afeBlocks[afeBlock] = true;
        return;
    }

    initializeTcaSafeUnlocked(afeBlock);
    configured_afeBlocks[afeBlock] = false;
    enabled_afeBlocks[afeBlock] = false;
    alert_history_[afeBlock] = {}; // Only after successful safe disable.
}

bool I2CMezzDrivers::HDMezzDriver::isAfeBlockEnabled(uint8_t afeBlock) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    return enabled_afeBlocks[afeBlock];
}

bool I2CMezzDrivers::HDMezzDriver::isAfeBlockConfigured(uint8_t afeBlock) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    return configured_afeBlocks[afeBlock];
}

void I2CMezzDrivers::HDMezzDriver::probeAfeBlock(uint8_t afeBlock) {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    probeAfeBlockUnlocked(afeBlock);
}

void I2CMezzDrivers::HDMezzDriver::setRShunt(uint8_t afeBlock, double rShunt, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        const auto derived = calculateRailCalibration(
            rShunt, max_current_5V_scale[afeBlock], max_current_5V_shutdown[afeBlock], 5.0);
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Shunt setting update attempted");
        if (enabled_afeBlocks[afeBlock]) {
            setPowerRequestsUnlocked(afeBlock, false, false);
        }
        r_shunt_5V[afeBlock] = rShunt;
        current_lsb_5V[afeBlock] = derived.currentLsb;
        shunt_cal_5V[afeBlock] = derived.shuntCal;
        max_power_5V[afeBlock] = derived.maxPower;
        alert_limit_5V[afeBlock] = derived.alertLimit;
    }
    else {
        const auto derived = calculateRailCalibration(
            rShunt, max_current_3V3_scale[afeBlock], max_current_3V3_shutdown[afeBlock], 3.3);
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Shunt setting update attempted");
        if (enabled_afeBlocks[afeBlock]) {
            setPowerRequestsUnlocked(afeBlock, false, false);
        }
        r_shunt_3V3[afeBlock] = rShunt;
        current_lsb_3V3[afeBlock] = derived.currentLsb;
        shunt_cal_3V3[afeBlock] = derived.shuntCal;
        max_power_3V3[afeBlock] = derived.maxPower;
        alert_limit_3V3[afeBlock] = derived.alertLimit;
    }
    configured_afeBlocks[afeBlock] = false;
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrentScale(uint8_t afeBlock, double maxCurrent, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        const auto derived = calculateRailCalibration(
            r_shunt_5V[afeBlock], maxCurrent, max_current_5V_shutdown[afeBlock], 5.0);
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Current scale update attempted");
        if (enabled_afeBlocks[afeBlock]) {
            setPowerRequestsUnlocked(afeBlock, false, false);
        }
        max_current_5V_scale[afeBlock] = maxCurrent;
        current_lsb_5V[afeBlock] = derived.currentLsb;
        shunt_cal_5V[afeBlock] = derived.shuntCal;
        max_power_5V[afeBlock] = derived.maxPower;
        alert_limit_5V[afeBlock] = derived.alertLimit;
    }
    else {
        const auto derived = calculateRailCalibration(
            r_shunt_3V3[afeBlock], maxCurrent, max_current_3V3_shutdown[afeBlock], 3.3);
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Current scale update attempted");
        if (enabled_afeBlocks[afeBlock]) {
            setPowerRequestsUnlocked(afeBlock, false, false);
        }
        max_current_3V3_scale[afeBlock] = maxCurrent;
        current_lsb_3V3[afeBlock] = derived.currentLsb;
        shunt_cal_3V3[afeBlock] = derived.shuntCal;
        max_power_3V3[afeBlock] = derived.maxPower;
        alert_limit_3V3[afeBlock] = derived.alertLimit;
    }
    configured_afeBlocks[afeBlock] = false;
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrentShutdown(uint8_t afeBlock, double maxCurrent, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        const auto derived = calculateRailCalibration(
            r_shunt_5V[afeBlock], max_current_5V_scale[afeBlock], maxCurrent, 5.0);
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Current shutdown setting update attempted");
        if (enabled_afeBlocks[afeBlock]) {
            setPowerRequestsUnlocked(afeBlock, false, false);
        }
        max_current_5V_shutdown[afeBlock] = maxCurrent;
        current_lsb_5V[afeBlock] = derived.currentLsb;
        shunt_cal_5V[afeBlock] = derived.shuntCal;
        max_power_5V[afeBlock] = derived.maxPower;
        alert_limit_5V[afeBlock] = derived.alertLimit;
    }
    else {
        const auto derived = calculateRailCalibration(
            r_shunt_3V3[afeBlock], max_current_3V3_scale[afeBlock], maxCurrent, 3.3);
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Current shutdown setting update attempted");
        if (enabled_afeBlocks[afeBlock]) {
            setPowerRequestsUnlocked(afeBlock, false, false);
        }
        max_current_3V3_shutdown[afeBlock] = maxCurrent;
        current_lsb_3V3[afeBlock] = derived.currentLsb;
        shunt_cal_3V3[afeBlock] = derived.shuntCal;
        max_power_3V3[afeBlock] = derived.maxPower;
        alert_limit_3V3[afeBlock] = derived.alertLimit;
    }
    configured_afeBlocks[afeBlock] = false;
}

double I2CMezzDrivers::HDMezzDriver::getRShunt(uint8_t afeBlock, const std::string &rail) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        return r_shunt_5V[afeBlock];
    }
    return r_shunt_3V3[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrentScale(uint8_t afeBlock, const std::string &rail) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        return max_current_5V_scale[afeBlock];
    }
    return max_current_3V3_scale[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrentShutdown(uint8_t afeBlock, const std::string &rail) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        return max_current_5V_shutdown[afeBlock];
    }
    return max_current_3V3_shutdown[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxPower(uint8_t afeBlock, const std::string &rail) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        return max_power_5V[afeBlock];
    }
    return max_power_3V3[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getCurrentLsb(uint8_t afeBlock, const std::string &rail) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        return current_lsb_5V[afeBlock];
    }
    return current_lsb_3V3[afeBlock];
}

uint16_t I2CMezzDrivers::HDMezzDriver::getShuntCal(uint8_t afeBlock, const std::string &rail) const {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    if(rail == "5V"){
        return shunt_cal_5V[afeBlock];
    }
    return shunt_cal_3V3[afeBlock];
}

I2CMezzDrivers::HDMezzDriver::ConfigurationSnapshot
I2CMezzDrivers::HDMezzDriver::readBlockConfiguration(uint8_t afeBlock) {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    auto result = readBlockConfigurationUnlocked(afeBlock);
    if (result.quality != ReadbackQuality::Good) {
        const auto quality = result.quality == ReadbackQuality::Error ? MonitorQuality::Error :
            result.quality == ReadbackQuality::Invalid ? MonitorQuality::Invalid : MonitorQuality::Unavailable;
        invalidateMonitoringUnlocked(afeBlock, quality, "Calibration readback is unavailable or invalid");
    } else if (result.observedShuntCal != result.requestedShuntCal) {
        // GOOD raw calibration readback is not GOOD scaled measurement data.
        // Do not disable monitoring or change the established alert/power policy.
        invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Invalid, "Observed calibration differs from requested scaling");
    }
    return result;
}

I2CMezzDrivers::HDMezzDriver::ConfigurationSnapshot
I2CMezzDrivers::HDMezzDriver::readBlockConfigurationUnlocked(uint8_t afeBlock) {
    ConfigurationSnapshot result;
    result.afeBlock = afeBlock;
    result.enabled = enabled_afeBlocks[afeBlock];
    result.configured = configured_afeBlocks[afeBlock];
    result.requestedSettingsAvailable = true;
    result.requested = {r_shunt_5V[afeBlock], r_shunt_3V3[afeBlock],
        max_current_5V_scale[afeBlock], max_current_3V3_scale[afeBlock],
        max_current_5V_shutdown[afeBlock], max_current_3V3_shutdown[afeBlock]};
    result.currentLsb = {current_lsb_5V[afeBlock], current_lsb_3V3[afeBlock]};
    result.maxPower = {max_power_5V[afeBlock], max_power_3V3[afeBlock]};
    result.requestedShuntCal = {shunt_cal_5V[afeBlock], shunt_cal_3V3[afeBlock]};
    if (!result.enabled) return result;

    try {
        result.acquisitionStartedNs = clock_();
        if (!result.acquisitionStartedNs) {
            result.quality = ReadbackQuality::Invalid;
            result.detail = "Missing monotonic acquisition time; no bus access";
            return result;
        }
        const std::array<uint8_t, 2> addresses = {
            I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"),
            I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR")};
        const auto idRegister = I2C_drivers_defines::HDMezzAddressMap.at("INA232_MANUFACTURER_ID_REG");
        const auto calRegister = I2C_drivers_defines::HDMezzAddressMap.at("INA232_CALIBRATION_REG");
        const auto identitiesMatch = [&] {
            const auto first = readINA232RegisterUnlocked(afeBlock, addresses[0], idRegister);
            const auto second = readINA232RegisterUnlocked(afeBlock, addresses[1], idRegister);
            return first == kIna232ManufacturerId && second == kIna232ManufacturerId;
        };
        // TI ID is an address/wiring sanity check, not a unique device/model ID.
        if (!identitiesMatch()) {
            result.quality = ReadbackQuality::Invalid;
            result.detail = "Unexpected INA232 manufacturer identity before calibration read";
            return result;
        }
        std::array<uint16_t, 2> first{}, second{};
        for (size_t i = 0; i < addresses.size(); ++i)
            first[i] = readINA232RegisterUnlocked(afeBlock, addresses[i], calRegister);
        for (size_t i = 0; i < addresses.size(); ++i)
            second[i] = readINA232RegisterUnlocked(afeBlock, addresses[i], calRegister);
        if (!identitiesMatch() || first != second || (first[0] & 0x8000u) || (first[1] & 0x8000u)) {
            result.quality = ReadbackQuality::Invalid;
            result.detail = "Changed identity/calibration or nonzero reserved calibration bit";
            return result;
        }
        const auto completed = clock_();
        if (completed < result.acquisitionStartedNs ||
            completed - result.acquisitionStartedNs > kMaxConfigurationReadNs) {
            result.quality = ReadbackQuality::Invalid;
            result.detail = "Invalid or excessive calibration acquisition interval (100 ms limit)";
            return result;
        }
        result.observedShuntCal = first;
        result.observedNs = completed;
        result.quality = ReadbackQuality::Good;
        result.detail = "Cached requested/derived settings; fresh stable calibration-register pair. "
                        "No fresh protection-configuration or physical calibration claim";
    } catch (const std::exception&) {
        // No partial pair or previous successful sample is substituted on error.
        result.quality = ReadbackQuality::Error;
        result.detail = "Mezzanine calibration acquisition failed; no complete readback";
    }
    return result;
}

void I2CMezzDrivers::HDMezzDriver::configureHdMezzAfeBlock(uint8_t afeBlock){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    requireEnabledUnlocked(afeBlock);
    configureHdMezzAfeBlockUnlocked(afeBlock);
}

void I2CMezzDrivers::HDMezzDriver::configureHdMezzAfeBlockUnlocked(uint8_t afeBlock){
    invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable,
        "Block programming attempted; awaiting a new monitoring sample");
    configured_afeBlocks[afeBlock] = false;

    initializeTcaSafeUnlocked(afeBlock);
    probeAfeBlockUnlocked(afeBlock);

    const uint8_t address5V = I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR");
    const uint8_t address3V3 = I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR");
    const uint8_t configRegister = I2C_drivers_defines::HDMezzAddressMap.at("INA232_CONF_REG");
    const uint8_t calibrationRegister = I2C_drivers_defines::HDMezzAddressMap.at("INA232_CALIBRATION_REG");
    const uint8_t maskRegister = I2C_drivers_defines::HDMezzAddressMap.at("INA232_MASK_ENABLE_REG");
    const uint8_t limitRegister = I2C_drivers_defines::HDMezzAddressMap.at("INA232_ALERT_LIMIT_REG");

    const auto configureIna = [this, afeBlock, configRegister, calibrationRegister,
                               maskRegister, limitRegister](uint8_t address,
                                                           uint16_t shuntCal,
                                                           uint16_t alertLimit) {
        writeINA232RegisterVerifiedUnlocked(afeBlock, address, configRegister,
                                            kIna232DefaultConfiguration,
                                            kIna232ConfigurationWritableBits);
        writeINA232RegisterVerifiedUnlocked(afeBlock, address, calibrationRegister,
                                            shuntCal, 0x7FFF);
        writeINA232RegisterVerifiedUnlocked(afeBlock, address, limitRegister,
                                            alertLimit);
        writeINA232RegisterVerifiedUnlocked(afeBlock, address, maskRegister,
                                            kIna232OverCurrentAlertConfiguration,
                                            kIna232MaskWritableBits);
    };

    configureIna(address5V, shunt_cal_5V[afeBlock], alert_limit_5V[afeBlock]);
    configureIna(address3V3, shunt_cal_3V3[afeBlock], alert_limit_3V3[afeBlock]);
    configured_afeBlocks[afeBlock] = true;
}

void I2CMezzDrivers::HDMezzDriver::configureHdMezzAfeBlock(uint8_t afeBlock, const BlockConfiguration& c) {
    // Validate the complete candidate before mutating state or touching hardware.
    validateAfeBlock(afeBlock);
    const auto rail5V = calculateRailCalibration(c.rShunt5V, c.maxCurrentScale5V, c.maxCurrentShutdown5V, 5.0);
    const auto rail3V3 = calculateRailCalibration(c.rShunt3V3, c.maxCurrentScale3V3, c.maxCurrentShutdown3V3, 3.3);
    std::unique_lock<std::mutex> lock(mutex_);
    requireEnabledUnlocked(afeBlock);
    const BlockConfiguration old{r_shunt_5V[afeBlock], r_shunt_3V3[afeBlock], max_current_5V_scale[afeBlock], max_current_3V3_scale[afeBlock], max_current_5V_shutdown[afeBlock], max_current_3V3_shutdown[afeBlock]};
    r_shunt_5V[afeBlock]=c.rShunt5V; r_shunt_3V3[afeBlock]=c.rShunt3V3;
    max_current_5V_scale[afeBlock]=c.maxCurrentScale5V; max_current_3V3_scale[afeBlock]=c.maxCurrentScale3V3;
    max_current_5V_shutdown[afeBlock]=c.maxCurrentShutdown5V; max_current_3V3_shutdown[afeBlock]=c.maxCurrentShutdown3V3;
    current_lsb_5V[afeBlock]=rail5V.currentLsb; shunt_cal_5V[afeBlock]=rail5V.shuntCal; max_power_5V[afeBlock]=rail5V.maxPower; alert_limit_5V[afeBlock]=rail5V.alertLimit;
    current_lsb_3V3[afeBlock]=rail3V3.currentLsb; shunt_cal_3V3[afeBlock]=rail3V3.shuntCal; max_power_3V3[afeBlock]=rail3V3.maxPower; alert_limit_3V3[afeBlock]=rail3V3.alertLimit;
    try { configureHdMezzAfeBlockUnlocked(afeBlock); }
    catch (...) { r_shunt_5V[afeBlock]=old.rShunt5V; r_shunt_3V3[afeBlock]=old.rShunt3V3; max_current_5V_scale[afeBlock]=old.maxCurrentScale5V; max_current_3V3_scale[afeBlock]=old.maxCurrentScale3V3; max_current_5V_shutdown[afeBlock]=old.maxCurrentShutdown5V; max_current_3V3_shutdown[afeBlock]=old.maxCurrentShutdown3V3; configureCalibrationValuesUnlocked(); configured_afeBlocks[afeBlock]=false; throw; }
}

void I2CMezzDrivers::HDMezzDriver::setPowerRequests(
    uint8_t afeBlock, bool power5V, bool power3V3) {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    setPowerRequestsUnlocked(afeBlock, power5V, power3V3);
}

I2CMezzDrivers::HDMezzDriver::PowerRequests
I2CMezzDrivers::HDMezzDriver::readPowerRequests(uint8_t afeBlock) {
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    return readPowerRequestsUnlocked(afeBlock);
}

void I2CMezzDrivers::HDMezzDriver::powerOn_HDMezzAfeBlock(
    uint8_t afeBlock, bool powerOn, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    requireEnabledUnlocked(afeBlock);
    if (powerOn) requireConfiguredUnlocked(afeBlock);
    invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Rail power request update attempted");
    const auto current = readPowerRequestsUnlocked(afeBlock);
    if (rail == "5V") {
        setPowerRequestsUnlocked(afeBlock, powerOn, current.power3V3);
    } else {
        setPowerRequestsUnlocked(afeBlock, current.power5V, powerOn);
    }
}

bool I2CMezzDrivers::HDMezzDriver::isPowerOn(uint8_t afeBlock, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    const auto state = readPowerRequestsUnlocked(afeBlock);
    return rail == "5V" ? state.power5V : state.power3V3;
}

double I2CMezzDrivers::HDMezzDriver::readRailVoltage(uint8_t afeBlock, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    requireConfiguredUnlocked(afeBlock);
    const uint8_t address = I2C_drivers_defines::HDMezzAddressMap.at("INA232_" + rail + "_ADDR");
    const uint16_t raw = readINA232FunctionUnlocked(afeBlock, address, "VBUS");
    return static_cast<double>(raw) * 1.6e-3; // V
}

double I2CMezzDrivers::HDMezzDriver::readRailCurrent(uint8_t afeBlock, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    requireConfiguredUnlocked(afeBlock);
    const uint8_t address = I2C_drivers_defines::HDMezzAddressMap.at("INA232_" + rail + "_ADDR");
    const uint16_t raw = readINA232FunctionUnlocked(afeBlock, address, "CURRENT");
    const int32_t signedRaw = (raw & 0x8000u) != 0
        ? static_cast<int32_t>(raw) - 0x10000
        : static_cast<int32_t>(raw);
    const double currentLsb = rail == "5V" ? current_lsb_5V[afeBlock]
                                             : current_lsb_3V3[afeBlock];
    return static_cast<double>(signedRaw) * currentLsb * 1000.0; // mA
}

double I2CMezzDrivers::HDMezzDriver::readRailPower(uint8_t afeBlock, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    requireConfiguredUnlocked(afeBlock);
    const uint8_t address = I2C_drivers_defines::HDMezzAddressMap.at("INA232_" + rail + "_ADDR");
    const uint16_t raw = readINA232FunctionUnlocked(afeBlock, address, "POWER");
    const double currentLsb = rail == "5V" ? current_lsb_5V[afeBlock]
                                             : current_lsb_3V3[afeBlock];
    return 32.0 * static_cast<double>(raw) * currentLsb * 1000.0; // mW
}

bool I2CMezzDrivers::HDMezzDriver::checkAlertStatus(uint8_t afeBlock, const std::string &rail){
    std::lock_guard<std::mutex> lock(mutex_);
    validateAfeBlock(afeBlock);
    validateRail(rail);
    requireConfiguredUnlocked(afeBlock);
    invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable,
        "Explicit clearing alert read; awaiting a complete monitoring sample");
    // Records alert evidence before the existing immediate power-request removal.
    return (readAlertStatusUnlocked(afeBlock, rail == "5V" ? 0 : 1) & 0x0010u) != 0;
}

void I2CMezzDrivers::HDMezzDriver::selectAfeBlockUnlocked(uint8_t afeBlock){
    validateAfeBlock(afeBlock);
    const std::string key = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    mux_->writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(key));
}

I2CRegisterDevice& I2CMezzDrivers::HDMezzDriver::inaDeviceUnlocked(uint8_t deviceAddress) {
    if (deviceAddress == I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR")) {
        return *ina_5V_;
    }
    if (deviceAddress == I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR")) {
        return *ina_3V3_;
    }
    throw std::invalid_argument("Unsupported INA232 address " + hexValue(deviceAddress, 2));
}

uint16_t I2CMezzDrivers::HDMezzDriver::readINA232RegisterUnlocked(
    uint8_t afeBlock, uint8_t deviceAddress, uint8_t registerAddress){
    selectAfeBlockUnlocked(afeBlock);
    std::vector<uint8_t> register_bytes;
    inaDeviceUnlocked(deviceAddress).readBytes(registerAddress, register_bytes, 2);
    if (register_bytes.size() != 2) {
        throw std::runtime_error("INA232 read returned an invalid byte count");
    }
    return (static_cast<uint16_t>(register_bytes[0]) << 8) | static_cast<uint16_t>(register_bytes[1]);
}

void I2CMezzDrivers::HDMezzDriver::writeINA232RegisterVerifiedUnlocked(
    uint8_t afeBlock,
    uint8_t deviceAddress,
    uint8_t registerAddress,
    uint16_t value,
    uint16_t verificationMask){
    selectAfeBlockUnlocked(afeBlock);
    const std::vector<uint8_t> registerBytes = {
        static_cast<uint8_t>((value >> 8) & 0xFF),
        static_cast<uint8_t>(value & 0xFF)
    };
    inaDeviceUnlocked(deviceAddress).writeBytes(registerAddress, registerBytes);
    const uint16_t readback =
        readINA232RegisterUnlocked(afeBlock, deviceAddress, registerAddress);
    if ((readback & verificationMask) != (value & verificationMask)) {
        std::ostringstream os;
        os << "INA232 verification failed for AFE block " << static_cast<unsigned>(afeBlock)
           << ", address " << hexValue(deviceAddress, 2)
           << ", register " << hexValue(registerAddress, 2)
           << ": expected " << hexValue(value, 4)
           << ", read " << hexValue(readback, 4)
           << ", mask " << hexValue(verificationMask, 4);
        throw std::runtime_error(os.str());
    }
}

uint16_t I2CMezzDrivers::HDMezzDriver::readINA232FunctionUnlocked(
    uint8_t afeBlock, uint8_t deviceAddress, const std::string &functionName){
    const auto it = I2C_drivers_defines::INA232FunctionDict.find(functionName);
    if(it == I2C_drivers_defines::INA232FunctionDict.end()){
        throw std::invalid_argument("Invalid INA232 function name: " + functionName);
    }
    
    const auto& bitField = it->second;
    const uint8_t registerAddr = bitField.begin()->first;
    const uint8_t msbPos = bitField.begin()->second.first;
    const uint8_t lsbPos = bitField.begin()->second.second;
    const unsigned width = msbPos - lsbPos + 1;
    const uint16_t fieldMask = width == 16 ? 0xFFFF
                                           : static_cast<uint16_t>((1u << width) - 1u);
    const uint16_t registerValue =
        readINA232RegisterUnlocked(afeBlock, deviceAddress, registerAddr);
    return static_cast<uint16_t>((registerValue >> lsbPos) & fieldMask);
}

void I2CMezzDrivers::HDMezzDriver::writeINA232FunctionUnlocked(
    uint8_t afeBlock, uint8_t deviceAddress, const std::string &functionName, uint16_t value){
    const auto it = I2C_drivers_defines::INA232FunctionDict.find(functionName);
    if(it == I2C_drivers_defines::INA232FunctionDict.end()){
        throw std::invalid_argument("Invalid INA232 function name: " + functionName);
    }
    
    const auto& bitField = it->second;
    const uint8_t registerAddr = bitField.begin()->first;
    const uint8_t msbPos = bitField.begin()->second.first;
    const uint8_t lsbPos = bitField.begin()->second.second;
    const unsigned width = msbPos - lsbPos + 1;
    const uint32_t fieldMax = width == 16 ? 0xFFFFu : ((1u << width) - 1u);
    if (value > fieldMax) {
        throw std::invalid_argument("Value does not fit INA232 function " + functionName);
    }

    const uint16_t mask = static_cast<uint16_t>(fieldMax << lsbPos);
    uint16_t registerValue =
        readINA232RegisterUnlocked(afeBlock, deviceAddress, registerAddr);
    registerValue = static_cast<uint16_t>(
        (registerValue & ~mask) | ((value << lsbPos) & mask));
    writeINA232RegisterVerifiedUnlocked(
        afeBlock, deviceAddress, registerAddr, registerValue, mask);
}

uint8_t I2CMezzDrivers::HDMezzDriver::readTCA9536RegisterUnlocked(
    uint8_t afeBlock, uint8_t registerAddress){
    selectAfeBlockUnlocked(afeBlock);
    uint8_t registerValue = 0;
    tca9536_->readByte(registerAddress, registerValue);
    return registerValue;
}

void I2CMezzDrivers::HDMezzDriver::writeTCA9536RegisterVerifiedUnlocked(
    uint8_t afeBlock,
    uint8_t registerAddress,
    uint8_t value,
    uint8_t verificationMask){
    selectAfeBlockUnlocked(afeBlock);
    tca9536_->writeByte(registerAddress, value);
    const uint8_t readback = readTCA9536RegisterUnlocked(afeBlock, registerAddress);
    if ((readback & verificationMask) != (value & verificationMask)) {
        std::ostringstream os;
        os << "TCA9536 verification failed for AFE block " << static_cast<unsigned>(afeBlock)
           << ", register " << hexValue(registerAddress, 2)
           << ": expected " << hexValue(value, 2)
           << ", read " << hexValue(readback, 2)
           << ", mask " << hexValue(verificationMask, 2);
        throw std::runtime_error(os.str());
    }
}

void I2CMezzDrivers::HDMezzDriver::probeAfeBlockUnlocked(uint8_t afeBlock) {
    validateAfeBlock(afeBlock);
    (void)readTCA9536RegisterUnlocked(
        afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"));
    (void)readTCA9536RegisterUnlocked(
        afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_CONF_REG"));

    const uint8_t manufacturerRegister =
        I2C_drivers_defines::HDMezzAddressMap.at("INA232_MANUFACTURER_ID_REG");
    const uint8_t address5V = I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR");
    const uint8_t address3V3 = I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR");
    const uint16_t id5V =
        readINA232RegisterUnlocked(afeBlock, address5V, manufacturerRegister);
    const uint16_t id3V3 =
        readINA232RegisterUnlocked(afeBlock, address3V3, manufacturerRegister);
    if (id5V != kIna232ManufacturerId || id3V3 != kIna232ManufacturerId) {
        std::ostringstream os;
        os << "HD mezzanine probe failed for AFE block " << static_cast<unsigned>(afeBlock)
           << ": expected INA232 manufacturer ID " << hexValue(kIna232ManufacturerId, 4)
           << ", read 5V=" << hexValue(id5V, 4)
           << ", 3V3/CE=" << hexValue(id3V3, 4);
        throw std::runtime_error(os.str());
    }
}

void I2CMezzDrivers::HDMezzDriver::initializeTcaSafeUnlocked(uint8_t afeBlock) {
    const uint8_t outputRegister =
        I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG");
    const uint8_t configRegister =
        I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_CONF_REG");
    const uint8_t oldOutput = readTCA9536RegisterUnlocked(afeBlock, outputRegister);
    const uint8_t safeOutput = static_cast<uint8_t>(oldOutput & ~0x03u);

    // Preload both rail request latches low before P0/P1 become outputs.
    writeTCA9536RegisterVerifiedUnlocked(afeBlock, outputRegister, safeOutput, 0x03);
    // P0/P1 are rail-request outputs; P2/P3 remain inputs. Upper bits are reserved.
    writeTCA9536RegisterVerifiedUnlocked(afeBlock, configRegister, 0xFC, 0x0F);
}

I2CMezzDrivers::HDMezzDriver::PowerRequests
I2CMezzDrivers::HDMezzDriver::readPowerRequestsUnlocked(uint8_t afeBlock) {
    requireEnabledUnlocked(afeBlock);
    const uint8_t output = readTCA9536RegisterUnlocked(
        afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"));
    return PowerRequests{(output & 0x01u) != 0, (output & 0x02u) != 0, output};
}

void I2CMezzDrivers::HDMezzDriver::setPowerRequestsUnlocked(
    uint8_t afeBlock, bool power5V, bool power3V3) {
    requireEnabledUnlocked(afeBlock);
    if (power5V || power3V3) {
        requireConfiguredUnlocked(afeBlock);
    }
    invalidateMonitoringUnlocked(afeBlock, MonitorQuality::Unavailable, "Rail power request update attempted");

    const uint8_t outputRegister =
        I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG");
    const uint8_t oldOutput = readTCA9536RegisterUnlocked(afeBlock, outputRegister);
    const uint8_t requestedBits = static_cast<uint8_t>((power5V ? 0x01u : 0u) |
                                                        (power3V3 ? 0x02u : 0u));
    const uint8_t newOutput =
        static_cast<uint8_t>((oldOutput & ~0x03u) | requestedBits);
    if (newOutput == oldOutput) {
        return;
    }
    writeTCA9536RegisterVerifiedUnlocked(afeBlock, outputRegister, newOutput, 0x03);
    delay_(std::chrono::milliseconds(10));
}

I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::PJT004A0X43_SRZ_Driver():
    REG_3VD3(board_pl_i2c_adapter(), I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_3VD3"), 1),
    REG_2VA1(board_pl_i2c_adapter(), I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_2VA1"), 1),
    REG_3VA6(board_pl_i2c_adapter(), I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_3VA6"), 1),
    REG_1VD8(board_pl_i2c_adapter(), I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_1VD8"), 1){}


I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::~PJT004A0X43_SRZ_Driver(){}

I2CDevice& I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::regulator(uint8_t number) {
    switch (number) {
        case 0: return REG_3VD3;
        case 1: return REG_2VA1;
        case 2: return REG_3VA6;
        case 3: return REG_1VD8;
        default: throw std::invalid_argument("Invalid regulator number; expected 0..3");
    }
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::readRailVoltage(const uint8_t& number) {
    auto& device = regulator(number);
    const auto mode = device.readByteSMBus(0x20);
    const auto raw = device.readWordSMBus(0x8b);
    if (device.readByteSMBus(0x20) != mode)
        throw std::runtime_error("Regulator VOUT_MODE changed across voltage read");
    return daphne_sc::pmbus_linear16(raw, mode);
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::readRailCurrent(const uint8_t& number) {
    return daphne_sc::pmbus_linear11(regulator(number).readWordSMBus(0x8c));
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::readTemperature(const uint8_t& number) {
    return daphne_sc::pmbus_linear11(regulator(number).readWordSMBus(0x8e));
}

I2CADCsDrivers::ADS7138_Driver::ADS7138_Driver(const uint8_t &deviceAddress):
    deviceAddress(deviceAddress),
    ADC_ADS7138(board_ps_i2c_adapter(), deviceAddress){
        this->configureDevice();
    }

I2CADCsDrivers::ADS7138_Driver::~ADS7138_Driver(){}

uint8_t I2CADCsDrivers::ADS7138_Driver::getChannelsListByte(const std::vector<bool> &channelsList){
    if(channelsList.size() != 8){
        throw std::invalid_argument("Channels list must have exactly 8 elements.");
    }
    uint8_t result = 0;
    for(size_t i = 0; i < channelsList.size(); ++i){
        if(channelsList[i]){
            result |= (1 << i);
        }
    }
    return result;
}

void I2CADCsDrivers::ADS7138_Driver::resetDevice(){

    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG), 0b00000001);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    uint8_t general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG)); // just to ensure the write is done.
    // check only the bite 0
    auto start_time = std::chrono::high_resolution_clock::now();
    while(general_config & 0b00000001){
        general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG));
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        // timeout condition
        if(std::chrono::high_resolution_clock::now() - start_time > std::chrono::milliseconds(100)){
            throw std::runtime_error("Timeout waiting for ADS7138 reset to complete.");
        }
    }
}

void I2CADCsDrivers::ADS7138_Driver::calibrateOffsetError(){
    // Set the CALIBRATE bit in the GENERAL_CFG register
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG), 0b00000010);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    uint8_t general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG)); // just to ensure the write is done.
    // check only the bite 1
    auto start_time = std::chrono::high_resolution_clock::now();
    while(general_config & 0b00000010){
        general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG));
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        // timeout condition
        if(std::chrono::high_resolution_clock::now() - start_time > std::chrono::milliseconds(100)){
            throw std::runtime_error("Timeout waiting for ADS7138 offset error calibration to complete.");
        }
    }
}

void I2CADCsDrivers::ADS7138_Driver::configureDevice(){

    this->resetDevice();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::PIN_CFG), 0b0); // set all pins to analog
    // do the offset error calibration first.
    this->calibrateOffsetError();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    
    // Now, I need to configure the channels that will be read in the auto sequence.
    //First convert the std::vector<bool> to a byte.
    uint8_t channel_config = this->getChannelsListByte(this->enabled_channels);
    //then set the auto sequence register with this value.
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::AUTO_SEQ_CH_SEL), channel_config);
    // Set the oversampling ratio to 128 samples (maximum).
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::OSR_CFG), 0b00000111);
    // Sets the SEQ_CONFIG = 0b01 and SEQ_START = 0b1
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::SEQUENCE_CFG), 0b00010001);
    
    //Let's set the device sampling rate and manual mode.
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::OPMODE_CFG), 0b00001000);// sets to 62.5kSPS / High speed oscillator / Manual mode
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    // Now, the device should be ready to acquire data.

}

void I2CADCsDrivers::ADS7138_Driver::setEnabledChannels(const std::vector<bool> &channelsList){
    if(channelsList.size() != 8){
        throw std::invalid_argument("Channels list must have exactly 8 elements.");
    }
    this->enabled_channels = channelsList;
    uint8_t channel_config = this->getChannelsListByte(this->enabled_channels);
    //then set the auto sequence register with this value.
    this->configureDevice();
}

std::vector<bool> I2CADCsDrivers::ADS7138_Driver::getEnabledChannels() const{
    return this->enabled_channels;
}

void I2CADCsDrivers::ADS7138_Driver::writeSingleRegister(const uint8_t &registerAddress, const uint8_t &value){
    
    // First let's set the data frame. The data frame is composed of:
    // - 1 byte for the opcode
    // - 1 byte for regaddr
    // - 1 byte for data

    std::vector<uint8_t> dataFrame = {static_cast<uint8_t>(I2C_drivers_defines::ADS7138OpCodes::SINGLE_REGISTER_WRITE),
                                      registerAddress,
                                      value};
    this->ADC_ADS7138.writeFrame(dataFrame);
}

uint8_t I2CADCsDrivers::ADS7138_Driver::readSingleRegister(const uint8_t &registerAddress){
    // First let's set the data frame. The data frame is composed of:
    // - 1 byte for the opcode
    // - 1 byte for regaddr
    std::vector<uint8_t> dataFrame = {static_cast<uint8_t>(I2C_drivers_defines::ADS7138OpCodes::SINGLE_REGISTER_READ),
                                      registerAddress};
    this->ADC_ADS7138.writeFrame(dataFrame);
    std::vector<uint8_t> registerValue;
    this->ADC_ADS7138.readFrame(registerValue, 1);
    return registerValue[0];
}

std::vector<double> I2CADCsDrivers::ADS7138_Driver::readData(const uint8_t &numSamples){

    if(numSamples == 0){
        throw std::invalid_argument("Number of samples must be greater than zero.");
    }
    // First, let's determine how many channels are enabled.
    size_t numEnabledChannels = 0;
    for(const auto &channel : this->enabled_channels){
        if(channel){
            numEnabledChannels++;
        }
    }
    if(numEnabledChannels == 0){
        throw std::runtime_error("No channels are enabled. Please enable at least one channel before reading data.");
    }
    // Each sample consists of 2 bytes per channel.
    size_t bytesToRead = numSamples * numEnabledChannels * 2;
    std::vector<uint8_t> rawData(bytesToRead);
    this->ADC_ADS7138.readFrame(rawData, bytesToRead);
    // Now, let's parse the raw data into a vector of double.
    std::vector<double> parsedData;
    parsedData.reserve(numSamples * numEnabledChannels);
    double Vref = 3.3;
    int N = 16;
    for(size_t i = 0; i < bytesToRead; i += 2){
        uint16_t sample = (static_cast<uint16_t>(rawData[i]) << 8) | static_cast<uint16_t>(rawData[i + 1]);
        double voltage = (static_cast<double>(sample) * Vref) / (1u << N);
        parsedData.push_back(voltage);
    }
    return parsedData;
}
