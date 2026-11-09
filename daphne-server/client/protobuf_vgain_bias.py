#!/usr/bin/env python3
"""Sequence AFE bias and per-channel TRIM for a VGAIN scan."""

import argparse
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

import zmq

from identity_cli import add_identity_argument
from protobuf_configure_vbias_trim import (
    BIAS_DAC_CODES_PER_VOLT,
    bias_control_volts_to_dac,
    bias_volts_to_dac,
    checked_dac_code,
    direct_dac_code,
    require_success,
)
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


# Nominal TRIM gain is 1 mV/code (trimGain=False). Validate the operating
# window with margin for the board's actual DAC and monitor calibration.
BIAS_MV_PER_CODE = 1000.0 / BIAS_DAC_CODES_PER_VOLT
MONITOR_TOLERANCE_MV = 100
MONITOR_POLL_S = 0.25
UNMONITORED_SETTLING_S = 0.75


def trim_step(max_trim_mv):
    return math.ceil(max_trim_mv / BIAS_MV_PER_CODE)


def require_window(window, low_mv, high_mv):
    if window is None:
        raise ValueError("nonzero TRIM requires --bias-safe-window-mv MIN MAX")
    if not window[0] <= low_mv <= high_mv <= window[1]:
        raise ValueError(
            f"effective bias range {low_mv:.0f}..{high_mv:.0f} mV "
            f"is outside the configured window {window[0]}..{window[1]} mV"
        )


def validate_point(window, bias_dac, max_trim_mv):
    if max_trim_mv:
        nominal_mv = bias_dac * BIAS_MV_PER_CODE
        transition_drop = trim_step(max_trim_mv) * BIAS_MV_PER_CODE
        require_window(
            window,
            nominal_mv - transition_drop - max_trim_mv - 2 * MONITOR_TOLERANCE_MV,
            nominal_mv + MONITOR_TOLERANCE_MV,
        )


