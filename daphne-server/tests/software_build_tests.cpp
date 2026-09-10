#include <iostream>
#include <stdexcept>
#include <string>
#include "server_controller/runtime_state.hpp"
#include "server_controller/software_build.hpp"

namespace {
void require(bool value) { if (!value) throw std::runtime_error("Software build metadata test failed"); }
bool hex(const std::string& value, size_t size) {
  return value.size() == size && value.find_first_not_of("0123456789abcdef") == std::string::npos;
}
}
int main() {
  using namespace daphne_sc;
  const auto& info = server_build_info();
  require(&info == &server_build_info());
  require(info.metadata_format_version() == 1 && info.component() == "daphne-server");
  require(info.control_envelope_version() == 2);
  require(hex(info.high_level_schema_sha256(), 64) && hex(info.low_level_schema_sha256(), 64));
  require(info.high_level_schema_sha256() != info.low_level_schema_sha256());
  require(!info.compiler_id().empty() && !info.compiler_version().empty());
  require(!info.target_architecture().empty() && !info.protobuf_compile_version().empty());
  if (info.source_quality() == daphne::MEASUREMENT_GOOD) {
    const auto length = info.source_git_commit().size();
    require((length == 40 || length == 64) && hex(info.source_git_commit(), length));
    require(hex(info.committed_source_tree(), length) && info.has_source_worktree_dirty());
    require(info.software_version() == "git:" + info.source_git_commit() +
        (info.source_worktree_dirty() ? "-dirty" : ""));
  } else {
    require(info.source_quality() == daphne::MEASUREMENT_UNAVAILABLE);
    require(!info.has_source_git_commit() && !info.has_committed_source_tree());
    require(!info.has_source_worktree_dirty() && !info.has_software_version());
  }
  daphne::ServerBuildInfo decoded;
  require(decoded.ParseFromString(info.SerializeAsString()));
  require(decoded.SerializeAsString() == info.SerializeAsString());
  uint64_t now = 100;
  RuntimeState runtime("test-instance", "test-boot", [&] { return ObservationTime{++now, 0}; });
  runtime.tick();
  const auto before = runtime.snapshot();
  runtime.begin_operation(202, 17, 19);
  runtime.begin_configuration();
  runtime.hardware_started();
  const auto during = runtime.snapshot();
  require(before.server_build().SerializeAsString() == info.SerializeAsString());
  require(during.server_build().SerializeAsString() == info.SerializeAsString());
  require(during.configuration_in_progress());
  daphne::SystemStatusSnapshot status;
  *status.mutable_server_build() = info;
  daphne::SystemStatusSnapshot roundtrip;
  require(roundtrip.ParseFromString(status.SerializeAsString()));
  require(roundtrip.server_build().SerializeAsString() == info.SerializeAsString());
  std::cout << "Compiled source/schema metadata, presence, wire round trips and busy-state stability passed\n";
}
