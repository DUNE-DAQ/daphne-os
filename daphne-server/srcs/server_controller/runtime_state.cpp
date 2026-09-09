#include "server_controller/runtime_state.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace daphne_sc {
namespace {
std::string bounded_reason(std::string text) {
  if (text.size() > 512) text.resize(512);
  for (char& c : text) if (static_cast<unsigned char>(c) < 32 || c == 127) c = ' ';
  return text;
}
bool sha256_text(const std::string& text) {
  return text.size() == 64 && text.find_first_not_of("0123456789abcdef") == std::string::npos;
}
}

RuntimeState::RuntimeState(std::string instance_id, std::string boot_id, Clock clock)
    : clock_(std::move(clock)) {
  if (!clock_ || instance_id.empty() || boot_id.empty())
    throw std::invalid_argument("Runtime state needs a clock and process/boot identities");
  state_.set_success(true);
  state_.set_instance_id(std::move(instance_id));
  state_.set_boot_id(std::move(boot_id));
  state_.set_invalidation_reason("Server started; no complete configuration applied by this process");
  state_.set_configuration_scope("Complete 40-channel/five-AFE aggregate execution; known local invalidations only, not analog readback or detection of every external reset");
  state_.mutable_last_configuration_result()->set_outcome(daphne::CONFIGURATION_NEVER_ATTEMPTED);
  state_.set_message("Executor bookkeeping; heartbeat indicates router progress, not FPGA/timing readiness. Host wall clock is unverified");
}

void RuntimeState::tick() {
  std::lock_guard<std::mutex> lock(mutex_);
  const auto now = clock_();
  const auto last = state_.heartbeat_monotonic_ns();
  if (now.monotonic_ns && (!last || (now.monotonic_ns >= last && now.monotonic_ns - last >= 1'000'000'000ULL))) {
    state_.set_heartbeat_sequence(state_.heartbeat_sequence() + 1);
    state_.set_heartbeat_monotonic_ns(now.monotonic_ns);
  }
}

daphne::ServerState RuntimeState::snapshot() const {
  std::lock_guard<std::mutex> lock(mutex_);
  auto result = state_;
  const auto now = clock_();
  result.set_observed_monotonic_ns(now.monotonic_ns);
  result.set_observed_host_unix_ns(now.host_unix_ns);
  return result; // Reading status never fabricates a new heartbeat.
}

void RuntimeState::begin_operation(uint32_t type, uint64_t task_id, uint64_t msg_id) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_.executor_busy()) throw std::logic_error("Hardware executor is already busy");
  state_.set_executor_busy(true);
  state_.set_executor_request_type(type);
  state_.set_executor_task_id(task_id);
  state_.set_executor_request_msg_id(msg_id);
}

void RuntimeState::end_operation() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_.configuration_in_progress()) throw std::logic_error("Configuration result was not finalized");
  state_.set_executor_busy(false);
  state_.clear_executor_request_type();
  state_.clear_executor_task_id();
  state_.clear_executor_request_msg_id();
}

void RuntimeState::begin_configuration() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!state_.executor_busy() || state_.configuration_in_progress())
    throw std::logic_error("Configuration must belong to one serialized executor operation");
  auto* result = state_.mutable_last_configuration_result();
  const uint64_t attempt = result->attempt_sequence() + 1;
  result->Clear();
  result->set_attempt_sequence(attempt);
  result->set_task_id(state_.executor_task_id());
  result->set_request_msg_id(state_.executor_request_msg_id());
  result->set_outcome(daphne::CONFIGURATION_RUNNING);
  result->set_started_monotonic_ns(clock_().monotonic_ns);
  state_.set_configuration_in_progress(true);
  attempt_invalidations_ = invalidations_;
}

void RuntimeState::hardware_started() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!state_.configuration_in_progress()) throw std::logic_error("No configuration attempt");
  state_.mutable_last_configuration_result()->set_hardware_started(true);
  state_.set_applied_configuration_valid(false);
  state_.set_invalidation_reason("Configuration is changing hardware");
}

void RuntimeState::finish_configuration(bool success, const std::string& reason,
                                        const std::string& applied_sha256, bool complete_scope) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!state_.configuration_in_progress()) throw std::logic_error("No configuration attempt");
  auto* result = state_.mutable_last_configuration_result();
  if (success && (!result->hardware_started() || (complete_scope && !sha256_text(applied_sha256))))
    throw std::logic_error("Successful complete configuration needs executed hardware and canonical SHA-256 evidence");
  result->set_outcome(success ? daphne::CONFIGURATION_SUCCEEDED :
      (result->hardware_started() ? daphne::CONFIGURATION_FAILED : daphne::CONFIGURATION_REJECTED));
  result->set_reason(bounded_reason(reason));
  const auto now = clock_();
  result->set_completed_monotonic_ns(now.monotonic_ns);
  result->set_completed_host_unix_ns(now.host_unix_ns);
  if (success && complete_scope && invalidations_ == attempt_invalidations_) {
    state_.set_applied_configuration_hash(applied_sha256);
    state_.set_applied_configuration_valid(true);
    state_.clear_invalidation_reason();
  } else if (result->hardware_started() && invalidations_ == attempt_invalidations_) {
    state_.set_applied_configuration_valid(false);
    state_.set_invalidation_reason(success ? "Partial aggregate does not establish a complete board configuration" :
        "Configuration failed after hardware access; hardware may be partially configured");
  }
  // A concurrent protective invalidation must never be erased by completion.
  state_.set_configuration_in_progress(false);
}

void RuntimeState::invalidate(const std::string& reason) {
  std::lock_guard<std::mutex> lock(mutex_);
  ++invalidations_;
  state_.set_applied_configuration_valid(false);
  state_.set_invalidation_reason(bounded_reason(reason));
}
} // namespace daphne_sc