class AfeBiasSequence:
    def __init__(self, client, high, low, afe, window, state_file, allow_unmonitored_bias=False):
        self.client = client
        self.high = high
        self.low = low
        self.afe = afe
        self.window = window
        self.state_file = state_file
        self.allow_unmonitored_bias = allow_unmonitored_bias
        self.cancelled = False

    def cancel(self, signum, frame):
        self.cancelled = True

    def rpc(self, operation, message, **fields):
        if self.cancelled:
            raise RuntimeError("bias/TRIM sequence interrupted")
        response = self.client.rpc(
            getattr(self.high, f"MT2_{operation}_REQ"),
            getattr(self.low, message)(**fields),
            getattr(self.high, f"MT2_{operation}_RESP"),
            getattr(self.low, f"{message}_response"),
        )
        require_success(operation, response)
        if self.cancelled:
            raise RuntimeError("bias/TRIM sequence interrupted")
        return response

    def bias_setpoint(self):
        response = self.rpc("READ_AFE_BIAS_SET", "cmd_readAFEBiasSet", afeBlock=self.afe)
        if response.afeBlock != self.afe:
            raise RuntimeError("bias setpoint readback returned the wrong AFE")
        return checked_dac_code(response.biasValue, "readback bias")

    def write_bias(self, code):
        response = self.rpc("WRITE_AFE_BIAS_SET", "cmd_writeAFEBiasSet", afeBlock=self.afe, biasValue=code)
        if response.afeBlock != self.afe or response.biasValue != code:
            raise RuntimeError("bias write returned an unexpected AFE or DAC code")

    def read_trims(self):
        response = self.rpc("READ_TRIM_ALL_AFE", "cmd_readTrim_allAFE", afeBlock=self.afe)
        if response.afeBlock != self.afe or len(response.trimValues) != 8:
            raise RuntimeError("TRIM readback did not return all eight channels of the selected AFE")
        return [checked_dac_code(value, "readback TRIM") for value in response.trimValues]

    def verify_bias(self, code, low_mv, high_mv):
        if not self.allow_unmonitored_bias:
            return self.stable_bias(low_mv, high_mv)

        time.sleep(UNMONITORED_SETTLING_S)
        if self.bias_setpoint() != code:
            raise RuntimeError(f"bias setpoint readback did not match DAC {code}")
        nominal_mv = code * BIAS_MV_PER_CODE
        if not low_mv <= nominal_mv <= high_mv:
            raise ValueError(f"nominal bias {nominal_mv:.0f} mV is outside {low_mv:.0f}..{high_mv:.0f} mV")
        print(f"Bias DAC {code} verified by setpoint readback ({nominal_mv:.0f} mV nominal)", flush=True)
        return nominal_mv

    def stable_bias(self, low_mv, high_mv):
        deadline = time.monotonic() + self.client.timeout_ms / 1000
        samples = []
        # Space samples beyond the server's default 200 ms monitor period.
        # After a write, the target band also checks for the expected voltage change.
        while time.monotonic() < deadline:
            time.sleep(MONITOR_POLL_S)
            response = self.rpc("READ_BIAS_VOLTAGE_MONITOR", "cmd_readBiasVoltageMonitor", afeBlock=self.afe)
            if response.afeBlock != self.afe:
                raise RuntimeError("bias monitor returned the wrong AFE")
            measured = response.biasVoltageValue
            if low_mv <= measured <= high_mv:
                samples = (samples + [measured])[-3:]
                if len(samples) == 3 and max(samples) - min(samples) <= MONITOR_TOLERANCE_MV:
                    return measured
            else:
                samples.clear()
        raise RuntimeError(f"bias did not settle within {low_mv:.0f}..{high_mv:.0f} mV")

    def save_state(self, state):
        temporary = self.state_file.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.state_file)

    def clear_trims(self):
        state = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file.exists() else {}
        max_trim = max(max(self.read_trims()), state.get("max_trim", 0))
        if max_trim:
            self.prepare_trim_clear(state, max_trim)

        response = self.rpc("WRITE_TRIM_ALL_AFE", "cmd_writeTrim_allAFE",
                            afeBlock=self.afe, trimValue=0, trimGain=False)
        if response.afeBlock != self.afe or response.trimValue != 0 or any(self.read_trims()):
            raise RuntimeError("TRIM zero could not be confirmed for the entire AFE")
        self.state_file.unlink(missing_ok=True)

    def prepare_trim_clear(self, state, max_trim):
        if self.window is None:
            raise ValueError("cannot clear active TRIM without --bias-safe-window-mv MIN MAX")

        current_code = self.bias_setpoint()
        transition = state.get("transition")
        if transition is None:
            original_mv = self.verify_bias(current_code, self.window[0] + max_trim, self.window[1])
            step = trim_step(max_trim)
            target_code = current_code - step
            expected_mv = original_mv - step * BIAS_MV_PER_CODE
            low_mv = expected_mv - MONITOR_TOLERANCE_MV
            high_mv = original_mv - max_trim
            require_window(self.window, low_mv - max_trim, high_mv)
            # Bias zero is reserved for shutdown after TRIM zero is confirmed.
            if target_code <= 0:
                raise ValueError("TRIM transition would require a zero or negative bias DAC code")
            transition = {
                "original_code": current_code, "target_code": target_code,
                "low_mv": low_mv, "high_mv": high_mv,
            }
            # Record the original target before writing so a retry never subtracts twice.
            self.save_state({"max_trim": max_trim, "transition": transition})

        target_code = transition["target_code"]
        low_mv, high_mv = transition["low_mv"], transition["high_mv"]
        require_window(self.window, low_mv - max_trim, high_mv)
        if not 0 < target_code < transition["original_code"] or current_code not in (
            transition["original_code"], target_code
        ):
            raise RuntimeError("bias DAC setpoint changed during TRIM restoration")
        if current_code != target_code:
            self.write_bias(checked_dac_code(target_code, "transition bias"))
        bias_mv = self.verify_bias(target_code, low_mv, high_mv)
        evidence = "nominal" if self.allow_unmonitored_bias else "measured"
        print(f"TRIM transition confirmed at {bias_mv:.0f} mV {evidence} (bias DAC {target_code})", flush=True)

    def apply(self, bias_dac, bias_control_dac, trims):
        max_trim = max(trims.values())
        validate_point(self.window, bias_dac, max_trim)
        self.clear_trims()
        control = self.rpc("WRITE_VBIAS_CONTROL", "cmd_writeVbiasControl",
                           vBiasControlValue=bias_control_dac, enable=True)
        if control.vBiasControlValue != bias_control_dac:
            raise RuntimeError("bias-control write returned an unexpected DAC code")
        self.write_bias(bias_dac)
        if not max_trim:
            return

        nominal_mv = bias_dac * BIAS_MV_PER_CODE
        bias_mv = self.verify_bias(bias_dac, nominal_mv - MONITOR_TOLERANCE_MV,
                                   nominal_mv + MONITOR_TOLERANCE_MV)
        require_window(self.window, bias_mv - trim_step(max_trim) * BIAS_MV_PER_CODE
                       - max_trim - MONITOR_TOLERANCE_MV, bias_mv)
        # A timeout may leave a write applied. Keep the maximum of all attempted TRIMs
        # available to the cleanup process, even if the server readback is incomplete.
        self.save_state({"max_trim": max_trim})
        for channel, value in trims.items():
            if not value:
                continue
            response = self.rpc("WRITE_TRIM_CH", "cmd_writeTrim_singleChannel",
                                trimChannel=channel, trimValue=value, trimGain=False)
            if response.trimChannel != channel or response.trimValue != value:
                raise RuntimeError(f"unexpected TRIM write response for channel {channel}")
        expected = [trims.get(self.afe * 8 + index, 0) for index in range(8)]
        if self.read_trims() != expected:
            raise RuntimeError("TRIM readback does not match the requested channel map")

    def shutdown(self):
        self.clear_trims()
        self.write_bias(0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "apply", "shutdown"))
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    parser.add_argument("-route", "--route", default="mezz/0")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--afe", type=int, choices=range(5), required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--bias-safe-window-mv", type=int, nargs=2, metavar=("MIN", "MAX"))
    parser.add_argument("--allow-unmonitored-bias", action="store_true",
                        help="Use nominal voltage and DAC setpoint readback in place of the bias monitor.")
    parser.add_argument("--bias", type=float, nargs="+")
    parser.add_argument("--bias-control", type=float)
    parser.add_argument("--set-as-dac", action="store_true")
    parser.add_argument("--trim-map", nargs="+", metavar="CHANNEL:DAC")
    add_identity_argument(parser, default="vgain-bias-v2")
    args = parser.parse_args(argv)

    try:
        window = args.bias_safe_window_mv
        if window is not None and not 0 <= window[0] < window[1]:
            raise ValueError("bias window must satisfy 0 <= MIN < MAX")
        if args.action != "shutdown":
            if args.bias is None or args.bias_control is None or args.trim_map is None:
                raise ValueError("--bias, --bias-control and --trim-map are required")
            trims = {}
            for item in args.trim_map:
                channel, code = map(int, item.split(":"))
                if channel // 8 != args.afe or channel in trims:
                    raise ValueError(f"invalid or duplicate channel {channel} for AFE {args.afe}")
                trims[channel] = checked_dac_code(code, "TRIM")
            if args.set_as_dac:
                bias_codes = [direct_dac_code(value, "bias") for value in args.bias]
                bias_control = direct_dac_code(args.bias_control, "bias control")
            else:
                bias_codes = [checked_dac_code(bias_volts_to_dac(value), "bias") for value in args.bias]
                bias_control = checked_dac_code(bias_control_volts_to_dac(args.bias_control), "bias control")
            for code in bias_codes:
                validate_point(window, code, max(trims.values()))
            if args.action == "validate":
                return 0
            if len(bias_codes) != 1:
                raise ValueError("apply expects exactly one bias value")

        high, low = load_protobuf_modules()
        with V2Client(high, args.ip, args.port, route=args.route,
                      timeout_ms=args.timeout_ms, identity=args.identity) as client:
            sequence = AfeBiasSequence(client, high, low, args.afe, window, args.state_file,
                                       allow_unmonitored_bias=args.allow_unmonitored_bias)
            handlers = {}
            for name in ("SIGINT", "SIGTERM", "SIGHUP"):
                signum = getattr(signal, name, None)
                if signum is not None:
                    handlers[signum] = signal.signal(signum, sequence.cancel)
            try:
                if args.action == "apply":
                    sequence.apply(bias_codes[0], bias_control, trims)
                else:
                    sequence.shutdown()
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
    except (ValueError, OverflowError, OSError, RuntimeError, zmq.ZMQError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
