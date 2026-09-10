#include "server_controller/native_timestamp.hpp"
#include "server_controller/timing_status.hpp"
#include <stdexcept>

namespace daphne_sc {
namespace {
constexpr uint32_t kValid = 1U, kExternal = 2U, kTimeout = 4U, kBusy = 8U;
constexpr uint32_t kReceived = 16U, kSourceInvalid = 32U, kContextInvalid = 64U;

bool status_consistent(uint32_t status) {
  const bool received = (status & kReceived) != 0;
  const bool timeout = (status & kTimeout) != 0;
  const bool busy = (status & kBusy) != 0;
  if ((status & ~0x7fU) != 0 || unsigned(received) + unsigned(timeout) + unsigned(busy) != 1)
    return false;
  if ((status & kSourceInvalid) && !received) return false;
  const bool valid = received && !(status & (kSourceInvalid | kContextInvalid));
  return ((status & kValid) != 0) == valid;
}
}

void invalidate_native_timestamp(daphne::NativeTimestampObservation& result,
    daphne::MeasurementQuality quality, const char* reason) {
  result.set_quality(quality);
  result.set_message(reason);
  result.clear_advancing(); result.clear_delta_ticks();
  result.set_identity_bracket_verified(false);
  for (auto& sample : *result.mutable_samples()) {
    sample.clear_timestamp_ticks();
    if (sample.quality() == daphne::MEASUREMENT_GOOD || sample.quality() == daphne::MEASUREMENT_UNAVAILABLE) {
      sample.set_quality(quality); sample.set_message(reason);
    }
  }
}

bool native_timestamp_pair_consistent(const daphne::NativeTimestampObservation& result) noexcept {
  if (result.quality() != daphne::MEASUREMENT_GOOD || !result.has_feature_abi() ||
      !result.has_feature_abi_after() || result.feature_abi() != kNativeTimestampAbi ||
      result.feature_abi_after() != kNativeTimestampAbi || !result.has_timeout_cycles() ||
      !result.has_timeout_cycles_after() || result.timeout_cycles() < 8 || result.timeout_cycles() > (1U << 20) ||
      result.timeout_cycles_after() != result.timeout_cycles() || !result.has_advancing() || !result.has_delta_ticks() ||
      result.maximum_attempts_per_sample() != kNativeTimestampMaximumAttempts ||
      result.maximum_acquisition_ms() != kNativeTimestampMaximumAcquisitionMs ||
      !result.acquisition_started_monotonic_ns() || result.observed_monotonic_ns() < result.acquisition_started_monotonic_ns() ||
      result.observed_monotonic_ns() - result.acquisition_started_monotonic_ns() > kNativeTimestampMaximumAcquisitionMs * 1000000 ||
      result.samples_size() > int(2 * kNativeTimestampMaximumAttempts)) return false;
  const daphne::NativeTimestampSample* selected[2]{};
  unsigned next_index = 0, next_attempt = 1;
  uint64_t previous_observed = result.acquisition_started_monotonic_ns();
  for (const auto& sample : result.samples()) {
    if (next_index > 1 || sample.sample_index() != next_index || sample.attempt_index() != next_attempt ||
        sample.attempt_index() > kNativeTimestampMaximumAttempts ||
        !sample.has_sequence_before() || !sample.has_sequence_first() || !sample.has_sequence_after() ||
        !sample.has_request_status_raw() || !sample.has_status_raw() || !sample.has_low_raw() || !sample.has_high_raw() ||
        sample.acquisition_started_monotonic_ns() < previous_observed ||
        sample.observed_monotonic_ns() < sample.acquisition_started_monotonic_ns() ||
        sample.observed_monotonic_ns() > result.observed_monotonic_ns()) return false;
    previous_observed = sample.observed_monotonic_ns();
    const bool coherent = sample.sequence_first() == static_cast<uint32_t>(sample.sequence_before() + 1U) &&
        sample.sequence_first() == sample.sequence_after() && sample.request_status_raw() == sample.status_raw();
    if (sample.quality() != daphne::MEASUREMENT_GOOD) {
      // Only complete conflicting reads can be retried into a GOOD pair.
      if (sample.quality() != daphne::MEASUREMENT_ERROR || sample.has_timestamp_ticks() || coherent) return false;
      ++next_attempt;
      continue;
    }
    if (!coherent || !sample.has_timestamp_ticks() ||
        (sample.status_raw() != 0x11 && sample.status_raw() != 0x13) ||
        sample.source() != (sample.status_raw() == 0x11 ? daphne::NATIVE_TIMESTAMP_LOCAL_COUNTER : daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS) ||
        sample.timestamp_ticks() != ((uint64_t(sample.high_raw()) << 32) | sample.low_raw())) return false;
    selected[sample.sample_index()] = &sample;
    ++next_index;
    next_attempt = 1;
  }
  if (!selected[0] || !selected[1] || selected[0]->source() != selected[1]->source() ||
      selected[1]->acquisition_started_monotonic_ns() < selected[0]->observed_monotonic_ns()) return false;
  const auto delta = selected[1]->timestamp_ticks() - selected[0]->timestamp_ticks();
  return result.delta_ticks() == delta && result.advancing() == (delta != 0 && delta < (uint64_t{1} << 63));
}

daphne::NativeTimestampObservation read_native_timestamp(
    Mmio32& mmio, uint32_t admitted_abi, const TimestampClock& clock) {
  daphne::NativeTimestampObservation result;
  result.set_maximum_attempts_per_sample(kNativeTimestampMaximumAttempts);
  result.set_maximum_acquisition_ms(kNativeTimestampMaximumAcquisitionMs);
  // Do not even probe the feature magic on a decoder with old address aliases.
  if (!supports_live_timestamp(admitted_abi)) {
    result.set_message("Native live timestamp unavailable: platform ABI 2.1 or 2.2 required; no snapshot addresses read");
    return result;
  }
  try {
    const uint64_t started = clock();
    result.set_acquisition_started_monotonic_ns(started);
    if (started == 0) throw std::runtime_error("Invalid observation clock");
    uint64_t last_observed = started;
    auto read = [&](uint32_t offset) { return mmio.read32(kTimingRegisterBase + offset); };
    auto within_budget = [&](uint64_t observed) {
      result.set_observed_monotonic_ns(observed);
      if (observed < last_observed) throw std::runtime_error("Observation clock moved backwards");
      last_observed = observed;
      if (observed - started > kNativeTimestampMaximumAcquisitionMs * 1000000) {
        invalidate_native_timestamp(result, daphne::MEASUREMENT_STALE,
            "Native timestamp collection exceeded its host observation budget");
        return false;
      }
      return true;
    };
    result.set_feature_abi(read(0x10));
    if (result.feature_abi() != kNativeTimestampAbi)
      throw std::runtime_error("Unknown snapshot feature ABI");
    result.set_timeout_cycles(read(0x28));
    if (result.timeout_cycles() < 8 || result.timeout_cycles() > (1U << 20))
      throw std::runtime_error("Snapshot mailbox budget outside supported bounds");
    if (!within_budget(clock())) return result;
    uint64_t ticks[2]{};
    daphne::NativeTimestampSource sources[2]{};
    for (uint32_t index = 0; index < 2; ++index) {
      bool captured = false;
      for (uint32_t attempt = 1; attempt <= kNativeTimestampMaximumAttempts; ++attempt) {
        auto* sample = result.add_samples();
        sample->set_sample_index(index); sample->set_attempt_index(attempt);
        const uint64_t attempt_start = clock();
        sample->set_acquisition_started_monotonic_ns(attempt_start);
        if (!within_budget(attempt_start)) return result;
        sample->set_sequence_before(read(0x18));
        sample->set_request_status_raw(read(0x14));
        sample->set_sequence_first(read(0x18));
        sample->set_status_raw(read(0x1c));
        sample->set_low_raw(read(0x20));
        sample->set_high_raw(read(0x24));
        sample->set_sequence_after(read(0x18));
        const auto observed = clock();
        sample->set_observed_monotonic_ns(observed);
        if (observed < attempt_start) throw std::runtime_error("Observation clock moved backwards");
        if (!within_budget(observed)) return result;
        if (sample->sequence_first() != static_cast<uint32_t>(sample->sequence_before() + 1U) ||
            sample->sequence_first() != sample->sequence_after() ||
            sample->status_raw() != sample->request_status_raw()) {
          sample->set_quality(daphne::MEASUREMENT_ERROR);
          sample->set_message("Snapshot sequence/status conflict; raw words are not a qualified sample");
          continue;
        }
        const auto status = sample->status_raw();
        if (!status_consistent(status)) throw std::runtime_error("Inconsistent snapshot status flags");
        sample->set_source((status & kExternal) ? daphne::NATIVE_TIMESTAMP_EXTERNAL_PDTS :
                                                 daphne::NATIVE_TIMESTAMP_LOCAL_COUNTER);
        if (!(status & kValid)) {
          if (sample->low_raw() != 0 || sample->high_raw() != 0)
            throw std::runtime_error("Failed snapshot retained nonzero data");
          const char* reason = (status & kTimeout) ? "Native snapshot timed out; no usable timestamp" :
              (status & kBusy) ? "Native snapshot mailbox unavailable/quarantined; no request accepted" :
              (status & kContextInvalid) ? "Native snapshot clock/endpoint context invalidated" :
              "Native timestamp source marked its payload invalid";
          sample->set_message(reason);
          invalidate_native_timestamp(result, daphne::MEASUREMENT_UNAVAILABLE, reason);
          return result;
        }
        ticks[index] = (uint64_t(sample->high_raw()) << 32) | sample->low_raw();
        sources[index] = sample->source();
        sample->set_timestamp_ticks(ticks[index]);
        sample->set_quality(daphne::MEASUREMENT_GOOD);
        sample->set_message("Coherent native snapshot; outer FPGA identity/programming bracket still required");
        captured = true;
        break;
      }
      if (!captured) throw std::runtime_error("Snapshot conflicts exhausted the retry budget");
    }
    result.set_feature_abi_after(read(0x10));
    result.set_timeout_cycles_after(read(0x28));
    if (!within_budget(clock())) return result;
    if (result.feature_abi_after() != result.feature_abi() || result.timeout_cycles_after() != result.timeout_cycles())
      throw std::runtime_error("Snapshot feature metadata changed during collection");
    if (sources[0] != sources[1]) {
      invalidate_native_timestamp(result, daphne::MEASUREMENT_UNAVAILABLE,
          "Native timestamp source changed between samples; counters cannot be compared");
      return result;
    }
    const uint64_t delta = ticks[1] - ticks[0];
    result.set_delta_ticks(delta);
    result.set_advancing(delta != 0 && delta < (uint64_t{1} << 63));
    result.set_quality(daphne::MEASUREMENT_GOOD);
    result.set_message(result.advancing() ?
        "Selected native timestamp advanced; not a frequency, epoch or acquisition-alignment qualification" :
        delta == 0 ? "Two coherent native timestamp samples did not advance" :
        "Native timestamp changed non-forward or discontinuously; no reset/epoch continuity established");
    return result;
  } catch (const std::exception&) {
    invalidate_native_timestamp(result, daphne::MEASUREMENT_ERROR,
        "Native timestamp transaction failed validation or register access; inspect retained raw evidence");
    if (result.samples_size()) {
      auto* last = result.mutable_samples(result.samples_size() - 1);
      if (last->quality() == daphne::MEASUREMENT_UNAVAILABLE) {
        last->set_quality(daphne::MEASUREMENT_ERROR);
        last->set_message(result.message());
      }
    }
    return result;
  }
}
}
