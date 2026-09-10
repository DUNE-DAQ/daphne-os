#pragma once

#include <string>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
struct LoadedBoardIdentity {
  daphne::BoardIdentityAssignmentFile artifact;
  std::string artifact_sha256;
};

// Parsing/validation is hardware-free. Errors never echo private values.
void validate_identity_artifact(const daphne::BoardIdentityAssignmentFile& artifact);
LoadedBoardIdentity parse_identity_artifact(const std::string& bytes);
LoadedBoardIdentity load_identity_artifact(const std::string& path);

// No hardware setters or DNS. The Linux collector samples only the explicitly
// bound management interface; comparison is separate from assignment validity.
daphne::ManagementNetworkObservation read_management_network(
    const daphne::ManagementIdentityBinding& binding);
daphne::BoardIdentityStatus make_board_identity_status(
    const LoadedBoardIdentity* loaded,
    const daphne::ManagementNetworkObservation& observed,
    bool include_details, uint64_t now_monotonic_ns);
}
