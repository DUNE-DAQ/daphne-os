#!/usr/bin/env python3
"""Read-only qualification of FPGA-health reporting, not a declaration of health.

Requests private network details for comparison but outputs only named check
results, public FPGA words and observation times. No hardware writes or scans;
ABI 2.1/2.2 reads trigger diagnostic captures, not acquisition changes.
"""
import argparse
import json
import math
from pathlib import Path
import sys
from native_timestamp import check_progress
from protocol_errors import check_history
from management_link import health_state as management_health
from afe_global import reset_health_state


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def check_status(s, h, expected_build, variant, require_bench=False, expected_abi=0x20000):
    require(s.success and s.HasField("fpga_health") and s.HasField("fpga_programming"),
            "Missing/failed FPGA status collection")
    health, p, i, ep = s.fpga_health, s.fpga_programming, s.gateware_identity, s.endpoint
    require(health.evaluated_monotonic_ns and health.maximum_observation_age_ms == 5000
            and health.scope and health.message, "Missing health scope/freshness policy")
    now = health.evaluated_monotonic_ns

    def fresh(quality, observed):
        return quality == h.MEASUREMENT_GOOD and 0 < observed <= now and now - observed <= 5_000_000_000

    require(expected_abi in (0x20000, 0x20001, 0x20002) and
            (i.magic, i.abi, i.variant, i.build_id) == (0x44415048, expected_abi, variant, expected_build)
            and i.quality == h.MEASUREMENT_GOOD and i.HasField("matches_admitted_profile")
            and i.matches_admitted_profile, "Unexpected gateware/admission")
    require(0 < i.acquisition_started_monotonic_ns <= ep.observed_monotonic_ns
            <= p.acquisition_started_monotonic_ns <= p.configuration_observed_monotonic_ns
            <= i.observed_monotonic_ns <= now, "Incorrect FPGA observation bracketing")
    require(p.HasField("configuration_status_raw") and p.configuration_quality == h.MEASUREMENT_GOOD
            and p.manager_quality == h.MEASUREMENT_GOOD and p.source and p.message,
            "Configuration STAT is not a qualified observation")
    require(ep.observation_quality == h.MEASUREMENT_GOOD, "Timing not measured")
    control, locks, endpoint_control, state = (ep.endpoint_clock_control_raw, ep.endpoint_clock_status_raw,
                                             ep.endpoint_control_raw, ep.endpoint_status_raw)
    timing_ready = bool(control & 4 and locks & 3 == 3 and not control & 3
                        and not endpoint_control & 0x10000 and state & 15 == 8 and state & 16)
    require(ep.ready == timing_ready, "Timing-ready summary disagrees with raw registers")
    require(not ep.last_timing_timestamp and not ep.last_timing_timestamp_observed_ns,
            "Legacy timestamp fields must remain unset")
    unknown, passed, failed = h.HEALTH_CHECK_UNKNOWN, h.HEALTH_CHECK_PASS, h.HEALTH_CHECK_FAIL

    def outcome(available, ok):
        return unknown if not available else passed if ok else failed

    raw = p.configuration_status_raw
    config_fresh = fresh(p.configuration_quality, p.configuration_observed_monotonic_ns)
    timing_fresh = fresh(ep.observation_quality, ep.observed_monotonic_ns)
    runtime, network, binding = s.server_state, s.board_identity.management, s.board_identity
    temperatures = [t for t in s.temperatures if t.name == "Temp_PL"]
    t = temperatures[0] if len(temperatures) == 1 else None
    thermal = (t is not None and t.valid and math.isfinite(t.temperature_c)
               and fresh(t.quality, t.observed_monotonic_ns)
               and h.TEMPERATURE_ALARM_GOOD <= t.alarm.state <= h.TEMPERATURE_ALARM_CRITICAL)
    expected = {
        "kernel_programming": outcome(fresh(p.manager_quality, p.manager_observed_monotonic_ns)
                                      and p.manager_state != "unknown", p.manager_state == "operating" and not p.HasField("manager_error_raw")),
        "configuration_error_flags": outcome(config_fresh, not raw & 0x28438001),
        "configuration_startup": outcome(config_fresh, raw & 0x78f0 == 0x78f0),
        "fabric_clock_locks": outcome(config_fresh, bool(raw & 4)),
        "admitted_gateware": outcome(fresh(i.quality, i.observed_monotonic_ns), i.matches_admitted_profile),
        "timing_clock_locks": outcome(timing_fresh, locks & 3 == 3),
        "timing_resets_released": outcome(timing_fresh, not control & 3 and not endpoint_control & 0x10000),
        "afe_reset_released": reset_health_state(s, h, now),
        "external_timing_ready": outcome(timing_fresh, timing_ready),
        "front_end_configuration": outcome(runtime.success and fresh(h.MEASUREMENT_GOOD, runtime.observed_monotonic_ns),
                                           runtime.applied_configuration_valid and not runtime.configuration_in_progress
                                           and bool(runtime.applied_configuration_hash)),
        "pl_die_temperature": outcome(thermal, thermal and t.alarm.state == h.TEMPERATURE_ALARM_GOOD),
        "management_interface": management_health(network, h, now),
        "management_identity": outcome(fresh(h.MEASUREMENT_GOOD, binding.observed_monotonic_ns)
                                       and binding.binding_state in (h.IDENTITY_BINDING_MATCH, h.IDENTITY_BINDING_MISMATCH),
                                       binding.binding_state == h.IDENTITY_BINDING_MATCH),
        "live_timestamp_progress": check_progress(s, h, now), "hermes_data_path": unknown, "external_reset_epoch": unknown,
    }
    require(len(health.checks) == len(expected) and {c.name for c in health.checks} == set(expected),
            "Missing/duplicate/unexpected health checks")
    for c in health.checks:
        require(c.state == expected[c.name] and c.message, "Incorrect health evaluation: " + c.name)
        if c.name == "afe_reset_released":
            require(c.observed_monotonic_ns == s.afe_global.observed_monotonic_ns,
                    "AFE reset check timestamp differs from its source observation")
    overall = (h.FPGA_HEALTH_NOT_READY if failed in expected.values() else
               h.FPGA_HEALTH_UNKNOWN if unknown in expected.values() else h.FPGA_HEALTH_OBSERVED_OK)
    require(health.state == overall, "Overall health ignores failed/unknown evidence")
    if require_bench:
        require(expected["external_timing_ready"] == failed and all(
            value == (failed if name == "external_timing_ready" else unknown if name in
                      ("hermes_data_path", "external_reset_epoch") or
                      (name == "live_timestamp_progress" and expected_abi == 0x20000) else passed)
            for name, value in expected.items()), "Board differs from expected qualified local-clock bench profile")
    return {"state": h.FpgaHealthState.Name(overall), "configuration_stat": f"0x{raw:08x}",
            "build_id": f"0x{i.build_id:08x}", "abi": f"0x{i.abi:08x}", "observed_monotonic_ns": now,
            "checks": {name: h.HealthCheckState.Name(value) for name, value in expected.items()},
            "protocol_errors": check_history(s, h, now)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--expected-abi", type=lambda value: int(value, 0), choices=(0x20000, 0x20001, 0x20002), default=0x20000,
                        help="Exact platform ABI word; default 0x20000 preserves deployed qualification")
    parser.add_argument("--mode", choices=("self-trigger", "full-stream"), required=True)
    parser.add_argument("--require-bench-profile", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import daphneV3_high_level_confs_pb2 as h
    import zmq
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 10000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect(args.endpoint)
    sequence = 0
    report = {"success": False, "meaning": "reporting verification, not a healthy-board declaration", "runs": []}

    def call(kind, body, cls):
        nonlocal sequence
        sequence += 1
        envelope = h.ControlEnvelopeV2(version=2, dir=h.DIR_REQUEST, type=kind,
                                        task_id=47, msg_id=sequence, payload=body.SerializeToString())
        socket.send(envelope.SerializeToString())
        reply = h.ControlEnvelopeV2.FromString(socket.recv())
        require(reply.version == 2 and reply.dir == h.DIR_RESPONSE and reply.type == kind + 1
                and reply.task_id == 47 and reply.correl_id == sequence and not reply.transport_error,
                "Wrong envelope or failed transport")
        return cls.FromString(reply.payload)

    try:
        before = call(h.MT2_READ_SERVER_STATE_REQ, h.ReadServerStateRequest(), h.ServerState)
        for _ in range(2):
            status = call(h.MT2_READ_SYSTEM_STATUS_REQ, h.ReadSystemStatusRequest(include_identity_details=True), h.SystemStatusSnapshot)
            require(not status.sfps, "Unexpected SFP collection")
            report["runs"].append(check_status(status, h, args.expected_build_id,
                1 if args.mode == "self-trigger" else 2, args.require_bench_profile, args.expected_abi))
        after = call(h.MT2_READ_SERVER_STATE_REQ, h.ReadServerStateRequest(), h.ServerState)
        require(before.success and after.success and before.instance_id == after.instance_id and before.boot_id == after.boot_id
                and before.applied_configuration_hash == after.applied_configuration_hash
                and before.applied_configuration_valid == after.applied_configuration_valid,
                "Status reads changed process or FE evidence")
        require(report["runs"][1]["observed_monotonic_ns"] > report["runs"][0]["observed_monotonic_ns"], "Non-advancing observation time")
        report["success"] = True
    except Exception as error:
        report["error"] = str(error) if isinstance(error, RuntimeError) else "Verification failed; private details suppressed"
    finally:
        report["requests_checked"] = sequence
        print(json.dumps(report, indent=2))
        socket.close()
        context.term()
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
