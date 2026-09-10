#include <iostream>
#include "server_controller/board_identity.hpp"
#include "server_controller/board_monitor.hpp"

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "Usage: identity_probe PRIVATE_BINARY_ARTIFACT (read-only local network comparison)\n";
    return 1;
  }
  try {
    const auto loaded = daphne_sc::load_identity_artifact(argv[1]);
    const auto observed = daphne_sc::read_management_network(loaded.artifact.binding());
    const auto status = daphne_sc::make_board_identity_status(&loaded, observed, false, daphne_sc::monotonic_time_ns());
    std::cout << "artifact_sha256=" << status.assignment_artifact_sha256()
              << " binding_state=" << daphne::IdentityBindingState_Name(status.binding_state())
              << " private_values=redacted\n";
    return status.binding_state() == daphne::IDENTITY_BINDING_MATCH ? 0 : 2;
  } catch (const std::exception& error) {
    std::cerr << "Identity probe failed: " << error.what() << '\n';
    return 1;
  }
}
