#pragma once
#include <cstdint>
#include <functional>
#include <vector>

namespace daphne_sc {
uint8_t ads1261_crc(const std::vector<uint8_t>& bytes);
uint8_t ads1261_afe_mux(uint32_t afe); // DA - DB; AIN0 has mux code 1, not 0.
int32_t ads1261_signed_code(uint32_t raw24);

struct ADS1261Sample {
  uint8_t id = 0, status = 0, input_mux = 0;
  int32_t raw_code = 0;
  double differential_volts = 0;
  bool saturated = false;
  uint64_t observed_monotonic_ns = 0;
};

class ADS1261 {
 public:
  using Transfer = std::function<std::vector<uint8_t>(const std::vector<uint8_t>&)>;
  using Clock = std::function<uint64_t()>;
  using Wait = std::function<void(uint64_t)>; // nanoseconds
  ADS1261(Transfer transfer, Clock now, Wait wait);
  uint8_t probe(); // ID read only; detects existing CRC framing without reset.
  bool crc_enabled() const { return crc_; }
  void initialize(); // Explicit measurement setup, never constructor side effects.
  ADS1261Sample convert(uint32_t afe);
  static constexpr double reference_volts = 2.5;
  static constexpr uint32_t gain = 1;
  static constexpr bool pga_bypassed = true; // Supports zero/near-rail trim common mode.
 private:
  std::vector<uint8_t> exchange(const std::vector<uint8_t>& tx);
  void command(uint8_t opcode);
  uint8_t read_register(uint8_t address);
  void write_register(uint8_t address, uint8_t value, bool verify = true);
  void check_profile();
  Transfer transfer_;
  Clock now_;
  Wait wait_;
  bool crc_ = false, initialized_ = false;
  uint8_t id_ = 0;
};
}  // namespace daphne_sc
