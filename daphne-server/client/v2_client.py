"""Small synchronous client for the daphneServer EnvelopeV2 RPC API."""

import os
from collections import deque
import math
import random
import time

import zmq


_ID_MASK = (1 << 63) - 1


def next_ids():
    now_ns = time.time_ns()
    entropy = random.randrange(1 << 16)
    task_id = ((now_ns << 16) ^ (os.getpid() << 8) ^ entropy) & _ID_MASK
    msg_id = ((now_ns << 1) ^ entropy) & _ID_MASK
    return task_id, msg_id


class V2Client:
    def __init__(
        self,
        protobuf_module,
        ip,
        port,
        route="mezz/0",
        timeout_ms=5000,
        identity="daphne-v2-client",
        context=None,
        socket=None,
    ):
        self.pb = protobuf_module
        self.route = route
        self.timeout_ms = timeout_ms
        self._expired_replies = deque(maxlen=64)
        self._owns_socket = socket is None
        if socket is None:
            context = context or zmq.Context.instance()
            socket = context.socket(zmq.DEALER)
            socket.setsockopt(zmq.IDENTITY, identity.encode())
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
            socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
            socket.connect(f"tcp://{ip}:{port}")
        self.socket = socket

    def close(self):
        if self._owns_socket and self.socket is not None:
            self.socket.close()
        self.socket = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def request(self, request_type, payload, expected_response_type=None):
        envelope = self.pb.ControlEnvelopeV2()
        envelope.version = 2
        envelope.dir = self.pb.DIR_REQUEST
        envelope.type = request_type
        envelope.payload = payload
        envelope.task_id, envelope.msg_id = next_ids()
        envelope.timestamp_ns = time.time_ns()
        envelope.route = self.route

        sent = False
        try:
            self.socket.send(envelope.SerializeToString())
            sent = True
            deadline = (time.monotonic() + self.timeout_ms / 1000
                        if self.timeout_ms >= 0 else None)
            while True:
                remaining_ms = -1
                if deadline is not None:
                    remaining_ms = max(0, math.ceil((deadline - time.monotonic()) * 1000))
                    if not remaining_ms and self.timeout_ms > 0:
                        raise zmq.Again()
                if not self.socket.poll(timeout=remaining_ms):
                    raise zmq.Again()
                frames = [self.socket.recv()]
                while self.socket.getsockopt(zmq.RCVMORE):
                    frames.append(self.socket.recv())

                response = self.pb.ControlEnvelopeV2()
                try:
                    response.ParseFromString(frames[-1])
                except Exception as exc:
                    raise RuntimeError("Invalid EnvelopeV2 response from daphneServer") from exc

                if response.version != 2:
                    raise RuntimeError(
                        f"Unexpected response envelope version {response.version}"
                    )
                if response.dir != self.pb.DIR_RESPONSE:
                    raise RuntimeError(f"Unexpected response direction {response.dir}")
                if response.correl_id in self._expired_replies:
                    # A timed-out RPC may still complete on the server. Consume
                    # its late reply without accepting it for the next RPC or
                    # replaying a READ/ACK whose effect is already unknown.
                    self._expired_replies.remove(response.correl_id)
                    continue
                if response.correl_id != envelope.msg_id:
                    raise RuntimeError(
                        "Response correlation mismatch: "
                        f"expected {envelope.msg_id}, got {response.correl_id}"
                    )
                if (
                    expected_response_type is not None
                    and response.type != expected_response_type
                ):
                    raise RuntimeError(
                        "Unexpected response type: "
                        f"expected {expected_response_type}, got {response.type}"
                    )
                return response
        except zmq.Again as exc:
            if sent:
                self._expired_replies.append(envelope.msg_id)
            stage = "waiting for daphneServer" if sent else "sending request to daphneServer"
            raise TimeoutError(
                f"Timed out {stage}: "
                f"request_type={request_type}, msg_id={envelope.msg_id}, "
                f"timeout_ms={self.timeout_ms}"
            ) from exc

    def rpc(self, request_type, request, response_type, response_class):
        envelope = self.request(
            request_type,
            request.SerializeToString(),
            expected_response_type=response_type,
        )
        response = response_class()
        try:
            response.ParseFromString(envelope.payload)
        except Exception as exc:
            raise RuntimeError("Invalid protobuf RPC response payload") from exc
        return response
