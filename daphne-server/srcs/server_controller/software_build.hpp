#pragma once
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
// Compiled-in metadata: no Git, file reads, subprocesses or hardware at runtime.
const daphne::ServerBuildInfo& server_build_info();
}
