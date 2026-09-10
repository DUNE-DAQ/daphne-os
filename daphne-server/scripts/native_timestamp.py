"""Independent wire-evidence checks for the ABI 2.1/2.2 diagnostic timestamp.

No I/O or hardware access. Counter progress does not qualify clock frequency,
external synchronization, reset epoch, or waveform/acquisition alignment.
"""

RAW_FIELDS = ("sequence_before", "request_status_raw", "sequence_first", "status_raw",
              "low_raw", "high_raw", "sequence_after")
FEATURE_FIELDS = ("feature_abi", "feature_abi_after", "timeout_cycles", "timeout_cycles_after")


def require(ok, reason):
    if not ok:
        raise RuntimeError("Native timestamp: " + reason)


def check_progress(status, h, now):
    """Return independently derived health state; reject malformed usable claims."""
    ep, identity, programming = status.endpoint, status.gateware_identity, status.fpga_programming
    live = ep.live_timestamp
    unknown = h.HEALTH_CHECK_UNKNOWN
    if identity.abi == 0x20000:
        require(ep.live_timestamp_quality == h.MEASUREMENT_UNAVAILABLE and
                live.quality == h.MEASUREMENT_UNAVAILABLE and not live.samples and
                not any(live.HasField(name) for name in FEATURE_FIELDS + ("advancing", "delta_ticks")) and
                not live.identity_bracket_verified,
                "ABI 2.0 must not advertise native register observations")
        return unknown
    require(identity.abi in (0x20001, 0x20002), "unsupported platform ABI")
    require(ep.HasField("live_timestamp") and live.message and
            ep.live_timestamp_quality == live.quality, "missing or inconsistent observation quality")
    require(live.maximum_attempts_per_sample == 3 and live.maximum_acquisition_ms == 100,
            "unexpected acquisition limits")
    require(live.quality in (h.MEASUREMENT_GOOD, h.MEASUREMENT_UNAVAILABLE,
                            h.MEASUREMENT_STALE, h.MEASUREMENT_ERROR), "unknown quality")
    require(len(live.samples) <= 6, "unbounded attempts")
    if live.quality != h.MEASUREMENT_GOOD:
        require(not live.HasField("advancing") and not live.HasField("delta_ticks") and
                all(not sample.HasField("timestamp_ticks") and sample.quality != h.MEASUREMENT_GOOD
                    for sample in live.samples), "failed observation contains usable values")
        return unknown

    require(all(live.HasField(name) for name in FEATURE_FIELDS) and
            live.feature_abi == live.feature_abi_after == 0x54530100 and
            8 <= live.timeout_cycles == live.timeout_cycles_after <= 1048576,
            "feature identity or mailbox budget changed/missing")
    start, end = live.acquisition_started_monotonic_ns, live.observed_monotonic_ns
    require(0 < start <= end and end - start <= 100_000_000, "invalid acquisition interval")
    selected, index, attempt, last = [], 0, 1, start
    for sample in live.samples:
        require(index < 2 and sample.sample_index == index and sample.attempt_index == attempt <= 3,
                "incorrect attempt order")
        require(all(sample.HasField(name) for name in RAW_FIELDS), "incomplete raw sample")
        require(last <= sample.acquisition_started_monotonic_ns <= sample.observed_monotonic_ns <= end,
                "out-of-order sample times")
        last = sample.observed_monotonic_ns
        coherent = (sample.sequence_first == (sample.sequence_before + 1) & 0xffffffff and
                    sample.sequence_first == sample.sequence_after and
                    sample.request_status_raw == sample.status_raw)
        if sample.quality != h.MEASUREMENT_GOOD:
            require(sample.quality == h.MEASUREMENT_ERROR and not coherent and
                    not sample.HasField("timestamp_ticks"), "retry is not a discarded sequence/status conflict")
            attempt += 1
            continue
        require(coherent and sample.status_raw in (0x11, 0x13) and sample.HasField("timestamp_ticks"),
                "unqualified sample marked usable")
        source = h.NATIVE_TIMESTAMP_LOCAL_COUNTER if sample.status_raw == 0x11 else h.NATIVE_TIMESTAMP_EXTERNAL_PDTS
        require(sample.source == source and sample.timestamp_ticks == (sample.high_raw << 32) | sample.low_raw,
                "decoded sample disagrees with raw words")
        selected.append(sample)
        index, attempt = index + 1, 1
    require(len(selected) == 2 and selected[0].source == selected[1].source,
            "missing or mixed-source pair")
    delta = (selected[1].timestamp_ticks - selected[0].timestamp_ticks) & 0xffffffffffffffff
    advancing = 0 < delta < 1 << 63
    require(live.HasField("delta_ticks") and live.delta_ticks == delta and
            live.HasField("advancing") and live.advancing == advancing, "incorrect progress calculation")

    def fresh(quality, observed):
        return quality == h.MEASUREMENT_GOOD and 0 < observed <= now and now - observed <= 5_000_000_000

    external = bool(ep.endpoint_clock_control_raw & 4)
    source = h.NATIVE_TIMESTAMP_EXTERNAL_PDTS if external else h.NATIVE_TIMESTAMP_LOCAL_COUNTER
    qualified = (live.identity_bracket_verified and ep.endpoint_clock_selected == external and
                 selected[0].source == source and
                 fresh(identity.quality, identity.observed_monotonic_ns) and
                 identity.HasField("matches_admitted_profile") and identity.matches_admitted_profile and
                 fresh(ep.observation_quality, ep.observed_monotonic_ns) and fresh(live.quality, end) and
                 0 < identity.acquisition_started_monotonic_ns <= ep.observed_monotonic_ns <= start <= end <=
                 programming.acquisition_started_monotonic_ns <= programming.configuration_observed_monotonic_ns <=
                 identity.observed_monotonic_ns)
    return unknown if not qualified else h.HEALTH_CHECK_PASS if advancing else h.HEALTH_CHECK_FAIL
