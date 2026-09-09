#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"

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
}
