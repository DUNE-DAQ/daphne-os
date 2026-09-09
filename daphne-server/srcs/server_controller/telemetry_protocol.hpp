#pragma once

#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/board_monitor.hpp"

namespace daphne_sc {
daphne::GeneralInfo make_general_info(const BoardMonitorSnapshot& sample);
}
