#include "server_controller/software_build.hpp"
#include "server_controller/v2_envelope.hpp"
#include "server_build_info.generated.hpp"

namespace daphne_sc {
const daphne::ServerBuildInfo& server_build_info() {
  static const auto info = [] {
    using namespace compiled_build;
    daphne::ServerBuildInfo result;
    result.set_metadata_format_version(1);
    result.set_component("daphne-server");
    if (*source_commit && *source_tree && *source_dirty) {
      const bool dirty = std::string(source_dirty) == "true";
      result.set_source_git_commit(source_commit);
      result.set_committed_source_tree(source_tree);
      result.set_source_worktree_dirty(dirty);
      result.set_software_version(std::string("git:") + source_commit + (dirty ? "-dirty" : ""));
      result.set_source_quality(daphne::MEASUREMENT_GOOD);
      result.set_source_detail("Build-time Git HEAD and server-directory status; committed tree is not a dirty-worktree digest or attestation");
    } else {
      result.set_source_quality(daphne::MEASUREMENT_UNAVAILABLE);
      result.set_source_detail("No stable committed server-tree metadata at build time; no source revision inferred from export labels");
    }
    result.set_high_level_schema_sha256(high_schema_sha256);
    result.set_low_level_schema_sha256(low_schema_sha256);
    result.set_control_envelope_version(v2::kControlEnvelopeVersion);
    result.set_compiler_id(compiler_id);
    result.set_compiler_version(compiler_version);
    result.set_target_architecture(target_architecture);
    result.set_protobuf_compile_version(protobuf_version);
    return result;
  }();
  return info;
}
}
