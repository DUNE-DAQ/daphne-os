#pragma once

#include <array>
#include <string>
#include <vector>

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
inline constexpr std::array<const char*, 8> kServiceUnits{{
    "daphne-runtime.target", "daphne-gateware-prepare.service", "firmware.service",
    "daphne-gateware-verify.service", "clockchip.service", "endpoint.service",
    "hermes.service", "daphne.service"}};

std::vector<daphne::ServiceStatus> parse_service_status(const std::string& output,
                                                     uint64_t host_ns, uint64_t mono_ns);
// Fixed argv, bounded subprocess, no shell, no arbitrary unit/property names,
// no journal, command lines, credentials, environment or network identity.
void add_service_status(daphne::SystemStatusSnapshot& status);
void add_host_status(daphne::SystemStatusSnapshot& status, bool mezzanine_access_enabled);
}  // namespace daphne_sc
