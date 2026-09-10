#include "DaphneI2CDrivers.hpp"

#include <array>
#include <atomic>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

constexpr uint8_t kMuxAddress = 0x71;
constexpr uint8_t kIna3V3Address = 0x40;
constexpr uint8_t kTcaAddress = 0x41;
constexpr uint8_t kIna5VAddress = 0x42;

struct Event {
    enum class Kind { Select, Read, Write };

    Kind kind;
    uint8_t afe;
    uint8_t address;
    int registerAddress;
    std::vector<uint8_t> bytes;
};

struct FakeBusState {
    std::mutex mutex;
    uint8_t selectedAfe{0xFF};
    std::array<std::array<uint16_t, 256>, 5> ina3V3{};
    std::array<std::array<uint16_t, 256>, 5> ina5V{};
    std::array<std::array<uint8_t, 256>, 5> tca{};
    std::vector<Event> events;
    unsigned statusCounter{0};
    bool varyDynamicStatusBits{true};
    bool corruptMaskWritableBit{false};
    bool yieldAfterSelect{false};
    unsigned readCalls{0};
    int failReadCall{-1}, shortReadCall{-1};
    unsigned transferCalls{0};
    int failTransferCall{-1}; // Includes mux selections, TCA and INA transactions.
    bool failTcaOutputWrite{false}, throwAfterTcaOutputWrite{false};
    bool clearAlertOnRead{false};
    std::function<uint16_t(unsigned, uint16_t)> transformRead;
    std::vector<uint64_t> clockValues;
    size_t clockIndex{0};
    uint64_t fixedClock{0};

    void transferLocked() {
        if (static_cast<int>(++transferCalls) == failTransferCall)
            throw std::runtime_error("Injected bus transfer failure");
    }

    FakeBusState() {
        for (std::size_t afe = 0; afe < 5; ++afe) {
            ina3V3[afe][0x00] = 0x4127;
            ina5V[afe][0x00] = 0x4127;
            ina3V3[afe][0x3E] = 0x5449;
            ina5V[afe][0x3E] = 0x5449;
            tca[afe][0x01] = 0xFF;
            tca[afe][0x03] = 0xFF;
        }
    }
};

class FakeDevice final : public I2CRegisterDevice {
public:
    FakeDevice(std::shared_ptr<FakeBusState> state, uint8_t address)
        : state_(std::move(state)), address_(address) {}

    void writeSingleByte(uint8_t data) override {
        if (address_ != kMuxAddress) {
            throw std::runtime_error("single-byte write is only valid for the fake mux");
        }
        const uint8_t afe = decodeMux(data);
        bool shouldYield = false;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            state_->transferLocked();
            state_->selectedAfe = afe;
            state_->events.push_back(
                Event{Event::Kind::Select, afe, address_, -1, {data}});
            shouldYield = state_->yieldAfterSelect;
        }
        if (shouldYield) {
            std::this_thread::yield();
        }
    }

    void writeByte(uint8_t registerAddress, uint8_t data) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        state_->transferLocked();
        const uint8_t afe = selectedAfeLocked();
        if (address_ != kTcaAddress) {
            throw std::runtime_error("byte write is only valid for the fake TCA9536");
        }
        if (registerAddress == 1 && state_->failTcaOutputWrite)
            throw std::runtime_error("Injected TCA output write failure");
        state_->tca[afe][registerAddress] = data;
        state_->events.push_back(
            Event{Event::Kind::Write, afe, address_, registerAddress, {data}});
        if (registerAddress == 1 && state_->throwAfterTcaOutputWrite)
            throw std::runtime_error("Injected uncertain TCA output write result");
    }

    void writeBytes(uint8_t registerAddress, const std::vector<uint8_t>& data) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        state_->transferLocked();
        const uint8_t afe = selectedAfeLocked();
        if (!isIna() || data.size() != 2) {
            throw std::runtime_error("word write is only valid for a fake INA232");
        }
        const uint16_t value = static_cast<uint16_t>(
            (static_cast<uint16_t>(data[0]) << 8) | data[1]);
        inaRegistersLocked(afe)[registerAddress] = value;
        state_->events.push_back(
            Event{Event::Kind::Write, afe, address_, registerAddress, data});
    }

    void readSingleByte(uint8_t&) override {
        throw std::runtime_error("fake current-pointer reads are unsupported");
    }

    void readByte(uint8_t registerAddress, uint8_t& data) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        state_->transferLocked();
        const uint8_t afe = selectedAfeLocked();
        if (address_ != kTcaAddress) {
            throw std::runtime_error("byte read is only valid for the fake TCA9536");
        }
        data = state_->tca[afe][registerAddress];
        state_->events.push_back(
            Event{Event::Kind::Read, afe, address_, registerAddress, {data}});
    }

    void readBytes(
        uint8_t registerAddress,
        std::vector<uint8_t>& data,
        std::size_t numBytes) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        state_->transferLocked();
        const uint8_t afe = selectedAfeLocked();
        if (!isIna() || numBytes != 2) {
            throw std::runtime_error("word read is only valid for a fake INA232");
        }
        const unsigned call = ++state_->readCalls;
        if (static_cast<int>(call) == state_->failReadCall)
            throw std::runtime_error("Injected I2C read failure");
        uint16_t value = inaRegistersLocked(afe)[registerAddress];
        if (registerAddress == 0x06 && state_->varyDynamicStatusBits) {
            value = static_cast<uint16_t>(
                (value & ~0x003Cu) | ((state_->statusCounter++ & 0x0Fu) << 2));
        }
        if (registerAddress == 0x06 && state_->corruptMaskWritableBit) {
            value ^= 0x0800u;
        }
        if (state_->transformRead) value = state_->transformRead(call, value);
        if (registerAddress == 0x06 && state_->clearAlertOnRead)
            inaRegistersLocked(afe)[registerAddress] &= ~0x0018u;
        std::vector<uint8_t> received = {
            static_cast<uint8_t>((value >> 8) & 0xFF),
            static_cast<uint8_t>(value & 0xFF)
        };
        state_->events.push_back(
            Event{Event::Kind::Read, afe, address_, registerAddress, received});
        if (static_cast<int>(call) == state_->shortReadCall) received.pop_back();
        data.swap(received);
    }

private:
    static uint8_t decodeMux(uint8_t encoded) {
        for (uint8_t afe = 0; afe < 5; ++afe) {
            if (encoded == static_cast<uint8_t>(1u << afe)) {
                return afe;
            }
        }
        throw std::runtime_error("invalid fake mux selection");
    }

    uint8_t selectedAfeLocked() const {
        if (state_->selectedAfe >= 5) {
            throw std::runtime_error("downstream access without mux selection");
        }
        return state_->selectedAfe;
    }

    bool isIna() const {
        return address_ == kIna3V3Address || address_ == kIna5VAddress;
    }

    std::array<uint16_t, 256>& inaRegistersLocked(uint8_t afe) {
        return address_ == kIna5VAddress ? state_->ina5V[afe] : state_->ina3V3[afe];
    }

    std::shared_ptr<FakeBusState> state_;
    uint8_t address_;
};

struct Rig {
    std::shared_ptr<FakeBusState> state;
    std::unique_ptr<I2CMezzDrivers::HDMezzDriver> driver;
};

Rig makeRig() {
    auto state = std::make_shared<FakeBusState>();
    auto factory = [state](const std::string& path, uint8_t address) {
        if (path != "fake-i2c") {
            throw std::runtime_error("unexpected fake adapter path");
        }
        return std::make_unique<FakeDevice>(state, address);
    };
    auto driver = std::make_unique<I2CMezzDrivers::HDMezzDriver>(
        "fake-i2c", std::move(factory), [](std::chrono::milliseconds) {}, [state] {
            std::lock_guard<std::mutex> lock(state->mutex);
            if (!state->clockValues.empty()) return state->clockValues.at(state->clockIndex++);
            if (state->fixedClock) return state->fixedClock;
            return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count());
        });
    return Rig{std::move(state), std::move(driver)};
}

