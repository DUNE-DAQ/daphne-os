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
void validate_analog_configuration(const daphne::ConfigureRequest& config);
uint32_t apply_verified_afe_function(
    const AfeFunctionWrite& write,
    const std::function<uint32_t(const std::string&, uint32_t)>& set_and_read);
daphne::cmd_readAFEReg_response read_live_afe_register(
    const daphne::cmd_readAFEReg& request,
    const std::function<uint32_t(uint32_t, uint32_t)>& read_register);
}
