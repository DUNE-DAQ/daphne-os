#pragma once

#include <functional>
#include <memory>
#include <string>
#include <unordered_map>

#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/gateware.hpp"
#include "server_controller/temperature_alarm.hpp"
#include "server_controller/board_identity.hpp"

class Daphne;

namespace daphne_sc {

using V2Handler = std::function<void(const std::string& req_payload, std::string& resp_payload, Daphne& daphne)>;

std::unordered_map<daphne::MessageTypeV2, V2Handler> make_v2_handlers(
    GatewareMode mode,
    std::shared_ptr<Mmio32> full_stream_mmio = nullptr,
    std::optional<GatewareIdentity> admitted_identity = std::nullopt,
    TemperatureAlarmPolicy temperature_policy = {},
    std::shared_ptr<const LoadedBoardIdentity> board_identity = nullptr);

}  // namespace daphne_sc
