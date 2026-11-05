"""Shared ZeroMQ identity option, including propagation through scan runners."""

import argparse
import os


def identity_value(value):
    encoded = value.encode("utf-8")
    if not 1 <= len(encoded) <= 255 or encoded[0] == 0:
        raise argparse.ArgumentTypeError(
            "identity must contain 1..255 UTF-8 bytes and cannot start with NUL"
        )
    return value


def add_identity_argument(parser, default=None):
    inherited = os.environ.get("DAPHNE_IDENTITY")
    if inherited is not None:
        default = f"{inherited}-{os.getpid()}"
    parser.add_argument(
        "--identity", "-identity", type=identity_value, default=default,
        help="ZeroMQ identity (scan runners propagate a base through "
             "DAPHNE_IDENTITY and each child appends its process ID)",
    )