std::vector<Event> events(const std::shared_ptr<FakeBusState>& state) {
    std::lock_guard<std::mutex> lock(state->mutex);
    return state->events;
}

void clearEvents(const std::shared_ptr<FakeBusState>& state) {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->events.clear();
}

int failures = 0;

void check(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void checkNear(double actual, double expected, double tolerance, const std::string& message) {
    if (!std::isfinite(actual) || !std::isfinite(expected) ||
        !(std::abs(actual - expected) <= tolerance)) {
        throw std::runtime_error(
            message + ": expected " + std::to_string(expected) +
            ", got " + std::to_string(actual));
    }
}

template <typename Function>
void expectThrows(Function&& function, const std::string& message) {
    try {
        function();
    } catch (const std::exception&) {
        return;
    }
    throw std::runtime_error(message);
}

template <typename Function>
void run(const char* name, Function&& function) {
    try {
        function();
        std::cout << "[PASS] " << name << '\n';
    } catch (const std::exception& error) {
        ++failures;
        std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
    }
}

void enableAndConfigure(Rig& rig, uint8_t afe) {
    rig.driver->enableAfeBlock(afe, true);
    rig.driver->configureHdMezzAfeBlock(afe);
}

void verifyEachTransferFollowsSelection(const std::vector<Event>& log) {
    for (std::size_t index = 0; index < log.size(); ++index) {
        if (log[index].kind == Event::Kind::Select) {
            check(log[index].bytes.size() == 1, "mux event has no encoded selection");
            check(log[index].bytes[0] == static_cast<uint8_t>(1u << log[index].afe),
                  "mux selected the wrong one-hot channel");
            continue;
        }
        check(index > 0, "downstream transfer occurred without an earlier selection");
        check(log[index - 1].kind == Event::Kind::Select,
              "downstream transfer did not immediately follow mux selection");
        check(log[index - 1].afe == log[index].afe,
              "mux selection and downstream transfer used different AFE blocks");
    }
}

void testMuxAndSafeInitialization() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(2, true);
    check(rig.driver->isAfeBlockEnabled(2), "enabled block was not recorded");
    check(!rig.driver->isAfeBlockConfigured(2), "enable unexpectedly marked block configured");

    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[2][0x01] & 0x03u) == 0,
              "safe initialization did not clear both rail requests");
        check((rig.state->tca[2][0x03] & 0x0Fu) == 0x0Cu,
              "TCA P0/P1 are not outputs with P2/P3 left as inputs");
    }

    const auto log = events(rig.state);
    verifyEachTransferFollowsSelection(log);
    std::size_t outputWrite = log.size();
    std::size_t configWrite = log.size();
    for (std::size_t index = 0; index < log.size(); ++index) {
        if (log[index].kind != Event::Kind::Write || log[index].address != kTcaAddress) {
            continue;
        }
        if (log[index].registerAddress == 0x01 && outputWrite == log.size()) {
            outputWrite = index;
            check((log[index].bytes.at(0) & 0x03u) == 0,
                  "first TCA output write requested a rail");
        }
        if (log[index].registerAddress == 0x03 && configWrite == log.size()) {
            configWrite = index;
            check(log[index].bytes.at(0) == 0xFC,
                  "safe TCA configuration was not 0xFC");
        }
    }
    check(outputWrite < configWrite,
          "TCA directions changed before the rail output latches were cleared");
}

void testAllMuxEncodings() {
    auto rig = makeRig();
    for (uint8_t afe = 0; afe < 5; ++afe) {
        rig.driver->probeAfeBlock(afe);
    }
    verifyEachTransferFollowsSelection(events(rig.state));
}

void testProbeRejectsWrongIdentityAfterSafeOff() {
    auto rig = makeRig();
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[3][0x3E] = 0x1234;
    }
    expectThrows(
        [&] { rig.driver->enableAfeBlock(3, true); },
        "wrong INA232 identity was accepted");
    check(!rig.driver->isAfeBlockEnabled(3),
          "failed probe left the block enabled");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[3][0x01] & 0x03u) == 0,
              "failed identity probe left stale rail requests active");
    }
    for (const auto& event : events(rig.state)) {
        if (event.kind == Event::Kind::Write) {
            check(event.address == kTcaAddress,
                  "failed identity probe programmed an INA232");
        }
    }
}

void testDefaultConfigurationAndByteOrder() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(0, true);
    clearEvents(rig.state);
    rig.driver->configureHdMezzAfeBlock(0);
    check(rig.driver->isAfeBlockConfigured(0),
          "successful configuration was not recorded");

    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check(rig.state->ina5V[0][0x00] == 0x4127, "wrong 5V INA configuration");
        check(rig.state->ina3V3[0][0x00] == 0x4127, "wrong 3V3 INA configuration");
        check(rig.state->ina5V[0][0x05] == 0x5B05, "wrong default 5V SHUNT_CAL");
        check(rig.state->ina3V3[0][0x05] == 0x0AEC, "wrong default 3V3 SHUNT_CAL");
        check(rig.state->ina5V[0][0x07] == 0x06C0, "wrong default 5V SOL limit");
        check(rig.state->ina3V3[0][0x07] == 0x1770, "wrong default CE SOL limit");
        check(rig.state->ina5V[0][0x06] == 0x8001, "wrong 5V mask/enable");
        check(rig.state->ina3V3[0][0x06] == 0x8001, "wrong 3V3 mask/enable");
        check((rig.state->tca[0][0x01] & 0x03u) == 0, "configuration left a rail requested");
    }

    bool sawBigEndianCalibration = false;
    const auto log = events(rig.state);
    verifyEachTransferFollowsSelection(log);
    for (const auto& event : log) {
        if (event.kind == Event::Kind::Write &&
            event.address == kIna5VAddress &&
            event.registerAddress == 0x05 &&
            event.bytes == std::vector<uint8_t>({0x5B, 0x05})) {
            sawBigEndianCalibration = true;
        }
    }
    check(sawBigEndianCalibration, "INA232 word was not written most-significant byte first");
}

void testWritableReadbackMismatchFailsConfiguration() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(0, true);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->corruptMaskWritableBit = true;
    }
    expectThrows(
        [&] { rig.driver->configureHdMezzAfeBlock(0); },
        "writable mask-bit mismatch was accepted");
    check(!rig.driver->isAfeBlockConfigured(0),
          "failed readback left the block configured");
}

void testTransactionalConfigurationRestoresStateAfterProgrammingFailure() {
    auto rig = makeRig();
    enableAndConfigure(rig, 1);
    rig.driver->setPowerRequests(1, true, true);
    const auto oldRshunt = rig.driver->getRShunt(1, "5V");
    const auto oldScale = rig.driver->getMaxCurrentScale(1, "5V");
    const auto oldShutdown = rig.driver->getMaxCurrentShutdown(1, "5V");
    { std::lock_guard<std::mutex> lock(rig.state->mutex); rig.state->corruptMaskWritableBit = true; }
    expectThrows([&] { rig.driver->configureHdMezzAfeBlock(1, {
        0.030, 0.25, 0.180, 0.180, 0.100, 0.009}); },
        "transactional configuration accepted a late verification failure");
    checkNear(rig.driver->getRShunt(1, "5V"), oldRshunt, 1e-12,
              "failed transaction changed stored 5V shunt resistance");
    checkNear(rig.driver->getMaxCurrentScale(1, "5V"), oldScale, 1e-12,
              "failed transaction changed stored 5V current scale");
    checkNear(rig.driver->getMaxCurrentShutdown(1, "5V"), oldShutdown, 1e-12,
              "failed transaction changed stored 5V shutdown limit");
    check(!rig.driver->isAfeBlockConfigured(1),
          "failed transaction left block configured");
    const auto requests = rig.driver->readPowerRequests(1);
    check(!requests.power5V && !requests.power3V3,
          "failed transaction left a rail request asserted");
}

