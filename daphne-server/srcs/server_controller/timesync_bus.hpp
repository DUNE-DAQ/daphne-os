#pragma once
#include "server_controller/timesync.hpp"
#include <functional>
#include <systemd/sd-bus.h>

namespace daphne_sc {
enum class TimesyncBusQuery { BusId, Owner, Properties };
// Owns the returned message. Exposed to test exact method/flags without sending.
sd_bus_message* make_timesync_bus_request(sd_bus*, TimesyncBusQuery, const std::string& unique_owner = {});
TimesyncRaw parse_timesync_properties(sd_bus_message*);
// Uses the supplied connection only; production creates a fresh fixed local
// system-bus connection. Tests can supply an isolated socket-pair bus.
TimesyncRaw query_timesync_bus(sd_bus*, uint64_t deadline_ns, const std::function<uint64_t()>& now);
}  // namespace daphne_sc
