#include <iostream>
#include <google/protobuf/util/json_util.h>
#include "server_controller/board_identity.hpp"
#include "server_controller/board_monitor.hpp"

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "Usage: management_link_probe PRIVATE_IDENTITY_ARTIFACT (read-only; link-only JSON)\n";
    return 1;
  }
  try {
    const auto loaded = daphne_sc::load_identity_artifact(argv[1]);
    const auto observed = daphne_sc::read_management_network(loaded.artifact.binding());
    const auto identity = daphne_sc::make_board_identity_status(&loaded, observed, false, daphne_sc::monotonic_time_ns());
    if (identity.binding_state() != daphne::IDENTITY_BINDING_MATCH || !observed.has_link())
      throw std::runtime_error("Management baseline did not match");
    std::string json;
    if (!google::protobuf::util::MessageToJsonString(observed.link(), &json).ok())
      throw std::runtime_error("Link serialization failed");
    // This submessage contains fixed labels/validated link measurements only.
    // Never serialize the parent observation, assignments, or private artifact.
    std::cout << json << '\n';
    return observed.link().quality() == daphne::MEASUREMENT_GOOD ? 0 : 2;
  } catch (const std::exception&) {
    std::cerr << "Management-link probe failed; private details suppressed\n";
    return 1;
  }
}
