#!/usr/bin/env python3
"""Check actual C++ collector/protobuf bytes with the independent Python reader.

The probe uses scripted MMIO, not /dev/mem or hardware. Only the outer context
is synthesized here; this proves software wire compatibility, not FPGA readout.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--proto-dir", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    from test_protocol_errors import protocol_fixture, check_history, h

    expected = {"abi20": None, "abi21": None, "zero": 0, "events": 7, "saturated": 0xffffffff,
                "overflowed": 0xffffffff, "reset": 0, "timeout": None, "busy": None, "retry": 8,
                "exhausted": None, "read_failure": None, "stale": None}
    result = subprocess.run([str(args.probe.resolve()), "--emit-fixtures"], check=True,
                            capture_output=True, text=True, timeout=30)
    observed = {}
    for line in result.stdout.splitlines():
        label, abi, encoded = line.split()
        if label not in expected or label in observed:
            raise RuntimeError("Unexpected or duplicate wire fixture")
        s = protocol_fixture()
        s.gateware_identity.abi = int(abi, 16)
        live = s.endpoint.protocol_errors
        live.ParseFromString(bytes.fromhex(encoded))
        # Explicit synthetic context; the emitted collector never claims its
        # own outer FPGA bracket or an observed reset epoch.
        if live.identity_bracket_verified or live.reset_epoch_known:
            raise RuntimeError("Collector invented outer context")
        if expected[label] is not None:
            live.identity_bracket_verified = True
            start, end = live.acquisition_started_monotonic_ns, live.observed_monotonic_ns
            s.gateware_identity.acquisition_started_monotonic_ns = start - 2
            s.endpoint.observed_monotonic_ns = start - 1
            s.fpga_programming.acquisition_started_monotonic_ns = end + 1
            s.fpga_programming.manager_observed_monotonic_ns = end + 2
            s.fpga_programming.configuration_observed_monotonic_ns = end + 3
            s.gateware_identity.observed_monotonic_ns = end + 4
        report = check_history(s, h, max(live.observed_monotonic_ns + 5, 200))
        if report["available"] != (expected[label] is not None) or report.get("count") != expected[label]:
            raise RuntimeError("C++/Python history interpretation disagrees")
        observed[label] = report["quality"]
    if set(observed) != set(expected):
        raise RuntimeError("Missing wire fixtures")
    print(json.dumps({"success": True, "cases": len(observed), "qualities": observed,
                      "scope": "Scripted C++ MMIO collector -> protobuf -> Python; synthetic outer context, no hardware"}, indent=2))


if __name__ == "__main__":
    main()
