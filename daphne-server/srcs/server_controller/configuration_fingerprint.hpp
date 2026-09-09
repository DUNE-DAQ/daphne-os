#pragma once
#include <cstdint>
#include <string>
#include <utility>
#include <vector>
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"

namespace daphne_sc {
std::string sha256_hex(const std::string& bytes);
struct ConfigurationProfile {
  GatewareIdentity identity;
  GatewareMode mode;
  bool reset_enabled;
  bool automatic_alignment;
};
// Canonical successfully executed command profile, with post-application
// control-register observations supplied by the executor. No requested hash,
// management address, unused slot or client timeout is treated as hardware.
std::string canonical_configuration_evidence(
    const daphne::ConfigureRequest& config, const ConfigurationProfile& profile,
    std::vector<std::pair<uint32_t, uint32_t>> control_observations);
bool is_complete_configuration(const daphne::ConfigureRequest& config);
}