void testConfigurationForcesRailsOffBeforeInaWrites() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(2, true);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->tca[2][0x01] |= 0x03u;
        rig.state->corruptMaskWritableBit = true;
    }
    clearEvents(rig.state);
    expectThrows(
        [&] { rig.driver->configureHdMezzAfeBlock(2); },
        "injected late INA verification fault was not detected");

    const auto log = events(rig.state);
    std::size_t railOffWrite = log.size();
    std::size_t firstInaWrite = log.size();
    for (std::size_t index = 0; index < log.size(); ++index) {
        if (log[index].kind != Event::Kind::Write) {
            continue;
        }
        if (log[index].address == kTcaAddress &&
            log[index].registerAddress == 0x01 &&
            (log[index].bytes.at(0) & 0x03u) == 0 &&
            railOffWrite == log.size()) {
            railOffWrite = index;
        }
        if ((log[index].address == kIna5VAddress ||
             log[index].address == kIna3V3Address) &&
            firstInaWrite == log.size()) {
            firstInaWrite = index;
        }
    }
    check(railOffWrite < firstInaWrite,
          "INA programming began before both rail requests were forced off");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[2][0x01] & 0x03u) == 0,
              "partial configuration failure left a rail requested");
    }
    check(!rig.driver->isAfeBlockConfigured(2),
          "partial configuration failure left configured state true");
}

void testPerBlockPowerStateAndSafeDisable() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    enableAndConfigure(rig, 1);
    rig.driver->setPowerRequests(0, true, false);

    const auto state0 = rig.driver->readPowerRequests(0);
    const auto state1 = rig.driver->readPowerRequests(1);
    check(state0.power5V && !state0.power3V3,
          "block 0 power request was not read from its TCA");
    check(!state1.power5V && !state1.power3V3,
          "block 0 power request leaked into block 1");

    rig.driver->enableAfeBlock(0, false);
    check(!rig.driver->isAfeBlockEnabled(0), "disable did not clear enabled state");
    check(!rig.driver->isAfeBlockConfigured(0), "disable did not clear configured state");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[0][0x01] & 0x03u) == 0,
              "disable did not force both rail requests off");
    }
}

void testDisableEnforcesOffWhenAlreadyDisabled() {
    auto rig = makeRig();
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->tca[4][0x01] = 0xFF;
    }
    rig.driver->enableAfeBlock(4, false);
    check(!rig.driver->isAfeBlockEnabled(4),
          "idempotent disable changed software enabled state");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[4][0x01] & 0x03u) == 0,
              "idempotent disable did not enforce both requests OFF");
        check((rig.state->tca[4][0x03] & 0x0Fu) == 0x0Cu,
              "idempotent disable did not establish safe GPIO directions");
    }
}

void testPowerOnRequiresConfiguration() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(4, true);
    clearEvents(rig.state);
    expectThrows(
        [&] { rig.driver->setPowerRequests(4, true, false); },
        "unconfigured block accepted an ON request");
    check(events(rig.state).empty(),
          "rejected ON request accessed downstream hardware");
}

void testAlertReadImmediatelyRemovesRailRequests() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    rig.driver->setPowerRequests(0, true, true);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->varyDynamicStatusBits = false;
        rig.state->ina5V[0][0x06] |= 0x0010u;
    }
    check(rig.driver->checkAlertStatus(0, "5V"),
          "asserted INA232 AFF was not reported");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[0][0x01] & 0x03u) == 0,
              "AFF read did not immediately remove both rail requests");
    }
}

void testSignedCurrentDecode() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[0][0x04] = 0xFFFF;
    }
    const double expected = -rig.driver->getCurrentLsb(0, "5V") * 1000.0;
    checkNear(rig.driver->readRailCurrent(0, "5V"), expected, 1e-12,
              "negative INA232 current wrapped around");
}

void testInvalidConfigurationIsNonMutatingAndDoesNoIo() {
    auto rig = makeRig();
    const double originalRShunt = rig.driver->getRShunt(0, "5V");
    const double originalScale = rig.driver->getMaxCurrentScale(0, "5V");
    const double originalShutdown = rig.driver->getMaxCurrentShutdown(0, "5V");
    clearEvents(rig.state);

    expectThrows(
        [&] { rig.driver->setRShunt(0, std::numeric_limits<double>::quiet_NaN(), "5V"); },
        "NaN Rshunt was accepted");
    expectThrows(
        [&] { rig.driver->setMaxCurrentScale(0, std::numeric_limits<double>::infinity(), "5V"); },
        "infinite current scale was accepted");
    expectThrows(
        [&] { rig.driver->setMaxCurrentShutdown(0, 0.3, "5V"); },
        "shutdown above scale was accepted");
    expectThrows(
        [&] { rig.driver->setRShunt(0, 0.5, "5V"); },
        "shunt full-scale overflow was accepted");
    expectThrows(
        [&] { rig.driver->setRShunt(0, 1e-9, "5V"); },
        "calibration register overflow was accepted");

    checkNear(rig.driver->getRShunt(0, "5V"), originalRShunt, 0.0,
              "invalid Rshunt mutated driver state");
    checkNear(rig.driver->getMaxCurrentScale(0, "5V"), originalScale, 0.0,
              "invalid current scale mutated driver state");
    checkNear(rig.driver->getMaxCurrentShutdown(0, "5V"), originalShutdown, 0.0,
              "invalid shutdown mutated driver state");
    check(events(rig.state).empty(),
          "numeric validation performed I2C traffic");
}

void testDisabledReadsDoNoIo() {
    auto rig = makeRig();
    clearEvents(rig.state);
    expectThrows(
        [&] { (void)rig.driver->readRailVoltage(1, "5V"); },
        "disabled block telemetry was allowed");
    expectThrows(
        [&] { (void)rig.driver->readPowerRequests(1); },
        "disabled block power state was allowed");
    check(events(rig.state).empty(),
          "disabled block rejection accessed the bus");
}

void testConcurrentMuxTransactionsStayCoherent() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    enableAndConfigure(rig, 1);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[0][0x02] = 0x0100;
        rig.state->ina5V[1][0x02] = 0x0200;
        rig.state->yieldAfterSelect = true;
    }
    clearEvents(rig.state);

    std::atomic<bool> coherent{true};
    const auto reader = [&](uint8_t afe, double expected) {
        try {
            for (int iteration = 0; iteration < 500; ++iteration) {
                if (std::abs(rig.driver->readRailVoltage(afe, "5V") - expected) > 1e-12) {
                    coherent.store(false);
                }
            }
        } catch (const std::exception&) {
            coherent.store(false);
        }
    };
    std::thread first(reader, static_cast<uint8_t>(0), 0x0100 * 1.6e-3);
    std::thread second(reader, static_cast<uint8_t>(1), 0x0200 * 1.6e-3);
    first.join();
    second.join();

    check(coherent.load(), "concurrent reads crossed mux channels");
    verifyEachTransferFollowsSelection(events(rig.state));
}

