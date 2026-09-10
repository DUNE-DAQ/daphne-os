#include "server_controller/protocol_errors.hpp"
#include "server_controller/timing_status.hpp"
#include <limits>
#include <stdexcept>

namespace daphne_sc {
namespace {
bool coherent(const daphne::ProtocolErrorAttempt& a) {
  return a.has_sequence_before() && a.has_sequence_first() && a.has_sequence_after() &&
      a.has_request_status_raw() && a.has_status_raw() && a.has_count_raw() && a.has_detail_raw() &&
      a.sequence_first() == static_cast<uint32_t>(a.sequence_before() + 1U) &&
      a.sequence_first() == a.sequence_after() && a.request_status_raw() == a.status_raw();
}
bool payload_consistent(uint32_t count, uint32_t detail) {
  const bool saturated = (detail & 32U) != 0, overflowed = (detail & 64U) != 0;
  return (detail & ~0xffU) == 0 && ((count == 0) == ((detail & 31U) == 0)) &&
      saturated == (count == std::numeric_limits<uint32_t>::max()) && (!overflowed || saturated);
}
}

void invalidate_protocol_error_history(daphne::ProtocolErrorObservation& result,
    daphne::MeasurementQuality quality, const char* reason) {
  result.set_quality(quality); result.set_message(reason);
  result.clear_count(); result.clear_reasons_seen(); result.clear_saturated();
  result.clear_overflowed(); result.clear_receiver_reset();
  result.set_identity_bracket_verified(false); result.set_reset_epoch_known(false);
  for (auto& attempt : *result.mutable_attempts()) {
    if (attempt.quality() == daphne::MEASUREMENT_GOOD || attempt.quality() == daphne::MEASUREMENT_UNAVAILABLE) {
      attempt.set_quality(quality); attempt.set_message(reason);
    }
  }
}

bool protocol_error_history_consistent(const daphne::ProtocolErrorObservation& r) noexcept {
  if (r.quality() != daphne::MEASUREMENT_GOOD || !r.has_feature_abi() || !r.has_feature_abi_after() ||
      r.feature_abi() != kProtocolErrorAbi || r.feature_abi_after() != kProtocolErrorAbi ||
      !r.has_timeout_cycles() || !r.has_timeout_cycles_after() || r.timeout_cycles() < 8 ||
      r.timeout_cycles() > (1U << 20) || r.timeout_cycles_after() != r.timeout_cycles() ||
      r.maximum_attempts() != kProtocolErrorMaximumAttempts || r.maximum_acquisition_ms() != kProtocolErrorMaximumAcquisitionMs ||
      r.counter_width_bits() != 32 || r.counted_scope() != daphne::PROTOCOL_ERROR_RX_PARSER_EPISODES ||
      r.lifetime() != daphne::PROTOCOL_ERROR_PLATFORM_RESET || r.reset_epoch_known() ||
      !r.has_count() || !r.has_reasons_seen() || !r.has_saturated() || !r.has_overflowed() || !r.has_receiver_reset() ||
      r.attempts_size() < 1 || r.attempts_size() > int(kProtocolErrorMaximumAttempts) ||
      !r.acquisition_started_monotonic_ns() || r.observed_monotonic_ns() < r.acquisition_started_monotonic_ns() ||
      r.observed_monotonic_ns() - r.acquisition_started_monotonic_ns() > kProtocolErrorMaximumAcquisitionMs * 1000000)
    return false;
  uint64_t last = r.acquisition_started_monotonic_ns();
  for (int i = 0; i < r.attempts_size(); ++i) {
    const auto& a = r.attempts(i);
    if (a.attempt_index() != unsigned(i + 1) || a.acquisition_started_monotonic_ns() < last ||
        a.observed_monotonic_ns() < a.acquisition_started_monotonic_ns() ||
        a.observed_monotonic_ns() > r.observed_monotonic_ns() ||
        !a.has_sequence_before() || !a.has_sequence_first() || !a.has_sequence_after() ||
        !a.has_request_status_raw() || !a.has_status_raw() || !a.has_count_raw() || !a.has_detail_raw())
      return false;
    last = a.observed_monotonic_ns();
    if (i + 1 < r.attempts_size()) {
      if (a.quality() != daphne::MEASUREMENT_ERROR || coherent(a)) return false;
    } else {
      if (a.quality() != daphne::MEASUREMENT_GOOD || !coherent(a) || a.status_raw() != 0x11 ||
          !payload_consistent(a.count_raw(), a.detail_raw()) || r.count() != a.count_raw() ||
          r.reasons_seen() != (a.detail_raw() & 31U) || r.saturated() != bool(a.detail_raw() & 32U) ||
          r.overflowed() != bool(a.detail_raw() & 64U) || r.receiver_reset() != bool(a.detail_raw() & 128U))
        return false;
    }
  }
  return true;
}

daphne::ProtocolErrorObservation read_protocol_error_history(
    Mmio32& mmio, uint32_t admitted_abi, const ProtocolErrorClock& clock) {
  daphne::ProtocolErrorObservation r;
  r.set_maximum_attempts(kProtocolErrorMaximumAttempts);
  r.set_maximum_acquisition_ms(kProtocolErrorMaximumAcquisitionMs);
  if (!supports_protocol_error_history(admitted_abi)) {
    r.set_message("Parser history unavailable: exact platform ABI 2.2 required; no diagnostic addresses read");
    return r;
  }
  r.set_counter_width_bits(32);
  r.set_counted_scope(daphne::PROTOCOL_ERROR_RX_PARSER_EPISODES);
  r.set_lifetime(daphne::PROTOCOL_ERROR_PLATFORM_RESET);
  try {
    const auto started = clock();
    if (!started) throw std::runtime_error("Invalid observation clock");
    r.set_acquisition_started_monotonic_ns(started);
    uint64_t last = started;
    auto read = [&](uint32_t offset) { return mmio.read32(kTimingRegisterBase + offset); };
    auto budget = [&](uint64_t observed) {
      r.set_observed_monotonic_ns(observed);
      if (observed < last) throw std::runtime_error("Observation clock moved backwards");
      last = observed;
      if (observed - started > kProtocolErrorMaximumAcquisitionMs * 1000000) {
        invalidate_protocol_error_history(r, daphne::MEASUREMENT_STALE, "Parser history exceeded its host observation budget");
        return false;
      }
      return true;
    };
    r.set_feature_abi(read(0x30));
    if (r.feature_abi() != kProtocolErrorAbi) throw std::runtime_error("Unknown protocol feature ABI");
    r.set_timeout_cycles(read(0x48));
    if (r.timeout_cycles() < 8 || r.timeout_cycles() > (1U << 20))
      throw std::runtime_error("Protocol mailbox budget outside supported bounds");
    if (!budget(clock())) return r;
    bool captured = false;
    const char* unavailable = nullptr;
    uint32_t count = 0, detail = 0;
    for (uint32_t index = 1; index <= kProtocolErrorMaximumAttempts; ++index) {
      auto* a = r.add_attempts(); a->set_attempt_index(index);
      a->set_acquisition_started_monotonic_ns(clock());
      if (!budget(a->acquisition_started_monotonic_ns())) return r;
      a->set_sequence_before(read(0x38));
      a->set_request_status_raw(read(0x34));
      a->set_sequence_first(read(0x38));
      a->set_status_raw(read(0x3c));
      a->set_count_raw(read(0x40));
      a->set_detail_raw(read(0x44));
      a->set_sequence_after(read(0x38));
      a->set_observed_monotonic_ns(clock());
      if (!budget(a->observed_monotonic_ns())) return r;
      if (!coherent(*a)) {
        a->set_quality(daphne::MEASUREMENT_ERROR);
        a->set_message("Protocol snapshot sequence/status conflict; raw words are not a usable count");
        continue;
      }
      if (a->status_raw() == 4 || a->status_raw() == 8) {
        if (a->count_raw() != 0 || a->detail_raw() != 0)
          throw std::runtime_error("Unavailable protocol snapshot retained data");
        unavailable = a->status_raw() == 4 ? "Parser source-clock snapshot timed out; no usable history" :
            "Parser snapshot mailbox busy/quarantined; no request accepted";
        a->set_message(unavailable);
        break; // Retry conflicts only, never spin on a stopped clock.
      }
      if (a->status_raw() != 0x11 || !payload_consistent(a->count_raw(), a->detail_raw()))
        throw std::runtime_error("Inconsistent protocol status or payload");
      count = a->count_raw(); detail = a->detail_raw(); captured = true;
      a->set_quality(daphne::MEASUREMENT_GOOD);
      a->set_message("Coherent native history; outer identity/programming bracket still required");
      break;
    }
    if (!captured && !unavailable) throw std::runtime_error("Protocol conflicts exhausted retry budget");
    r.set_feature_abi_after(read(0x30)); r.set_timeout_cycles_after(read(0x48));
    if (!budget(clock())) return r;
    if (r.feature_abi_after() != r.feature_abi() || r.timeout_cycles_after() != r.timeout_cycles())
      throw std::runtime_error("Protocol feature metadata changed during collection");
    if (unavailable) {
      invalidate_protocol_error_history(r, daphne::MEASUREMENT_UNAVAILABLE, unavailable);
      return r;
    }
    r.set_count(count); r.set_reasons_seen(detail & 31U); r.set_saturated(detail & 32U);
    r.set_overflowed(detail & 64U); r.set_receiver_reset(detail & 128U);
    r.set_quality(daphne::MEASUREMENT_GOOD);
    r.set_message("Receive-parser error episodes since an unobserved common platform reset; not current failure, all protocol errors or since-boot history");
    return r;
  } catch (const std::exception&) {
    invalidate_protocol_error_history(r, daphne::MEASUREMENT_ERROR,
        "Parser history failed validation or register access; inspect retained raw evidence");
    return r;
  }
}
}
