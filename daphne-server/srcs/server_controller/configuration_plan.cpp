#include "server_controller/configuration_plan.hpp"

#include <set>
#include <stdexcept>

namespace daphne_sc {
std::vector<AfeFunctionWrite> make_afe_function_plan(const daphne::AFEConfig& config) {
  const auto lpf = config.pga().lpf_cut_frequency();
  if (lpf != 0 && lpf != 2 && lpf != 3 && lpf != 4)
    throw std::invalid_argument("PGA LPF code must be 0, 2, 3 or 4");
  if (config.lna().clamp() > 3 || config.lna().gain() > 3)
    throw std::invalid_argument("LNA clamp/gain code must be 0..3");
  return {
      {"SERIALIZED_DATA_RATE", 1},
      {"ADC_RESOLUTION_RESET", config.adc().resolution()},
      {"ADC_OUTPUT_FORMAT", config.adc().output_format()},
      {"LSB_MSB_FIRST", config.adc().sb_first()},
      {"LPF_PROGRAMMABILITY", lpf},
      // AFE5808A register 51 bit 13: 0 = 24 dB, 1 = 30 dB.
      {"PGA_GAIN_CONTROL", config.pga().gain()},
      {"PGA_INTEGRATOR_DISABLE", config.pga().integrator_disable()},
      {"PGA_CLAMP_LEVEL", 2},
      {"ACTIVE_TERMINATION_ENABLE", 0},
      {"LNA_INPUT_CLAMP_SETTING", config.lna().clamp()},
      {"LNA_GAIN", config.lna().gain()},
      {"LNA_INTEGRATOR_DISABLE", config.lna().integrator_disable()},
  };
}

void validate_analog_configuration(const daphne::ConfigureRequest& config) {
  if (config.biasctrl() > 4095)
    throw std::invalid_argument("Bias Control out of range (0..4095)");
  std::set<uint32_t> channels;
  for (const auto& channel : config.channels()) {
    if (channel.id() >= 40 || !channels.insert(channel.id()).second)
      throw std::invalid_argument("Channel IDs must be unique and in 0..39");
    if (channel.trim() > 4095 || channel.offset() > 4095)
      throw std::invalid_argument("Channel trim/offset out of range (0..4095)");
    if (channel.gain() != 0)
      throw std::invalid_argument(
          "ChannelConfig.gain is unsupported: the 1/2 to hardware mapping is unqualified; "
          "0 means unspecified (legacy DAC gain-bit behavior). No configuration was applied");
  }
  std::set<uint32_t> afes;
  for (const auto& afe : config.afes()) {
    if (afe.id() >= 5 || !afes.insert(afe.id()).second)
      throw std::invalid_argument("AFE IDs must be unique and in 0..4");
    if (afe.attenuators() > 4095 || afe.v_bias() > 4095)
      throw std::invalid_argument("AFE VGAIN/BIAS out of range (0..4095)");
    make_afe_function_plan(afe);
  }
}

uint32_t apply_verified_afe_function(
    const AfeFunctionWrite& write,
    const std::function<uint32_t(const std::string&, uint32_t)>& set_and_read) {
  if (write.value > 0xFFFF)
    throw std::invalid_argument("AFE value out of range (0..65535); refusing implicit narrowing");
  const auto actual = set_and_read(write.function, write.value);
  if (actual != write.value)
    throw std::runtime_error("AFE " + write.function + " readback mismatch: requested " +
                             std::to_string(write.value) + ", read " + std::to_string(actual));
  return actual;
}
}