void verifyCalibrationReadOnly(const std::vector<Event>& log) {
    verifyEachTransferFollowsSelection(log);
    for (const auto& event : log) {
        check(event.kind != Event::Kind::Write, "configuration read wrote a downstream device");
        if (event.kind == Event::Kind::Read) {
            check(event.address == kIna5VAddress || event.address == kIna3V3Address,
                  "configuration read touched TCA or other device");
            check(event.registerAddress == 0x3E || event.registerAddress == 0x05,
                  "configuration read accessed a clearing or unrelated register");
        }
    }
}

void testFreshCalibrationReadbackAndMismatch() {
    using Quality = I2CMezzDrivers::HDMezzDriver::ReadbackQuality;
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    rig.driver->setPowerRequests(0, true, true);
    clearEvents(rig.state);
    const auto original = rig.driver->readBlockConfiguration(0);
    check(original.quality == Quality::Good && original.enabled && original.configured,
          "configured calibration read failed");
    check(original.observedShuntCal == original.requestedShuntCal, "programmed pair not read back");
    check(original.acquisitionStartedNs > 0 && original.observedNs >= original.acquisitionStartedNs,
          "missing acquisition timestamps");
    check(events(rig.state).size() == 16, "expected eight mux-selected read transactions");
    verifyCalibrationReadOnly(events(rig.state));
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[0][0x05] = 0x1234;
        rig.state->ina3V3[0][0x05] = 0; // A reset value is legitimate raw readback, not requested calibration.
    }
    clearEvents(rig.state);
    const auto changed = rig.driver->readBlockConfiguration(0);
    check(changed.quality == Quality::Good && changed.observedShuntCal[0] == 0x1234 &&
          changed.observedShuntCal[1] == 0, "readback substituted cached calibration");
    check(changed.requestedShuntCal == original.requestedShuntCal,
          "readback mutated requested calibration");
    check(changed.configured, "diagnostic read changed the existing monitor enable policy");
    verifyCalibrationReadOnly(events(rig.state));
    check((rig.state->tca[0][0x01] & 3u) == 3u, "diagnostic read changed power requests");
}

void testCalibrationDisabledUnconfiguredAndInvalidBlock() {
    using Quality = I2CMezzDrivers::HDMezzDriver::ReadbackQuality;
    auto rig = makeRig();
    const auto disabled = rig.driver->readBlockConfiguration(0);
    check(disabled.quality == Quality::Unavailable && !disabled.enabled && !disabled.configured &&
          disabled.observedNs == 0, "disabled block pretended readback");
    check(disabled.requestedShuntCal[0] != 0, "requested defaults lost");
    expectThrows([&] { rig.driver->readBlockConfiguration(5); }, "invalid block accepted");
    check(events(rig.state).empty(), "disabled or invalid block touched bus");
    rig.driver->enableAfeBlock(1, true); // Explicit fixture setup, not part of the read path.
    clearEvents(rig.state);
    const auto unconfigured = rig.driver->readBlockConfiguration(1);
    check(unconfigured.quality == Quality::Good && unconfigured.enabled && !unconfigured.configured &&
          unconfigured.observedShuntCal == std::array<uint16_t, 2>{0, 0},
          "unconfigured block did not report actual reset calibration");
    verifyCalibrationReadOnly(events(rig.state));
}

void testCalibrationReadFailureNeverReturnsOldPair() {
    using Quality = I2CMezzDrivers::HDMezzDriver::ReadbackQuality;
    for (int failure = 1; failure <= 8; ++failure) {
        for (bool shortRead : {false, true}) {
            auto rig = makeRig();
            enableAndConfigure(rig, 0);
            check(rig.driver->readBlockConfiguration(0).quality == Quality::Good, "fixture read failed");
            rig.state->readCalls = 0;
            if (shortRead) rig.state->shortReadCall = failure;
            else rig.state->failReadCall = failure;
            clearEvents(rig.state);
            const auto failed = rig.driver->readBlockConfiguration(0);
            check(failed.quality == Quality::Error && failed.observedNs == 0 &&
                  failed.observedShuntCal == std::array<uint16_t, 2>{0, 0},
                  "failed acquisition returned a partial or old successful pair");
            verifyCalibrationReadOnly(events(rig.state));
        }
    }
}

void testCalibrationIdentityStabilityAndReservedBit() {
    using Quality = I2CMezzDrivers::HDMezzDriver::ReadbackQuality;
    for (unsigned changedCall : {1u, 2u, 5u, 6u, 7u, 8u}) {
        auto rig = makeRig();
        enableAndConfigure(rig, 0);
        rig.state->readCalls = 0;
        rig.state->transformRead = [changedCall](unsigned call, uint16_t value) {
            return static_cast<uint16_t>(call == changedCall ? value ^ 1u : value);
        };
        clearEvents(rig.state);
        const auto rejected = rig.driver->readBlockConfiguration(0);
        check(rejected.quality == Quality::Invalid && rejected.observedNs == 0 &&
              rejected.observedShuntCal == std::array<uint16_t, 2>{0, 0},
              "identity change or unstable calibration was admitted");
        verifyCalibrationReadOnly(events(rig.state));
    }
    for (bool secondRail : {false, true}) {
        auto rig = makeRig();
        enableAndConfigure(rig, 0);
        (secondRail ? rig.state->ina3V3 : rig.state->ina5V)[0][0x05] |= 0x8000u;
        check(rig.driver->readBlockConfiguration(0).quality == Quality::Invalid,
              "reserved calibration bit was masked into plausible data");
    }
}

void testCalibrationAcquisitionTiming() {
    using Driver = I2CMezzDrivers::HDMezzDriver;
    for (const auto& times : std::vector<std::vector<uint64_t>>{
            {0}, {100, 99}, {100, 100 + Driver::kMaxConfigurationReadNs + 1}}) {
        auto rig = makeRig();
        enableAndConfigure(rig, 0);
        rig.state->clockValues = times;
        clearEvents(rig.state);
        const auto result = rig.driver->readBlockConfiguration(0);
        check(result.quality == Driver::ReadbackQuality::Invalid && result.observedNs == 0,
              "invalid clock or excessive acquisition duration accepted");
        if (!times[0]) check(events(rig.state).empty(), "missing start time still accessed bus");
        verifyCalibrationReadOnly(events(rig.state));
    }
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    rig.state->clockValues = {100, 100 + Driver::kMaxConfigurationReadNs};
    check(rig.driver->readBlockConfiguration(0).quality == Driver::ReadbackQuality::Good,
          "inclusive acquisition boundary rejected");
}

void testConcurrentCalibrationSnapshotsStayWhole() {
    using Quality = I2CMezzDrivers::HDMezzDriver::ReadbackQuality;
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    rig.driver->setRShunt(1, 0.040, "5V");
    enableAndConfigure(rig, 1);
    rig.state->yieldAfterSelect = true;
    clearEvents(rig.state);
    std::atomic<bool> coherent{true};
    const auto reader = [&](uint8_t afe) {
        for (unsigned n = 0; n < 80; ++n) {
            const auto result = rig.driver->readBlockConfiguration(afe);
            if (result.quality != Quality::Good || result.afeBlock != afe ||
                result.observedShuntCal != result.requestedShuntCal) coherent = false;
        }
    };
    std::thread first(reader, 0), second(reader, 1);
    first.join(); second.join();
    check(coherent, "calibration snapshot crossed blocks or generations");
    const auto log = events(rig.state);
    check(log.size() == 160 * 16, "incomplete concurrent transaction log");
    verifyCalibrationReadOnly(log);
    for (size_t start = 0; start < log.size(); start += 16)
        for (size_t i = start; i < start + 16; ++i)
            check(log[i].afe == log[start].afe, "another block interleaved inside a snapshot");
}

