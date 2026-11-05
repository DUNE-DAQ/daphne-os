#!/usr/bin/env python3
import zmq
import sys
import argparse
from identity_cli import add_identity_argument
from protobuf_loader import load_protobuf_modules

high_pb2, _ = load_protobuf_modules()

def main(ip="10.73.137.161", port=40001, identity=None):
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    if identity is not None:
        socket.setsockopt(zmq.IDENTITY, identity.encode("utf-8"))
    socket.connect(f"tcp://{ip}:{port}")
    print(f"[CLIENT] Connected to tcp://{ip}:{port}")

    # Build ControlEnvelope
    req = high_pb2.ControlEnvelope()
    req.version = 2
    req.command = "get_endpoint_status"

    # Send request
    socket.send(req.SerializeToString())
    print("[CLIENT] Request sent, waiting for reply...")

    # Receive reply
    reply_bytes = socket.recv()
    reply = high_pb2.ControlEnvelope()
    reply.ParseFromString(reply_bytes)

    print("[CLIENT] Reply received:")
    print(f"  success = {reply.success}")
    print(f"  message = {reply.message}")

    if reply.HasField("endpoint_status"):
        print("  Endpoint state:", reply.endpoint_status.state)
        print("  PLL locked:", reply.endpoint_status.pll_locked)
        print("  Clock frequency:", reply.endpoint_status.clk_freq_hz)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read endpoint status.")
    parser.add_argument("ip", nargs="?", default="10.73.137.161")
    parser.add_argument("port", nargs="?", type=int, default=40001)
    add_identity_argument(parser, default=None)
    args = parser.parse_args()
    main(args.ip, args.port, args.identity)
