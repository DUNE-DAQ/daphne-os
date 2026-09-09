#include <iostream>
#include <map>
#include <stdexcept>
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
  for (uint32_t gain : {1u, 2u, UINT32_MAX})
    invalid([&](auto& r) { r.mutable_channels(0)->set_gain(gain); });
  invalid([](auto& r) { r.mutable_afes(0)->set_id(5); });
  invalid([](auto& r) { *r.add_afes() = r.afes(0); });
  invalid([](auto& r) { r.mutable_afes(0)->set_v_bias(4096); });
  invalid([](auto& r) { r.mutable_afes(0)->set_attenuators(4096); });
  invalid([](auto& r) { r.mutable_afes(0)->mutable_pga()->set_lpf_cut_frequency(1); });
  invalid([](auto& r) { r.mutable_afes(0)->mutable_lna()->set_gain(4); });
  invalid([](auto& r) { r.mutable_afes(0)->mutable_lna()->set_clamp(4); });
  std::cout << "Configuration preflight, PGA gain and readback tests passed\n";
}