using MezzDriver = I2CMezzDrivers::HDMezzDriver;
using MonitorQuality = MezzDriver::MonitorQuality;

Rig makeMonitorRig(uint8_t afe = 0) {
    auto rig = makeRig();
    rig.state->varyDynamicStatusBits = false;
    rig.state->clearAlertOnRead = true;
    rig.state->fixedClock = 1'000'000'000ULL;
    enableAndConfigure(rig, afe);
    rig.driver->setPowerRequests(afe, true, true);
    rig.state->ina5V[afe][0x02] = 3125; // 5 V
    rig.state->ina3V3[afe][0x02] = 2000; // 3.2 V, legacy CE rail
    rig.state->ina5V[afe][0x04] = 0xFF00; // -256 signed current codes
    rig.state->ina3V3[afe][0x04] = 1000;
    rig.state->ina5V[afe][0x03] = 123;
    rig.state->ina3V3[afe][0x03] = 456;
    clearEvents(rig.state);
    return rig;
}

void checkNoNumericalSample(const MezzDriver::MonitoringSnapshot& sample) {
    check(sample.quality != MonitorQuality::Good && !sample.activeConfigurationVerified &&
          !sample.powerRequestsOffConfirmed, "non-GOOD sample retained a valid power/configuration claim");
    for (const auto& rail : sample.rails)
        check(std::isnan(rail.voltage) && std::isnan(rail.current) && std::isnan(rail.power) &&
              !rail.powerRequested, "partial or previous numerical sample was retained");
}

void checkNoDownstreamWrites(const Rig& rig) {
    for (const auto& event : events(rig.state))
        check(event.kind != Event::Kind::Write, "observation/error invented a control write");
}

void testMonitoringUnavailableAndCacheOnly() {
    auto rig = makeRig();
    for (uint8_t afe = 0; afe < 5; ++afe) {
        const auto initial = rig.driver->monitoringSnapshot(afe);
        check(initial.quality == MonitorQuality::Unavailable && initial.driverStateAvailable &&
              !initial.enabled && !initial.configured && initial.afeBlock == afe &&
              !initial.alerts[0].available && !initial.alerts[1].available &&
              initial.lastGoodNs == 0 && initial.sampleAttempt == 0,
              "initial cache invented driver, alert or measurement observations");
        checkNoNumericalSample(initial);
        checkNoNumericalSample(rig.driver->pollMonitoring(afe));
        rig.driver->clearCachedAlerts(afe);
    }
    for (uint8_t afe : {5, 255}) {
        expectThrows([&] { rig.driver->pollMonitoring(afe); }, "poll accepted invalid block");
        expectThrows([&] { rig.driver->monitoringSnapshot(afe); }, "cache accepted invalid block");
        expectThrows([&] { rig.driver->clearCachedAlerts(afe); }, "clear accepted invalid block");
    }
    check(events(rig.state).empty(), "disabled/invalid/cache-only operations accessed bus");
    rig.driver->enableAfeBlock(0, true);
    clearEvents(rig.state);
    const auto unconfigured = rig.driver->pollMonitoring(0);
    check(unconfigured.enabled && !unconfigured.configured && unconfigured.sampleAttempt == 0,
          "unconfigured block attempted measurement");
    checkNoNumericalSample(unconfigured);
    check(events(rig.state).empty(), "unconfigured monitor accessed bus");
}

void testMonitoringWholeSampleUnitsAndPresence() {
    auto rig = makeMonitorRig(3);
    auto sample = rig.driver->pollMonitoring(3);
    check(sample.quality == MonitorQuality::Good && sample.afeBlock == 3 &&
          sample.enabled && sample.configured && sample.driverStateAvailable &&
          sample.activeConfigurationVerified && sample.sampleAttempt == 1 &&
          sample.lastGoodNs == sample.observedNs && sample.observedNs >= sample.acquisitionStartedNs &&
          sample.acquisitionStartedNs != 0 && sample.stateObservedNs == sample.observedNs,
          "complete snapshot metadata missing");
    checkNear(sample.rails[0].voltage, 5.0, 1e-12, "5V voltage units");
    checkNear(sample.rails[1].voltage, 3.2, 1e-12, "CE voltage units");
    checkNear(sample.rails[0].current, -256 * rig.driver->getCurrentLsb(3, "5V") * 1000, 1e-12,
              "signed current / mA units");
    checkNear(sample.rails[1].current, 1000 * rig.driver->getCurrentLsb(3, "3V3") * 1000, 1e-12,
              "positive current / mA units");
    checkNear(sample.rails[0].power, 123 * 32 * rig.driver->getCurrentLsb(3, "5V") * 1000, 1e-12,
              "5V power / mW units");
    checkNear(sample.rails[1].power, 456 * 32 * rig.driver->getCurrentLsb(3, "3V3") * 1000, 1e-12,
              "CE power / mW units");
    check(sample.rails[0].powerRequested && sample.rails[1].powerRequested &&
          !sample.protectiveActionAttempted && !sample.powerRequestsOffConfirmed,
          "TCA output request readback mismatch");
    for (const auto& alert : sample.alerts)
        check(alert.available && !alert.latched && alert.maskEnableRaw == 0x8001 &&
              alert.observedNs == sample.observedNs, "fresh alert history missing");
    const auto log = events(rig.state);
    check(log.size() == 54, "complete poll must contain 27 mux-selected reads");
    verifyEachTransferFollowsSelection(log);
    checkNoDownstreamWrites(rig);
    clearEvents(rig.state);
    sample.rails[0].voltage = -999; // Returned snapshot cannot mutate the stored generation.
    ++rig.state->fixedClock;
    for (int i = 0; i < 20; ++i) {
        const auto cached = rig.driver->monitoringSnapshot(3);
        check(cached.quality == MonitorQuality::Good && cached.sampleAttempt == 1 &&
              cached.stateObservedNs == rig.state->fixedClock && cached.observedNs == sample.observedNs,
              "cache read refreshed hardware time or lost the snapshot");
        checkNear(cached.rails[0].voltage, 5, 1e-12, "cache alias");
    }
    check(events(rig.state).empty(), "cache read touched clearing status or other hardware");
    rig.driver->setPowerRequests(3, false, false);
    for (auto* registers : {&rig.state->ina5V[3], &rig.state->ina3V3[3]})
        for (int reg : {2, 3, 4}) (*registers)[reg] = 0;
    sample = rig.driver->pollMonitoring(3);
    check(sample.quality == MonitorQuality::Good && sample.powerRequestsOffConfirmed,
          "valid zero/false observations treated as missing");
    for (const auto& rail : sample.rails)
        check(rail.voltage == 0 && rail.current == 0 && rail.power == 0 && !rail.powerRequested,
              "zero/false conversion wrong");
}

void testEveryMonitoringTransferFailureAndRecovery() {
    // Includes both config fences, six measurements, clearing status and final TCA read.
    for (bool shortRead : {false, true}) {
        const int count = shortRead ? 24 : 54;
        for (int fail = 1; fail <= count; ++fail) {
            auto rig = makeMonitorRig();
            const auto good = rig.driver->pollMonitoring(0);
            check(good.quality == MonitorQuality::Good, "fixture incomplete");
            clearEvents(rig.state);
            rig.state->readCalls = rig.state->transferCalls = 0;
            if (shortRead) rig.state->shortReadCall = fail;
            else rig.state->failTransferCall = fail;
            const auto bad = rig.driver->pollMonitoring(0);
            check(bad.quality == MonitorQuality::Error && bad.observedNs == 0 &&
                  bad.sampleAttempt == 2 && bad.lastGoodNs == good.observedNs &&
                  bad.configured && bad.enabled, "failed poll published partial/old GOOD or disabled protection polling");
            checkNoNumericalSample(bad);
            checkNoNumericalSample(rig.driver->monitoringSnapshot(0));
            checkNoDownstreamWrites(rig);
            check((rig.state->tca[0][1] & 3u) == 3u, "bus failure invented a new trip policy");
            rig.state->failTransferCall = rig.state->shortReadCall = -1;
            const auto recovered = rig.driver->pollMonitoring(0);
            check(recovered.quality == MonitorQuality::Good && recovered.sampleAttempt == 3,
                  "complete subsequent poll did not recover");
        }
    }
}

