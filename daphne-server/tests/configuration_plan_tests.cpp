#include <algorithm>
#include <array>
#include <iostream>
#include <map>
#include <stdexcept>
#include "Ad5327.hpp"
#include "defines.hpp"
#include "server_controller/configuration_plan.hpp"

namespace {
void require(bool ok) {
  if (!ok) throw std::runtime_error("configuration plan assertion failed");
}
template <typename Function>
void rejects(Function function) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  require(rejected);
}
}

int main() {
  using namespace daphne_sc;
  // Five distinct codes, mixed zeros and all zeros, in every input order.
  // These are mock writes, never nonzero-bias hardware tests.
  const std::array<uint32_t, 5> board_to_pl = {0, 4, 3, 2, 1};
  const std::array<std::array<uint32_t, 5>, 3> bias_cases = {{
      {17, 513, 1025, 2049, 4095}, {0, 11, 0, 22, 0}, {0, 0, 0, 0, 0}}};
  unsigned bias_commands = 0;
  for (const auto& codes : bias_cases) {
    std::array<uint32_t, 5> order = {0, 1, 2, 3, 4};
    do {
      daphne::ConfigureRequest bias_request;
      for (const auto id : order) {
        auto* entry = bias_request.add_afes();
        entry->set_id(id);
        entry->set_v_bias(codes[id]);
      }
      daphne::ConfigureRequest decoded;
      require(decoded.ParseFromString(bias_request.SerializeAsString()));
      validate_analog_configuration(decoded);
      std::map<uint32_t, uint32_t> observed;
      for (const auto& entry : decoded.afes()) {
        apply_afe_bias_command(entry, [&](uint32_t pl, uint32_t code) {
          require(pl == board_to_pl[entry.id()] && code == codes[entry.id()]);
          require(observed.emplace(pl, code).second);
          ++bias_commands;
        });
      }
      require(observed.size() == 5);
    } while (std::next_permutation(order.begin(), order.end()));
  }
  require(bias_commands == 1800);
  // The proto3 default in a present entry is also a real zero command.
  daphne::AFEConfig default_bias;
  default_bias.set_id(4);
  apply_afe_bias_command(default_bias, [&](uint32_t pl, uint32_t code) {
    require(pl == 1 && code == 0);
    ++bias_commands;
  });
  auto run_bias_request = [&](const daphne::ConfigureRequest& config) {
    validate_analog_configuration(config); // Complete preflight precedes writes.
    for (const auto& entry : config.afes())
      apply_afe_bias_command(entry, [&](uint32_t, uint32_t) { ++bias_commands; });
  };
  run_bias_request(daphne::ConfigureRequest{}); // No AFE entry: no BIAS command.
  require(bias_commands == 1801);
  for (unsigned problem = 0; problem < 3; ++problem) {
    daphne::ConfigureRequest bad;
    bad.add_afes()->set_id(0); // Valid entry must not be written before rejection.
    auto* entry = bad.add_afes();
    entry->set_id(problem == 0 ? 5 : (problem == 1 ? 0 : 1));
    entry->set_v_bias(problem == 2 ? 4096 : 0);
    rejects([&] { run_bias_request(bad); });
    require(bias_commands == 1801);
  }
  for (bool bad_id : {false, true}) {
    daphne::AFEConfig bad;
    bad.set_id(bad_id ? 5 : 0);
    bad.set_v_bias(bad_id ? 0 : 4096);
    rejects([&] { apply_afe_bias_command(bad, [&](uint32_t, uint32_t) { ++bias_commands; }); });
    require(bias_commands == 1801);
  }
  daphne::ConfigureRequest request;
  request.set_biasctrl(4095);
  auto* channel = request.add_channels();
  channel->set_id(39);
  channel->set_trim(4095);
  channel->set_offset(4095);
  auto* afe = request.add_afes();
  afe->set_id(4);
  afe->set_attenuators(4095);
  afe->set_v_bias(4095);
  afe->mutable_pga()->set_lpf_cut_frequency(4);
  afe->mutable_lna()->set_gain(3);
  afe->mutable_lna()->set_clamp(3);
  validate_analog_configuration(request);
  for (uint32_t gain : {0u, 1u, 2u}) {
    auto offset_request = request;
    auto* offset = offset_request.mutable_channels(0);
    offset->set_gain(gain);
    const uint32_t limit = gain == 0 ? 4095 : (gain == 1 ? 2700 : 1500);
    for (uint32_t code : {0u, limit}) {
      offset->set_offset(code);
      for (uint32_t id = 0; id < 40; ++id) {
        offset->set_id(id);
        daphne::ConfigureRequest decoded;
        require(decoded.ParseFromString(offset_request.SerializeAsString()));
        validate_analog_configuration(decoded);
        const auto& c = decoded.channels(0);
        const bool bit = offset_gain_bit(c.gain());
        require(bit == (gain == 2));
        const auto word = ad5327::encode_word(c.id() % 4, c.offset(), bit, false);
        require(((word >> 14) & 3) == id % 4);
        require(((word >> 13) & 1) == (gain == 2));
        require((word & 0x1000) == 0 && (word & 0xFFF) == code);
      }
    }
    offset->set_offset(limit + 1);
    rejects([&] { validate_analog_configuration(offset_request); });
  }
  // Mixed per-channel gains are supported; AD5327 GAIN addresses one output.
  auto mixed = request;
  mixed.clear_channels();
  for (uint32_t id = 0; id < 40; ++id) {
    auto* c = mixed.add_channels();
    c->set_id(id);
    c->set_gain(1 + id % 2);
    c->set_offset(1000);
  }
  validate_analog_configuration(mixed);
  // Exhaust the actual encoder used by Dac::updateCurrentRegister. Changing
  // offset gain must change ONLY bit 13, never address, buffer or DAC code.
  for (uint32_t address = 0; address < 4; ++address)
    for (uint32_t code = 0; code <= 4095; ++code)
      for (bool buffer : {false, true}) {
        const auto x1 = ad5327::encode_word(address, code, offset_gain_bit(1), buffer);
        const auto x2 = ad5327::encode_word(address, code, offset_gain_bit(2), buffer);
        require(x1 == (address << 14 | uint32_t(buffer) << 12 | code));
        require((x1 ^ x2) == 0x2000);
      }
  const auto gain_field = afe_definitions::afeFunctionDict.at("PGA_GAIN_CONTROL");
  require(gain_field.size() == 1 && gain_field.begin()->first == 51);
  require(gain_field.begin()->second == std::make_pair(13, 13));
  for (bool gain : {false, true}) {
    afe->mutable_pga()->set_gain(gain);
    daphne::ConfigureRequest decoded;
    require(decoded.ParseFromString(request.SerializeAsString()));
    unsigned gain_writes = 0;
    for (const auto& write : make_afe_function_plan(decoded.afes(0))) {
      apply_verified_afe_function(write, [&](const std::string& name, uint32_t value) {
        if (name == "PGA_GAIN_CONTROL") {
          ++gain_writes;
          require(value == static_cast<uint32_t>(gain));
        }
        return value;
      });
    }
    require(gain_writes == 1);
  }
  rejects([] { apply_verified_afe_function({"PGA_GAIN_CONTROL", 1},
                                          [](const std::string&, uint32_t) { return 0; }); });
  unsigned writes = 0;
  rejects([&] { apply_verified_afe_function({"PGA_GAIN_CONTROL", 65536},
                                           [&](const std::string&, uint32_t) { ++writes; return 0; }); });
  require(writes == 0);
  daphne::cmd_readAFEReg read_request;
  read_request.set_afeblock(4);
  read_request.set_regaddress(51);
  unsigned reads = 0;
  auto read_response = read_live_afe_register(read_request, [&](uint32_t afe_pl, uint32_t address) {
    ++reads;
    require(afe_pl == 1 && address == 51);
    return 0x2345;
  });
  require(reads == 1 && read_response.regvalue() == 0x2345);
  require(read_response.afeblock() == 4 && read_response.hardware_readback());
  require(read_response.observed_monotonic_ns() > 0);
  read_request.set_afeblock(5);
  rejects([&] { read_live_afe_register(read_request, [&](uint32_t, uint32_t) { ++reads; return 0; }); });
  require(reads == 1);
  auto invalid = [&](const auto& modify) {
    auto bad = request;
    modify(bad);
    rejects([&] { validate_analog_configuration(bad); });
  };
  invalid([](auto& r) { r.set_biasctrl(4096); });
  invalid([](auto& r) { r.mutable_channels(0)->set_id(40); });
  invalid([](auto& r) { *r.add_channels() = r.channels(0); });
  invalid([](auto& r) { r.mutable_channels(0)->set_trim(4096); });
  invalid([](auto& r) { r.mutable_channels(0)->set_offset(4096); });
  for (uint32_t gain : {3u, 4u, UINT32_MAX}) {
    rejects([&] { offset_gain_bit(gain); });
    invalid([&](auto& r) { r.mutable_channels(0)->set_gain(gain); });
  }
  invalid([](auto& r) { r.mutable_afes(0)->set_id(5); });
  invalid([](auto& r) { *r.add_afes() = r.afes(0); });
  invalid([](auto& r) { r.mutable_afes(0)->set_v_bias(4096); });
  invalid([](auto& r) { r.mutable_afes(0)->set_attenuators(4096); });
  invalid([](auto& r) { r.mutable_afes(0)->mutable_pga()->set_lpf_cut_frequency(1); });
  invalid([](auto& r) { r.mutable_afes(0)->mutable_lna()->set_gain(4); });
  invalid([](auto& r) { r.mutable_afes(0)->mutable_lna()->set_clamp(4); });
  std::cout << "Configuration preflight, 1800 five-AFE BIAS writes including zero, "
               "offset DAC x1/x2, PGA gain and readback tests passed\n";
}
