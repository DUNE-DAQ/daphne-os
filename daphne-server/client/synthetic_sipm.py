#!/usr/bin/env python3
"""Configure or read the optional AFE0 CH0 synthetic SiPM generator."""

import argparse
from identity_cli import add_identity_argument
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json
import sys

import zmq

from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


def amplitude_to_q8(text):
    """Quantize an ADC-unit amplitude to U14.8, with ties rounded up."""
    try:
        amplitude = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("amplitude must be a decimal number") from exc
    if not amplitude.is_finite() or not Decimal(1) <= amplitude <= Decimal(10000):
        raise argparse.ArgumentTypeError("amplitude must be finite and in 1..10000 ADC units")
    with localcontext() as context:
        context.prec = max(28, len(amplitude.as_tuple().digits) + 8)
        return int((amplitude * 256).to_integral_value(rounding=ROUND_HALF_UP))


def _snapshot(pb, response):
    if not response.success:
        raise RuntimeError(response.message or "synthetic SiPM RPC failed (empty response or server error)")
    amplitude_q8 = int(response.amplitude_q8)
    models = {pb.SYNTHETIC_SIPM_FBK: "fbk", pb.SYNTHETIC_SIPM_HPK: "hpk"}
    if not 256 <= amplitude_q8 <= 2560000 or response.model not in models:
        raise RuntimeError("invalid synthetic SiPM configuration returned by server")
    raw = amplitude_q8 | (int(response.model) << 22) | (int(response.enable) << 23)
    if response.raw_register != raw:
        raise RuntimeError("synthetic SiPM fields disagree with raw register readback")
    return {
        "afe": 0,
        "channel": 0,
        "amplitude": amplitude_q8 / 256,
        "amplitude_q8": amplitude_q8,
        "model": models[response.model],
        "enable": bool(response.enable),
        "raw_register": f"0x{raw:08X}",
    }


def read_configuration(pb, client):
    response = client.rpc(
        pb.MT2_READ_SYNTHETIC_SIPM_CONFIG_REQ,
        pb.ReadSyntheticSipmConfigRequest(),
        pb.MT2_READ_SYNTHETIC_SIPM_CONFIG_RESP,
        pb.SyntheticSipmConfigResponse,
    )
    return _snapshot(pb, response)


def configure_generator(pb, client, amplitude_q8, model, enable):
    if not 256 <= amplitude_q8 <= 2560000:
        raise ValueError("amplitude_q8 out of range (256..2560000)")
    models = {"fbk": pb.SYNTHETIC_SIPM_FBK, "hpk": pb.SYNTHETIC_SIPM_HPK}
    if model not in models:
        raise ValueError("model must be fbk or hpk")
    response = client.rpc(
        pb.MT2_CONFIGURE_SYNTHETIC_SIPM_REQ,
        pb.ConfigureSyntheticSipmRequest(
            amplitude_q8=amplitude_q8, model=models[model], enable=enable
        ),
        pb.MT2_CONFIGURE_SYNTHETIC_SIPM_RESP,
        pb.SyntheticSipmConfigResponse,
    )
    snapshot = _snapshot(pb, response)
    if (snapshot["amplitude_q8"], snapshot["model"], snapshot["enable"]) != (
        amplitude_q8, model, enable
    ):
        raise RuntimeError("synthetic SiPM readback differs from requested configuration")
    return snapshot


def disable_generator(pb, client):
    current = read_configuration(pb, client)
    return configure_generator(pb, client, current["amplitude_q8"], current["model"], False)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Configure the AFE0 CH0 synthetic generator. Configuration clears filter history."
    )
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--timeout-ms", type=int, default=5000)
    add_identity_argument(parser, default='synthetic-sipm-client')
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure", help="Write all three fields and verify readback.")
    configure.add_argument(
        "--amplitude", type=amplitude_to_q8, required=True,
        help="Excitation in ADC units, 1..10000; quantized to 1/256 (ties up)."
    )
    configure.add_argument("--model", choices=("fbk", "hpk"), required=True)
    state = configure.add_mutually_exclusive_group(required=True)
    state.add_argument("--enable", dest="enable", action="store_true")
    state.add_argument("--disable", dest="enable", action="store_false")
    commands.add_parser("read", help="Read the AXI configuration register without writing.")
    commands.add_parser("disable", help="Read current amplitude/model and reapply with ENABLE=0.")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or args.timeout_ms <= 0:
        parser.error("port must be in 1..65535 and timeout-ms must be positive")
    try:
        pb, _ = load_protobuf_modules(require_synthetic_sipm=True)
        with V2Client(
            pb, args.ip, args.port, route=args.route,
            timeout_ms=args.timeout_ms, identity=args.identity
        ) as client:
            if args.command == "read":
                snapshot = read_configuration(pb, client)
            elif args.command == "disable":
                snapshot = disable_generator(pb, client)
            else:
                snapshot = configure_generator(pb, client, args.amplitude, args.model, args.enable)
    except (ValueError, RuntimeError, TimeoutError, zmq.ZMQError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
