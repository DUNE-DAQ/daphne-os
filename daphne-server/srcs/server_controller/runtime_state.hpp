#pragma once

#include <cstdint>
#include <functional>
#include <mutex>
#include <memory>
#include <string>
#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {
struct ObservationTime { uint64_t monotonic_ns; uint64_t host_unix_ns; };

// Process-local executor evidence. A restart deliberately forgets configuration
// validity: hardware may have survived while the previous process did not.
class RuntimeState {
 public:
  using Clock = std::function<ObservationTime()>;
  RuntimeState(std::string instance_id, std::string boot_id, Clock clock);
  void tick(); // Call from the responsive router loop, not from snapshot().
  daphne::ServerState snapshot() const;
  void begin_operation(uint32_t type, uint64_t task_id, uint64_t msg_id);
  void end_operation();
  void begin_configuration();
  void hardware_started();
  void finish_configuration(bool success, const std::string& reason,
                            const std::string& applied_sha256 = {}, bool complete_scope = false);
  void invalidate(const std::string& reason);

 private:
  Clock clock_;
  mutable std::mutex mutex_;
  daphne::ServerState state_;
  uint64_t invalidations_ = 0;
  uint64_t attempt_invalidations_ = 0;
};
std::shared_ptr<RuntimeState> make_process_runtime_state();
bool invalidates_configuration(daphne::MessageTypeV2 type);
} // namespace daphne_sc
