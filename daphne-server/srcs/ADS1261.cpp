#include "ADS1261.hpp"
#include <stdexcept>
#include <utility>

namespace daphne_sc {
uint8_t ads1261_crc(const std::vector<uint8_t>& bytes) {
  uint8_t crc = 0xff;
  for (const auto value : bytes) {
    crc ^= value;
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = static_cast<uint8_t>((crc << 1) ^ ((crc & 0x80) ? 0x07 : 0));
  }
  return crc;
}
uint8_t ads1261_afe_mux(uint32_t afe) {
  if (afe >= 5) throw std::invalid_argument("ADS1261 AFE index outside 0..4");
  return static_cast<uint8_t>(((2 * afe + 2) << 4) | (2 * afe + 1));
}
int32_t ads1261_signed_code(uint32_t raw) {
  if (raw > 0xffffff) throw std::invalid_argument("ADC code exceeds 24 bits");
  return static_cast<int32_t>(raw) - ((raw & 0x800000) ? 0x1000000 : 0);
}
ADS1261::ADS1261(Transfer transfer, Clock now, Wait wait)
    : transfer_(std::move(transfer)), now_(std::move(now)), wait_(std::move(wait)) {
  if (!transfer_ || !now_ || !wait_) throw std::invalid_argument("Missing ADC transport/clock");
}
std::vector<uint8_t> ADS1261::exchange(const std::vector<uint8_t>& tx) {
  const auto rx = transfer_(tx);
  if (rx.size() != tx.size() || rx.size() < 2 || rx[1] != tx[0])
    throw std::runtime_error("ADS1261 short response or command echo mismatch");
  return rx;
}
uint8_t ADS1261::probe() {
  initialized_ = false;
  crc_ = false;
  // Valid RREG framing in either mode: the CRC clocks fall in the data phase
  // when CRC is disabled. Avoid an intentionally bad-CRC probe setting CRCERR.
  const auto command_crc = ads1261_crc({0x20, 0});
  const auto response = exchange({0x20, 0, command_crc, 0, 0, 0});
  if ((response[2] >> 4) == 8) { id_ = response[2]; return id_; }
  // In CRC mode byte 3 is the echoed zero, not the ID.
  if (response[2] != 0 || response[3] != command_crc ||
      response[5] != ads1261_crc({response[4]}))
    throw std::runtime_error("ADS1261 identity framing/CRC missing or incompatible");
  crc_ = true;
  id_ = response[4];
  if ((id_ >> 4) != 8) throw std::runtime_error("ADS1261 identity missing or incompatible");
  return id_;
}
void ADS1261::command(uint8_t op) {
  if (!crc_) { exchange({op, 0}); return; }
  const uint8_t crc = ads1261_crc({op, 0});
  const auto rx = exchange({op, 0, crc, 0});
  if (rx[2] != 0 || rx[3] != crc) throw std::runtime_error("ADS1261 command CRC/echo mismatch");
}
uint8_t ADS1261::read_register(uint8_t address) {
  const uint8_t op = 0x20 | address;
  if (!crc_) return exchange({op, 0, 0})[2];
  const uint8_t crc = ads1261_crc({op, 0});
  const auto rx = exchange({op, 0, crc, 0, 0, 0});
  if (rx[2] != 0 || rx[3] != crc || rx[5] != ads1261_crc({rx[4]}))
    throw std::runtime_error("ADS1261 register response CRC/echo mismatch");
  return rx[4];
}
void ADS1261::write_register(uint8_t address, uint8_t value, bool verify) {
  const uint8_t op = 0x40 | address;
  if (!crc_) exchange({op, value});
  else {
    const uint8_t crc = ads1261_crc({op, value});
    const auto rx = exchange({op, value, crc, 0});
    if (rx[2] != value || rx[3] != crc) throw std::runtime_error("ADS1261 write CRC/echo mismatch");
  }
  if (verify && read_register(address) != value)
    throw std::runtime_error("ADS1261 configuration readback mismatch");
}
void ADS1261::initialize() {
  probe();
  command(0x06); // ADC reset only, after identification; no carrier/FPGA reset.
  wait_(5000000);
  crc_ = false;
  if (read_register(0) != id_) throw std::runtime_error("ADS1261 identity changed after reset");
  write_register(5, 0x60, false); // Enable STATUS + CRC; transition to CRC after this write.
  crc_ = true;
  if (read_register(5) != 0x60) throw std::runtime_error("ADS1261 CRC enable did not take effect");
  write_register(2, 0x40); // 400 SPS, sinc1, settled single-shot conversion.
  write_register(3, 0x11); // Pulse mode, 50 us conversion-start delay.
  write_register(6, 0x10); // Enable and select internal 2.5 V reference, not default AVDD.
  write_register(0x10, 0x80); // Gain 1, PGA bypass for near-ground trim inputs.
  write_register(1, 0, false); // Clear RESET/CRCERR latches; final sample status must be clean.
  wait_(5000000); // Reference/PGA settling margin before selecting an input.
  check_profile();
  initialized_ = true;
}
void ADS1261::check_profile() {
  for (const auto pair : {std::pair<uint8_t, uint8_t>{0, id_}, {2, 0x40}, {3, 0x11},
                         {4, 0}, {5, 0x60}, {6, 0x10}, {7, 0}, {8, 0}, {9, 0},
                         {10, 0}, {11, 0}, {12, 0x40}, {13, 0xff}, {14, 0},
                         {16, 0x80}, {18, 0}})
    if (read_register(pair.first) != pair.second)
      throw std::runtime_error("ADS1261 profile/calibration/readback changed");
}
ADS1261Sample ADS1261::convert(uint32_t afe) {
  const auto mux = ads1261_afe_mux(afe);
  if (!initialized_) throw std::runtime_error("ADS1261 measurement setup has not completed");
  write_register(0x11, mux);
  command(0x08);
  const auto started = now_();
  bool ready = false;
  for (unsigned attempt = 0; attempt < 200; ++attempt) {
    const auto status = read_register(1);
    if (status & 0x41) throw std::runtime_error("ADS1261 reset or command CRC fault during conversion");
    if (status & 4) { ready = true; break; }
    const auto now = now_();
    if (now < started || now - started >= 100000000) break;
    wait_(500000);
  }
  if (!ready) throw std::runtime_error("ADS1261 data-ready timeout; no retained sample reported");
  const uint8_t command_crc = ads1261_crc({0x12, 0});
  const auto rx = exchange({0x12, 0, command_crc, 0, 0, 0, 0, 0, 0});
  if (rx[2] != 0 || rx[3] != command_crc || rx[8] != ads1261_crc({rx[4], rx[5], rx[6], rx[7]}))
    throw std::runtime_error("ADS1261 conversion CRC/echo mismatch");
  ADS1261Sample result;
  result.id = id_;
  result.status = rx[4];
  result.input_mux = mux;
  result.observed_monotonic_ns = now_();
  result.raw_code = ads1261_signed_code((uint32_t(rx[5]) << 16) | (uint32_t(rx[6]) << 8) | rx[7]);
  result.saturated = result.raw_code == -8388608 || result.raw_code == 8388607;
  result.differential_volts = result.raw_code * reference_volts / (gain * 8388608.0);
  check_profile();
  if (read_register(0x11) != mux) throw std::runtime_error("ADS1261 input changed during conversion");
  // Single-shot mode stops itself. Keep faulted/saturated raw data as diagnostic
  // evidence; the caller must not mark its voltage/current measurement Good.
  return result;
}
}  // namespace daphne_sc