void testMonitoringConfigurationFences() {
    // Every bit of identity/configuration/calibration/limit changes on either rail.
    for (bool secondRail : {false, true}) {
        for (int reg : {0x3E, 0, 5, 7}) {
            for (unsigned bit = 0; bit < 16; ++bit) {
                auto rig = makeMonitorRig();
                auto& registers = secondRail ? rig.state->ina3V3[0] : rig.state->ina5V[0];
                registers[reg] ^= 1u << bit;
                const auto invalid = rig.driver->pollMonitoring(0);
                check(invalid.quality == MonitorQuality::Invalid && invalid.configured,
                      "mismatched readback permitted scaled data or disabled protective poll");
                checkNoNumericalSample(invalid);
                checkNoDownstreamWrites(rig);
            }
        }
    }
    for (unsigned bit = 0; bit < 4; ++bit) {
        auto rig = makeMonitorRig();
        rig.state->tca[0][3] ^= 1u << bit;
        check(rig.driver->pollMonitoring(0).quality == MonitorQuality::Invalid,
              "wrong TCA directions admitted");
        checkNoDownstreamWrites(rig);
    }
    for (unsigned changedCall : {15u, 16u, 17u, 18u, 19u, 20u, 21u, 22u}) {
        auto rig = makeMonitorRig();
        rig.state->readCalls = 0;
        rig.state->transformRead = [changedCall](unsigned call, uint16_t value) {
            return static_cast<uint16_t>(call == changedCall ? value ^ 1u : value);
        };
        check(rig.driver->pollMonitoring(0).quality == MonitorQuality::Invalid,
              "changed late fence admitted");
        checkNoDownstreamWrites(rig);
    }
}

void testMonitoringMaskAndErrorFlags() {
    for (bool secondRail : {false, true}) {
        for (unsigned bit = 0; bit < 16; ++bit) {
            if (bit == 3 || bit == 4) continue; // CVRF and AFF are valid dynamic flags.
            auto rig = makeMonitorRig();
            (secondRail ? rig.state->ina3V3[0] : rig.state->ina5V[0])[6] ^= 1u << bit;
            check(rig.driver->pollMonitoring(0).quality == MonitorQuality::Invalid,
                  "wrong mask/control/reserved or MemError/OVF admitted");
            checkNoDownstreamWrites(rig);
        }
    }
    auto rig = makeMonitorRig();
    rig.state->ina5V[0][6] |= 8; rig.state->ina3V3[0][6] |= 8;
    check(rig.driver->pollMonitoring(0).quality == MonitorQuality::Good,
          "conversion-ready flag treated as measurement invalid");
    checkNoDownstreamWrites(rig);
}

void testMonitoringClockAndStaleness() {
    for (const auto& times : std::vector<std::vector<uint64_t>>{
            {0, 110, 120, 130}, {100, 0, 120, 130}, {100, 110, 0, 130},
            {100, 90, 120, 130}, {100, 120, 110, 130}, {100, 110, 140, 130},
            {100, 110, 120, 99}, {100, 110, 120, 0},
            {100, 110, 120, 100 + MezzDriver::kMaxMonitorAcquisitionNs + 1}, {100}}) {
        auto rig = makeMonitorRig();
        rig.state->clockValues = times;
        const auto invalid = rig.driver->pollMonitoring(0);
        check(invalid.quality == MonitorQuality::Invalid && invalid.observedNs == 0,
              "invalid, missing, thrown or excessive clock accepted");
        checkNoNumericalSample(invalid);
        checkNoDownstreamWrites(rig);
    }
    auto rig = makeMonitorRig();
    rig.state->clockValues = {100, 110, 120, 100 + MezzDriver::kMaxMonitorAcquisitionNs};
    const auto good = rig.driver->pollMonitoring(0);
    check(good.quality == MonitorQuality::Good, "inclusive acquisition boundary rejected");
    rig.state->clockValues.clear();
    rig.state->fixedClock = good.observedNs + MezzDriver::kMaxMonitorAgeNs;
    clearEvents(rig.state);
    check(rig.driver->monitoringSnapshot(0).quality == MonitorQuality::Good,
          "inclusive freshness boundary rejected");
    ++rig.state->fixedClock;
    const auto stale = rig.driver->monitoringSnapshot(0);
    check(stale.quality == MonitorQuality::Stale && stale.observedNs == good.observedNs &&
          stale.lastGoodNs == good.observedNs && stale.alerts[0].observedNs == 110 &&
          stale.alerts[1].observedNs == 120, "staleness erased or refreshed historical timestamps");
    checkNoNumericalSample(stale);
    rig.state->fixedClock = good.observedNs - 1;
    check(rig.driver->monitoringSnapshot(0).quality == MonitorQuality::Invalid,
          "backward snapshot clock admitted");
    rig.state->clockValues = {0}; rig.state->clockIndex = 0;
    check(rig.driver->monitoringSnapshot(0).quality == MonitorQuality::Invalid,
          "missing snapshot clock admitted");
    check(events(rig.state).empty(), "freshness checks touched hardware");
}

void testMonitoringAlertRetentionAndExplicitClear() {
    auto rig = makeMonitorRig();
    rig.state->ina5V[0][6] |= 0x10u;
    const auto tripped = rig.driver->pollMonitoring(0);
    check(tripped.quality == MonitorQuality::Good && tripped.alerts[0].latched &&
          !tripped.alerts[1].latched && tripped.protectiveActionAttempted &&
          tripped.powerRequestsOffConfirmed && !tripped.rails[0].powerRequested &&
          !tripped.rails[1].powerRequested, "fresh AFF did not retain evidence and remove both requests");
    check((rig.state->ina5V[0][6] & 0x10u) == 0, "fixture did not clear hardware AFF on read");
    clearEvents(rig.state);
    ++rig.state->fixedClock;
    const auto retained = rig.driver->pollMonitoring(0);
    check(retained.quality == MonitorQuality::Unavailable && retained.alerts[0].latched &&
          retained.alerts[0].observedNs == tripped.alerts[0].observedNs &&
          retained.alerts[0].maskEnableRaw == tripped.alerts[0].maskEnableRaw &&
          retained.alerts[1].observedNs > tripped.alerts[1].observedNs,
          "retained latch was cleared or advertised as fresh status");
    checkNoNumericalSample(retained);
    for (const auto& event : events(rig.state))
        check(!(event.kind == Event::Kind::Read && event.address == kIna5VAddress && event.registerAddress == 6),
              "latched rail status was re-read contrary to existing policy");
    // Invalid measurement configuration must not be downgraded to merely retained history.
    rig.state->ina5V[0][5] ^= 1;
    check(rig.driver->pollMonitoring(0).quality == MonitorQuality::Invalid,
          "retained alert hid invalid calibration");
    rig.state->ina5V[0][5] ^= 1;
    clearEvents(rig.state);
    rig.driver->clearCachedAlerts(0);
    const auto cleared = rig.driver->monitoringSnapshot(0);
    check(!cleared.alerts[0].available && !cleared.alerts[1].available,
          "explicit software clear retained history");
    checkNoNumericalSample(cleared);
    check(events(rig.state).empty(), "software clear read hardware or re-enabled requests");
    const auto recovered = rig.driver->pollMonitoring(0);
    check(recovered.quality == MonitorQuality::Good && !recovered.alerts[0].latched &&
          recovered.powerRequestsOffConfirmed, "post-clear sample failed or re-energized a rail");
}

