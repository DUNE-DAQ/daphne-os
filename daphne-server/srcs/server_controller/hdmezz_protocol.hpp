#pragma once

#include "DaphneI2CDrivers.hpp"
#include "daphneV3_low_level_confs.pb.h"

namespace daphne_sc {
// Return true only for a complete fresh hardware calibration pair. No I/O.
bool fill_hdmezz_configuration(
    const I2CMezzDrivers::HDMezzDriver::ConfigurationSnapshot& snapshot,
    daphne::cmd_readHDMezzBlockConfig_response& response);
}
