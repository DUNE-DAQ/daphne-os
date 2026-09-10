"""Independent fan wire validation. GOOD means register reporting, not fan health."""

SOURCE = "FPGA:0x94000000,0x94000004,0x94000008;sequential-read-only"
DECODED = ("pwm_command", "tach_pulses_capped", "tach_at_counter_limit")
UNQUALIFIED = ("present", "pwm_enabled", "duty_cycle_percent", "tach_rpm",
               "running", "stalled", "stall_count", "control_mode")


def require(ok, reason="Invalid fan register observation"):
    if not ok:
        raise RuntimeError(reason)


def check_fans(status, high, now_monotonic_ns, *, required=True):
    if not status.fans:
        require(not required, "Server did not provide fan register observations")
        return None
    require(len(status.fans) == 2, "Expected two fan tach channels sharing one command")
    a, b = status.fans
    for key in ("quality", "acquisition_started_monotonic_ns", "observed_monotonic_ns"):
        require(getattr(a, key) == getattr(b, key), "Fan records disagree on shared acquisition")
    for key in ("pwm_control_raw", "pwm_control_after_raw"):
        require(a.HasField(key) == b.HasField(key) and getattr(a, key) == getattr(b, key),
                "Fan records disagree on shared acquisition")
    reports = []
    for index, r in enumerate(status.fans):
        require(r.name == "fan" + str(index) and r.source == SOURCE and r.message and r.maximum_acquisition_ms == 100)
        require(r.quality in (high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_GOOD,
                              high.MEASUREMENT_ERROR, high.MEASUREMENT_STALE))
        require(not r.tach_valid and not r.source_sample_time_known and
                not any(r.HasField(key) for key in UNQUALIFIED), "Unqualified physical fan claims")
        if r.quality != high.MEASUREMENT_GOOD:
            require(not any(r.HasField(key) for key in DECODED), "Failed fan read retained decoded values")
            require(not required, "Fan register observation is unavailable, failed or stale")
            reports.append({"name": r.name, "available": False, "quality": high.MeasurementQuality.Name(r.quality)})
            continue
        require(status.success and all(r.HasField(key) for key in
                ("pwm_control_raw", "pwm_control_after_raw", "tachometer_raw") + DECODED))
        require(0 <= r.pwm_control_raw <= 255 and r.pwm_command == r.pwm_control_raw == r.pwm_control_after_raw)
        require(not r.tachometer_raw & ~0xf80 and r.tach_pulses_capped == r.tachometer_raw >> 7 and
                r.tach_at_counter_limit == (r.tach_pulses_capped == 31))
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
                i.observed_monotonic_ns <= now_monotonic_ns, "Fan reads are outside the admission bracket")
        require(r.observed_monotonic_ns - r.acquisition_started_monotonic_ns <= 100_000_000 and
                now_monotonic_ns - r.observed_monotonic_ns <= 5_000_000_000, "Fan register readback is stale")
        reports.append({"name": r.name, "available": True, "quality": "MEASUREMENT_GOOD",
                        "pwm_command": r.pwm_command, "tachometer_raw": f"0x{r.tachometer_raw:08x}",
                        "tach_pulses_capped": r.tach_pulses_capped, "tach_at_counter_limit": r.tach_at_counter_limit,
                        "acquisition_started_monotonic_ns": r.acquisition_started_monotonic_ns,
                        "observed_monotonic_ns": r.observed_monotonic_ns,
                        "scope": "host register observation; not physical RPM, presence, stall or FPGA sample time"})
    return reports