void testMonitoringAlertSurvivesProtectiveFailure() {
    for (bool uncertainWrite : {false, true}) {
        auto rig = makeMonitorRig();
        rig.state->ina5V[0][6] |= 0x10u;
        rig.state->ina3V3[0][6] |= 0x10u;
        rig.state->failTcaOutputWrite = !uncertainWrite;
        rig.state->throwAfterTcaOutputWrite = uncertainWrite;
        const auto failed = rig.driver->pollMonitoring(0);
        check(failed.quality == MonitorQuality::Error && failed.alerts[0].latched &&
              failed.alerts[1].latched && failed.protectiveActionAttempted &&
              failed.alerts[0].available && failed.alerts[1].available,
              "failed power removal erased an alert or prevented the other rail's alert read");
        checkNoNumericalSample(failed);
        check((rig.state->ina5V[0][6] & 0x10u) == 0 && (rig.state->ina3V3[0][6] & 0x10u) == 0,
              "test did not consume clearing hardware alerts");
        rig.state->failTcaOutputWrite = rig.state->throwAfterTcaOutputWrite = false;
        const auto retry = rig.driver->pollMonitoring(0);
        check(retry.alerts[0].latched && retry.alerts[1].latched && retry.protectiveActionAttempted &&
              (rig.state->tca[0][1] & 3u) == 0, "retained latch failed to retry request removal");
    }
    auto rig = makeMonitorRig();
    rig.state->ina5V[0][6] |= 0x10u;
    rig.state->failTcaOutputWrite = true;
    expectThrows([&] { rig.driver->checkAlertStatus(0, "5V"); }, "explicit alert read hid failed removal");
    const auto retained = rig.driver->monitoringSnapshot(0);
    check(retained.alerts[0].latched && retained.alerts[0].maskEnableRaw == 0x8011,
          "explicit clearing read lost evidence on write failure");
    expectThrows([&] { rig.driver->enableAfeBlock(0, false); }, "disable ignored failed safe-off");
    check(rig.driver->monitoringSnapshot(0).alerts[0].latched,
          "failed disable cleared alert history");
    rig.state->failTcaOutputWrite = false;
    rig.driver->enableAfeBlock(0, false);
    const auto disabled = rig.driver->monitoringSnapshot(0);
    check(!disabled.enabled && !disabled.configured && !disabled.alerts[0].available,
          "successful disable failed to clear history");
    checkNoNumericalSample(disabled);
}

void testMonitoringFailuresDoNotSuppressProtectivePoll() {
    // Earlier measurement and first-rail status failures must not hide the CE alert.
    for (int failCall : {1, 10, 15, 23}) {
        auto rig = makeMonitorRig();
        rig.state->ina3V3[0][6] |= 0x10;
        rig.state->readCalls = 0; rig.state->failReadCall = failCall;
        const auto failed = rig.driver->pollMonitoring(0);
        check(failed.quality == MonitorQuality::Error && failed.alerts[1].latched &&
              failed.protectiveActionAttempted && (rig.state->tca[0][1] & 3u) == 0,
              "failed acquisition suppressed existing protective alert service");
        checkNoNumericalSample(failed);
    }
    auto rig = makeMonitorRig();
    rig.state->clockValues = {0, 0, 0, 0};
    rig.state->ina5V[0][6] |= 0x10;
    const auto badTime = rig.driver->pollMonitoring(0);
    check(badTime.quality == MonitorQuality::Invalid && badTime.alerts[0].latched &&
          (rig.state->tca[0][1] & 3u) == 0, "missing timestamps suppressed protective power removal");
}

void testMonitoringControlInvalidationAndFailures() {
    const std::vector<std::function<void(MezzDriver&)>> controls = {
        [](auto& d) { d.enableAfeBlock(0, false); },
        [](auto& d) { d.configureHdMezzAfeBlock(0); },
        [](auto& d) { d.configureHdMezzAfeBlock(0, {0.036, 0.3, 0.2, 0.2, 0.1, 0.04}); },
        [](auto& d) { d.setPowerRequests(0, false, false); },
        [](auto& d) { d.powerOn_HDMezzAfeBlock(0, false, "5V"); },
        [](auto& d) { d.powerOn_HDMezzAfeBlock(0, false, "3V3"); },
        [](auto& d) { d.setRShunt(0, 0.040, "5V"); },
        [](auto& d) { d.setRShunt(0, 0.28, "3V3"); },
        [](auto& d) { d.setMaxCurrentScale(0, 0.21, "5V"); },
        [](auto& d) { d.setMaxCurrentScale(0, 0.21, "3V3"); },
        [](auto& d) { d.setMaxCurrentShutdown(0, 0.11, "5V"); },
        [](auto& d) { d.setMaxCurrentShutdown(0, 0.04, "3V3"); },
        [](auto& d) { d.checkAlertStatus(0, "5V"); }
    };
    for (const auto& control : controls) {
        for (bool fail : {false, true}) {
            auto rig = makeMonitorRig();
            const auto good = rig.driver->pollMonitoring(0);
            rig.state->transferCalls = 0;
            if (fail) rig.state->failTransferCall = 1;
            if (fail) expectThrows([&] { control(*rig.driver); }, "control ignored injected bus failure");
            else control(*rig.driver);
            const auto invalidated = rig.driver->monitoringSnapshot(0);
            checkNoNumericalSample(invalidated);
            check(invalidated.lastGoodNs == good.observedNs && invalidated.sampleAttempt == 1 &&
                  invalidated.observedNs == 0, "control erased history or left old sample time current");
        }
    }
    auto rig = makeMonitorRig();
    const auto good = rig.driver->pollMonitoring(0);
    clearEvents(rig.state);
    rig.driver->enableAfeBlock(0, true); // Idempotent no-op preserves the snapshot.
    expectThrows([&] { rig.driver->setRShunt(0, -1, "5V"); }, "invalid shunt accepted");
    expectThrows([&] { rig.driver->setMaxCurrentScale(0, -1, "5V"); }, "invalid scale accepted");
    expectThrows([&] { rig.driver->setMaxCurrentShutdown(0, -1, "3V3"); }, "invalid threshold accepted");
    expectThrows([&] { rig.driver->setPowerRequests(9, false, false); }, "invalid block accepted");
    expectThrows([&] { rig.driver->powerOn_HDMezzAfeBlock(0, true, "unknown"); }, "invalid rail accepted");
    expectThrows([&] { rig.driver->configureHdMezzAfeBlock(0, {-1, 0.3, 0.2, 0.2, 0.1, 0.04}); },
                 "invalid aggregate accepted");
    check(rig.driver->monitoringSnapshot(0).quality == MonitorQuality::Good &&
          rig.driver->monitoringSnapshot(0).sampleAttempt == good.sampleAttempt && events(rig.state).empty(),
          "rejected input or no-op invalidated sample or accessed bus");
}

