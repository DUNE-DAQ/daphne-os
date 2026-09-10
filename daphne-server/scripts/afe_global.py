"""Independent I283-I288 wire checks; no RPC, hardware access or private output."""

SOURCE = "FPGA:0x80000000,0x9400000C;sequential-read-only"
FIELDS = ("power_state_bit", "reset_asserted", "busy_afe0", "busy_afe12", "busy_afe34", "bias_enabled")


def require(ok, reason="Invalid AFE global observation"):
    if not ok:
        raise RuntimeError(reason)


def check_afe_global(status, high, now_monotonic_ns, *, required=True):
    if not status.HasField("afe_global"):
        require(not required, "Server did not provide AFE global readback")
        return None
    r = status.afe_global
    require(r.quality in (high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_GOOD,
                          high.MEASUREMENT_STALE, high.MEASUREMENT_ERROR))
    if r.quality != high.MEASUREMENT_GOOD:
        require(not any(r.HasField(key) for key in FIELDS), "Failed AFE observation retained decoded values")
        require(not required, "AFE global readback is unavailable, stale or failed")
        return {"available": False, "quality": high.MeasurementQuality.Name(r.quality)}
    require(status.success and r.source == SOURCE and r.message and r.maximum_acquisition_ms == 100)
    require(all(r.HasField(key) for key in ("global_control_raw", "bias_enable_raw") + FIELDS))
    require(not r.global_control_raw & ~31 and not r.bias_enable_raw & ~1)
    expected = (bool(r.global_control_raw & 2), bool(r.global_control_raw & 1),
                bool(r.global_control_raw & 4), bool(r.global_control_raw & 8),
                bool(r.global_control_raw & 16), bool(r.bias_enable_raw & 1))
    require(tuple(getattr(r, key) for key in FIELDS) == expected, "AFE flags disagree with raw register bits")
    require(r.identity_bracket_verified and status.HasField("gateware_identity") and status.HasField("fpga_programming"))
    i, p = status.gateware_identity, status.fpga_programming
    require(i.quality == high.MEASUREMENT_GOOD and i.magic == 0x44415048 and
            i.abi in (0x20000, 0x20001, 0x20002) and i.variant in (1, 2) and
            not i.build_id & 0xf0000000 and i.HasField("matches_admitted_profile") and i.matches_admitted_profile)
    require(p.manager_quality == high.MEASUREMENT_GOOD and p.manager_state == "operating" and
            not p.HasField("manager_error_raw") and p.configuration_quality == high.MEASUREMENT_GOOD and
            p.HasField("configuration_status_raw") and not p.configuration_status_raw & 0x28438001 and
            p.configuration_status_raw & 0x78f0 == 0x78f0)
    require(0 < i.acquisition_started_monotonic_ns <= r.acquisition_started_monotonic_ns <=
            r.observed_monotonic_ns <= p.acquisition_started_monotonic_ns <=
            p.manager_observed_monotonic_ns <= p.configuration_observed_monotonic_ns <=
            i.observed_monotonic_ns <= now_monotonic_ns, "AFE observation is outside the admission bracket")
    require(r.observed_monotonic_ns - r.acquisition_started_monotonic_ns <= 100_000_000 and
            now_monotonic_ns - r.observed_monotonic_ns <= 5_000_000_000, "AFE observation is stale")
    return {"available": True, "quality": "MEASUREMENT_GOOD",
            "global_control_raw": f"0x{r.global_control_raw:08x}",
            "bias_enable_raw": f"0x{r.bias_enable_raw:08x}",
            **dict(zip(FIELDS, expected)),
            "acquisition_started_monotonic_ns": r.acquisition_started_monotonic_ns,
            "observed_monotonic_ns": r.observed_monotonic_ns,
            "scope": "sequential FPGA register samples; not bias voltage, physical power, busy history or a health verdict"}
