"""Independent checks of ABI 2.2 receive-parser history; no I/O or writes.

A nonzero history is not a current failure. Zero is not proof of error-free
operation since boot: the common platform-reset epoch is not observed.
"""

RAW_FIELDS = ("sequence_before", "request_status_raw", "sequence_first", "status_raw",
              "count_raw", "detail_raw", "sequence_after")
FEATURE_FIELDS = ("feature_abi", "feature_abi_after", "timeout_cycles", "timeout_cycles_after")
DECODED_FIELDS = ("count", "reasons_seen", "saturated", "overflowed", "receiver_reset")
REASONS = ("async_checksum", "async_length", "sync_length", "comma_in_sync", "buffer_unavailable")


def require(ok, reason):
    if not ok:
        raise RuntimeError("Parser history: " + reason)


def check_history(status, h, now):
    """Validate wire evidence; return a redacted history report, never a health verdict.

Failed/partial observations retain their raw evidence in the input protobuf.
Only fresh, coherently decoded, identity-bracketed counts reach this report.
"""
    ep, identity, programming = status.endpoint, status.gateware_identity, status.fpga_programming
    live = ep.protocol_errors
    require(live.quality in (h.MEASUREMENT_GOOD, h.MEASUREMENT_UNAVAILABLE,
                            h.MEASUREMENT_STALE, h.MEASUREMENT_ERROR), "unknown quality")
    unavailable = {"available": False, "quality": h.MeasurementQuality.Name(live.quality),
                   "reset_epoch_known": False}
    if identity.abi in (0x20000, 0x20001):
        require(live.quality == h.MEASUREMENT_UNAVAILABLE and not live.attempts and
                not any(live.HasField(name) for name in FEATURE_FIELDS + DECODED_FIELDS) and
                not live.identity_bracket_verified and not live.reset_epoch_known and
                not live.counter_width_bits and not live.counted_scope and not live.lifetime,
                "older ABI must not advertise protocol register observations")
        return dict(unavailable, reason="Not implemented by this platform ABI; no diagnostic probes")
    require(identity.abi == 0x20002, "unsupported platform ABI")
    require(ep.HasField("protocol_errors") and live.message, "missing observation")
    require(live.maximum_attempts == 3 and live.maximum_acquisition_ms == 100 and len(live.attempts) <= 3,
            "unexpected acquisition limits")
    require(live.counter_width_bits == 32 and live.counted_scope == h.PROTOCOL_ERROR_RX_PARSER_EPISODES and
            live.lifetime == h.PROTOCOL_ERROR_PLATFORM_RESET and not live.reset_epoch_known,
            "unsupported counter scope/lifetime or invented reset epoch")
    if live.quality != h.MEASUREMENT_GOOD:
        require(not any(live.HasField(name) for name in DECODED_FIELDS) and
                all(a.quality in (h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_STALE, h.MEASUREMENT_ERROR)
                    for a in live.attempts), "failed observation contains usable values")
        return dict(unavailable, reason="History unavailable; inspect retained raw evidence")

    require(all(live.HasField(name) for name in FEATURE_FIELDS + DECODED_FIELDS) and
            live.feature_abi == live.feature_abi_after == 0x50450100 and
            8 <= live.timeout_cycles == live.timeout_cycles_after <= 1048576,
            "feature metadata changed/missing or decoded field absent")
    start, end = live.acquisition_started_monotonic_ns, live.observed_monotonic_ns
    require(0 < start <= end and end - start <= 100_000_000 and live.attempts,
            "invalid acquisition interval or empty history")
    last = start
    for index, attempt in enumerate(live.attempts, 1):
        require(attempt.attempt_index == index and all(attempt.HasField(name) for name in RAW_FIELDS),
                "incorrect attempt order or incomplete raw words")
        require(last <= attempt.acquisition_started_monotonic_ns <= attempt.observed_monotonic_ns <= end,
                "out-of-order attempt times")
        last = attempt.observed_monotonic_ns
        coherent = (attempt.sequence_first == (attempt.sequence_before + 1) & 0xffffffff and
                    attempt.sequence_first == attempt.sequence_after and
                    attempt.request_status_raw == attempt.status_raw)
        if index < len(live.attempts):
            require(attempt.quality == h.MEASUREMENT_ERROR and not coherent,
                    "retry is not a discarded sequence/status conflict")
            continue
        require(attempt.quality == h.MEASUREMENT_GOOD and coherent and attempt.status_raw == 0x11,
                "unqualified final snapshot marked usable")
        count, detail = attempt.count_raw, attempt.detail_raw
        require(not detail & ~0xff and (count == 0) == (detail & 31 == 0) and
                bool(detail & 32) == (count == 0xffffffff) and (not detail & 64 or detail & 32),
                "inconsistent raw count/reasons/saturation")
        require(live.count == count and live.reasons_seen == detail & 31 and
                live.saturated == bool(detail & 32) and live.overflowed == bool(detail & 64) and
                live.receiver_reset == bool(detail & 128), "decoded history disagrees with raw words")

    def fresh(quality, observed):
        return quality == h.MEASUREMENT_GOOD and 0 < observed <= now and now - observed <= 5_000_000_000

    qualified = (live.identity_bracket_verified and identity.magic == 0x44415048 and
                 identity.variant in (1, 2) and not identity.build_id & 0xf0000000 and
                 identity.HasField("matches_admitted_profile") and identity.matches_admitted_profile and
                 fresh(identity.quality, identity.observed_monotonic_ns) and
                 fresh(ep.observation_quality, ep.observed_monotonic_ns) and fresh(live.quality, end) and
                 fresh(programming.manager_quality, programming.manager_observed_monotonic_ns) and
                 programming.manager_state == "operating" and not programming.HasField("manager_error_raw") and
                 fresh(programming.configuration_quality, programming.configuration_observed_monotonic_ns) and
                 programming.HasField("configuration_status_raw") and
                 not programming.configuration_status_raw & 0x28438001 and
                 programming.configuration_status_raw & 0x78f0 == 0x78f0 and
                 0 < identity.acquisition_started_monotonic_ns <= ep.observed_monotonic_ns <= start <= end <=
                 programming.acquisition_started_monotonic_ns <= programming.manager_observed_monotonic_ns <=
                 programming.configuration_observed_monotonic_ns <= identity.observed_monotonic_ns)
    if not qualified:
        return dict(unavailable, reason="History lacks fresh admission/programming context")
    return {"available": True, "quality": h.MeasurementQuality.Name(live.quality),
            "count": live.count, "reasons_seen": [name for bit, name in enumerate(REASONS) if live.reasons_seen & 1 << bit],
            "reasons_mask": live.reasons_seen, "saturated": live.saturated, "overflowed": live.overflowed,
            "receiver_reset_at_capture": live.receiver_reset, "counter_width_bits": 32,
            "scope": "RX-parser error episodes", "lifetime": "common platform reset, not parser recovery",
            "reset_epoch_known": False, "observed_monotonic_ns": end,
            "meaning": "Historical episodes, not current failure or all protocol errors; not since-boot evidence"}