void testMonitoringCalibrationReadbackInvalidation() {
    for (int failure = 0; failure <= 3; ++failure) {
        auto rig = makeMonitorRig();
        rig.driver->pollMonitoring(0);
        rig.state->readCalls = 0;
        if (failure == 1) rig.state->ina5V[0][5] ^= 1;
        if (failure == 2) rig.state->failReadCall = 1;
        if (failure == 3) rig.state->ina3V3[0][0x3E] ^= 1;
        clearEvents(rig.state);
        const auto actual = rig.driver->readBlockConfiguration(0);
        const auto cached = rig.driver->monitoringSnapshot(0);
        if (!failure) check(cached.quality == MonitorQuality::Good, "matching calibration invalidated cache");
        else checkNoNumericalSample(cached);
        if (failure == 1)
            check(actual.quality == MezzDriver::ReadbackQuality::Good &&
                  actual.observedShuntCal != actual.requestedShuntCal && cached.quality == MonitorQuality::Invalid,
                  "GOOD raw mismatch masqueraded as valid scaled monitoring data");
        check(cached.configured && (rig.state->tca[0][1] & 3u) == 3u,
              "calibration observation changed protective monitoring selection or power");
        verifyCalibrationReadOnly(events(rig.state));
    }
}

void testMonitoringConcurrentWholeCyclesAndControls() {
    auto rig = makeMonitorRig();
    enableAndConfigure(rig, 1);
    rig.state->ina5V[1][2] = 1000;
    rig.state->ina3V3[1][2] = 500;
    rig.state->yieldAfterSelect = true;
    clearEvents(rig.state);
    std::atomic<bool> coherent{true};
    const auto poll = [&](uint8_t afe, double first, double second) {
        try {
            for (int n = 0; n < 80; ++n) {
                const auto sample = rig.driver->pollMonitoring(afe);
                if (sample.quality != MonitorQuality::Good || sample.afeBlock != afe ||
                    sample.rails[0].voltage != first || sample.rails[1].voltage != second ||
                    sample.sampleAttempt != static_cast<uint64_t>(n + 1)) coherent = false;
            }
        } catch (...) { coherent = false; }
    };
    std::thread first(poll, 0, 5.0, 3.2), second(poll, 1, 1.6, 0.8);
    std::thread reader([&] {
        for (int n = 0; n < 160; ++n) {
            for (uint8_t afe : {0, 1}) {
                const auto sample = rig.driver->monitoringSnapshot(afe);
                if (sample.quality == MonitorQuality::Good &&
                    (sample.rails[0].voltage != (afe ? 1.6 : 5.0) ||
                     sample.rails[1].voltage != (afe ? 0.8 : 3.2))) coherent = false;
            }
        }
    });
    first.join(); second.join(); reader.join();
    check(coherent, "concurrent cache/poll mixed blocks or partial sample generations");
    const auto log = events(rig.state);
    check(log.size() == 160 * 54, "unexpected concurrent bus traffic");
    verifyEachTransferFollowsSelection(log);
    for (size_t start = 0; start < log.size(); start += 54)
        for (size_t i = start; i < start + 54; ++i)
            check(log[i].afe == log[start].afe, "another poll interleaved within one cycle");

    // Hold one acquisition mid-cycle; a waiting control must invalidate AFTER publication.
    std::mutex barrierMutex;
    std::condition_variable cv;
    bool paused = false, release = false;
    rig.state->readCalls = 0;
    rig.state->transformRead = [&](unsigned call, uint16_t value) {
        if (call == 1) {
            std::unique_lock<std::mutex> lock(barrierMutex);
            paused = true; cv.notify_all();
            cv.wait(lock, [&] { return release; });
        }
        return value;
    };
    std::thread acquisition([&] { rig.driver->pollMonitoring(0); });
    {
        std::unique_lock<std::mutex> lock(barrierMutex);
        cv.wait(lock, [&] { return paused; });
    }
    std::atomic<bool> controlStarted{false}, controlCompleted{false};
    std::thread control([&] {
        controlStarted = true;
        rig.driver->setPowerRequests(0, false, false);
        controlCompleted = true;
    });
    while (!controlStarted) std::this_thread::yield();
    const bool completedEarly = controlCompleted;
    {
        std::lock_guard<std::mutex> lock(barrierMutex);
        release = true; cv.notify_all();
    }
    acquisition.join(); control.join();
    check(!completedEarly && controlCompleted, "control escaped the whole-cycle driver lock");
    checkNoNumericalSample(rig.driver->monitoringSnapshot(0));
    check(rig.driver->monitoringSnapshot(1).quality == MonitorQuality::Good,
          "control for one block invalidated another block's sample");
    rig.state->transformRead = {};
    check(rig.driver->pollMonitoring(0).powerRequestsOffConfirmed,
          "post-control cycle did not observe requests off");
}

}  // namespace

int main() {
    run("mux selection and safe initialization", testMuxAndSafeInitialization);
    run("all mux encodings", testAllMuxEncodings);
    run("probe identity failure after safe-off", testProbeRejectsWrongIdentityAfterSafeOff);
    run("default configuration and byte order", testDefaultConfigurationAndByteOrder);
    run("masked readback verification", testWritableReadbackMismatchFailsConfiguration);
    run("transactional configuration rollback", testTransactionalConfigurationRestoresStateAfterProgrammingFailure);
    run("rail-off ordering during configuration", testConfigurationForcesRailsOffBeforeInaWrites);
    run("per-block power state and safe disable", testPerBlockPowerStateAndSafeDisable);
    run("idempotent disable enforces off", testDisableEnforcesOffWhenAlreadyDisabled);
    run("power-on requires configuration", testPowerOnRequiresConfiguration);
    run("alert read removes rail requests", testAlertReadImmediatelyRemovesRailRequests);
    run("signed current decode", testSignedCurrentDecode);
    run("invalid configuration validation", testInvalidConfigurationIsNonMutatingAndDoesNoIo);
    run("disabled block rejection", testDisabledReadsDoNoIo);
    run("concurrent mux transaction coherence", testConcurrentMuxTransactionsStayCoherent);
    run("fresh calibration pair and requested/readback mismatch", testFreshCalibrationReadbackAndMismatch);
    run("disabled and unconfigured calibration provenance", testCalibrationDisabledUnconfiguredAndInvalidBlock);
    run("all calibration read failures and short transfers", testCalibrationReadFailureNeverReturnsOldPair);
    run("calibration identity/stability/reserved-bit rejection", testCalibrationIdentityStabilityAndReservedBit);
    run("calibration acquisition timing boundaries", testCalibrationAcquisitionTiming);
    run("concurrent calibration snapshots are whole", testConcurrentCalibrationSnapshotsStayWhole);
    run("monitor unavailable states and cache-only access", testMonitoringUnavailableAndCacheOnly);
    run("monitor whole sample, units and valid zero/false", testMonitoringWholeSampleUnitsAndPresence);
    run("all monitor transfer failures, short reads and recovery", testEveryMonitoringTransferFailureAndRecovery);
    run("monitor configuration/calibration/limit/identity fences", testMonitoringConfigurationFences);
    run("monitor mask configuration and memory/overflow flags", testMonitoringMaskAndErrorFlags);
    run("monitor clock validity and stale-cache boundaries", testMonitoringClockAndStaleness);
    run("monitor retained alert timestamps and explicit clear", testMonitoringAlertRetentionAndExplicitClear);
    run("monitor alerts survive failed and uncertain protective writes", testMonitoringAlertSurvivesProtectiveFailure);
    run("monitor failures do not suppress protective alert polling", testMonitoringFailuresDoNotSuppressProtectivePoll);
    run("monitor invalidation before controls, including failures", testMonitoringControlInvalidationAndFailures);
    run("monitor invalidation on inconsistent calibration readback", testMonitoringCalibrationReadbackInvalidation);
    run("monitor concurrent whole cycles, cache readers and controls", testMonitoringConcurrentWholeCyclesAndControls);

    if (failures != 0) {
        std::cerr << failures << " HD mezzanine test(s) failed\n";
        return 1;
    }
    std::cout << "All HD mezzanine hardware-layer tests passed\n";
    return 0;
}
