#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "server_controller/synthetic_sipm.hpp"

namespace {
using namespace daphne_sc;

void require(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << '\n';
    std::exit(1);
  }
}

void require_throws(const std::function<void()>& action, const std::string& text) {
  try {
    action();
  } catch (const std::exception& error) {
    require(std::string(error.what()).find(text) != std::string::npos, error.what());
    return;
  }
  require(false, "expected exception: " + text);
}

// The acquisition model latches parameters only while disabled and observes
// AXI writes only when the settling callback advances its clock domain.
class FakeMmio final : public Mmio32 {
 public:
  uint32_t read32(uint64_t address) override {
    require(address == kSyntheticConfigAddress, "isolated register address");
    ++reads;
    if (fail_read_after_write == writes.size() && fail_read_after_write != 0) {
      fail_read_after_write = 0;
      throw std::runtime_error("read failed");
    }
    return supported ? value : 0U;
  }

  void write32(uint64_t address, uint32_t data) override {
    require(address == kSyntheticConfigAddress, "isolated register address");
    writes.push_back(data);
    events.push_back("write");
    if (writes.size() == fail_write_number) throw std::runtime_error("write failed");
    if (supported && writes.size() != ignored_write_number) value = data & kSyntheticConfigMask;
  }

  void settle() {
    events.push_back("settle");
    if ((value & kSyntheticEnableBit) == 0U) {
      latched = value;
      history_cleared = true;
    } else {
      require(latched == (value & ~kSyntheticEnableBit), "new parameters latched before enable");
    }
  }

  uint32_t value = 0x00C01680U;  // HPK A=22.5, enabled
  uint32_t latched = 0x00401680U;
  size_t reads = 0;
  size_t fail_write_number = 0;
  size_t ignored_write_number = 0;
  size_t fail_read_after_write = 0;
  bool supported = true;
  bool history_cleared = false;
  std::vector<uint32_t> writes;
  std::vector<std::string> events;
};

void test_validation() {
  require(encode_synthetic_config(5760, 0, true) == 0x00801680U, "FBK example");
  require(encode_synthetic_config(5760, 1, true) == 0x00C01680U, "HPK example");
  require(encode_synthetic_config(256, 0, false) == 0x100U, "minimum amplitude");
  require(encode_synthetic_config(2560000, 1, true) == 0x00E71000U, "maximum amplitude");
  require(encode_synthetic_config(257, 0, false) == 257U, "fractional ADC amplitude");
  for (uint32_t amplitude : {0U, 255U, 2560001U, 0xFFFFFFFFU}) {
    FakeMmio mmio;
    require_throws([&] { configure_synthetic_sipm(mmio, amplitude, 0, true); }, "amplitude_q8");
    require(mmio.reads == 0 && mmio.writes.empty(), "invalid amplitude never touches MMIO");
  }
  for (uint32_t model : {2U, 0xFFFFFFFFU}) {
    FakeMmio mmio;
    require_throws([&] { configure_synthetic_sipm(mmio, 256, model, true); }, "model");
    require(mmio.reads == 0 && mmio.writes.empty(), "invalid model never touches MMIO");
  }
}

void test_sequence() {
  for (bool enable : {false, true}) {
    FakeMmio mmio;
    const uint32_t result = configure_synthetic_sipm(mmio, 2048, 0, enable, [&] { mmio.settle(); });
    std::vector<uint32_t> expected = {0x00401680U, 2048U};
    if (enable) expected.push_back(0x00800800U);
    require(mmio.writes == expected, "disable preserves old parameters before writing new ones");
    require(mmio.value == result && mmio.latched == 2048U, "readback and latched parameters agree");
    require(mmio.history_cleared, "configuration clears history");
    require(mmio.events.size() == 2 * expected.size(), "wait after each write");
    for (size_t i = 0; i < mmio.events.size(); i += 2) {
      require(mmio.events[i] == "write" && mmio.events[i + 1] == "settle", "ordered settling");
    }
  }
  FakeMmio repeated;
  configure_synthetic_sipm(repeated, 5760, 1, true, [&] { repeated.settle(); });
  require(repeated.writes.size() == 3 && repeated.history_cleared, "repeated configuration rearms");

  FakeMmio zero;
  zero.value = 0;  // Present hardware with externally written invalid parameters
  configure_synthetic_sipm(zero, 256, 0, true, [&] { zero.settle(); });
  require(zero.value == 0x00800100U, "configuration can repair a present zero register");
}

void test_failures() {
  for (size_t stage : {1U, 2U, 3U}) {
    FakeMmio mmio;
    mmio.ignored_write_number = stage;
    require_throws([&] { configure_synthetic_sipm(mmio, 2048, 0, true, [&] { mmio.settle(); }); },
                   "readback mismatch");
    require((mmio.value & kSyntheticEnableBit) == 0U, "mismatch leaves generator disabled");
    require(mmio.writes.size() == stage + 1, "failure stops sequence and attempts disable");

    FakeMmio write_failure;
    write_failure.fail_write_number = stage;
    require_throws([&] {
      configure_synthetic_sipm(write_failure, 2048, 0, true, [&] { write_failure.settle(); });
    }, "write failed");
    require((write_failure.value & kSyntheticEnableBit) == 0U, "write error attempts disable");

    FakeMmio read_failure;
    read_failure.fail_read_after_write = stage;
    require_throws([&] {
      configure_synthetic_sipm(read_failure, 2048, 0, true, [&] { read_failure.settle(); });
    }, "read failed");
    require((read_failure.value & kSyntheticEnableBit) == 0U, "read error attempts disable");
  }

  FakeMmio absent;
  absent.supported = false;
  absent.value = 0;
  require_throws([&] { read_synthetic_config(absent); }, "unavailable");
  require(absent.writes.empty(), "read request never writes");
  require_throws([&] {
    configure_synthetic_sipm(absent, 256, 0, true, [&] { absent.settle(); });
  }, "readback mismatch");
  for (auto value : absent.writes) {
    require((value & kSyntheticEnableBit) == 0U, "absent generator never receives enable");
  }

  FakeMmio disable_failure;
  disable_failure.ignored_write_number = 1;
  disable_failure.fail_write_number = 2;
  require_throws([&] {
    configure_synthetic_sipm(disable_failure, 2048, 0, true, [&] { disable_failure.settle(); });
  }, "could not verify disabled state: write failed");
}

}  // namespace

int main() {
  test_validation();
  test_sequence();
  test_failures();
  FakeMmio mmio;
  require(read_synthetic_config(mmio) == 0x00C01680U && mmio.writes.empty(), "readback is read-only");
  std::cout << "synthetic SiPM configuration tests passed\n";
}
