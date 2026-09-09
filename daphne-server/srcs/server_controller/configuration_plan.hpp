#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"
#include "daphneV3_low_level_confs.pb.h"

namespace daphne_sc {
struct AfeFunctionWrite {
  std::string function;
  uint32_t value;
};
std::vector<AfeFunctionWrite> make_afe_function_plan(const daphne::AFEConfig& config);
// ChannelConfig.gain is an offset DAC multiplier, NOT the raw low-level bit.
// 0 (omitted legacy field) and 1 select x1; 2 selects x2. Reject other values.
bool offset_gain_bit(uint32_t gain);
void validate_analog_configuration(const daphne::ConfigureRequest& config);
// Apply the BIAS code for one present AFE entry, including zero. The callback
// receives the mapped PL AFE index; completing it is not analog readback.
void apply_afe_bias_command(
    const daphne::AFEConfig& config,
    const std::function<void(uint32_t, uint32_t)>& write_bias);
uint32_t apply_verified_afe_function(
    const AfeFunctionWrite& write,
    const std::function<uint32_t(const std::string&, uint32_t)>& set_and_read);
daphne::cmd_readAFEReg_response read_live_afe_register(
    const daphne::cmd_readAFEReg& request,
    const std::function<uint32_t(uint32_t, uint32_t)>& read_register);
}
