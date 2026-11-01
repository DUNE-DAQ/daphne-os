import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class _Again(Exception):
    pass


class _ZmqError(Exception):
    pass


# v2_client only needs these symbols when a socket is injected.
sys.modules["zmq"] = types.SimpleNamespace(
    Again=_Again,
    ZMQError=_ZmqError,
    DEALER=1,
    IDENTITY=2,
    LINGER=3,
    RCVTIMEO=4,
    SNDTIMEO=5,
    RCVMORE=6,
)

CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from v2_client import V2Client  # noqa: E402


class _Envelope:
    def __init__(self):
        self.version = 0
        self.dir = 0
        self.type = 0
        self.payload = b""
        self.task_id = 0
        self.msg_id = 0
        self.correl_id = 0
        self.route = ""
        self.timestamp_ns = 0

    def SerializeToString(self):
        fields = vars(self).copy()
        fields["payload"] = self.payload.hex()
        return json.dumps(fields).encode()

    def ParseFromString(self, payload):
        fields = json.loads(payload.decode())
        fields["payload"] = bytes.fromhex(fields["payload"])
        for name, value in fields.items():
            setattr(self, name, value)


class _Proto:
    DIR_REQUEST = 0
    DIR_RESPONSE = 1
    ControlEnvelopeV2 = _Envelope


class _Socket:
    def __init__(self, response_type=207, correl_delta=0):
        self.response_type = response_type
        self.correl_delta = correl_delta
        self.request = None
        self.reply = None

    def send(self, payload):
        self.request = _Envelope()
        self.request.ParseFromString(payload)
        response = _Envelope()
        response.version = 2
        response.dir = _Proto.DIR_RESPONSE
        response.type = self.response_type
        response.payload = b"reply"
        response.correl_id = self.request.msg_id + self.correl_delta
        self.reply = response.SerializeToString()

    def recv(self):
        return self.reply

    def poll(self, timeout):
        return 1

    def getsockopt(self, option):
        return 0


class V2ClientTests(unittest.TestCase):
    def test_timeout_then_cancel_consumes_only_known_late_reply(self):
        socket = _LateSocket()
        client = V2Client(_Proto, "unused", 0, timeout_ms=10000, socket=socket)
        with self.assertRaisesRegex(TimeoutError, r"request_type=342, msg_id=\d+, timeout_ms=10000"):
            client.request(342, b"read", 343)
        reply = client.request(344, b"cancel", 345)
        self.assertEqual(reply.type, 345)
        self.assertEqual(reply.correl_id, socket.requests[-1].msg_id)
        self.assertEqual([request.type for request in socket.requests], [342, 344])
        self.assertEqual(socket.received_ids, [request.msg_id for request in socket.requests])

    def test_late_replies_do_not_restart_receive_deadline(self):
        clock = types.SimpleNamespace(now=0.0)
        socket = _LateSocket(timeouts=2)
        socket.after_recv = lambda: setattr(clock, "now", clock.now + .006)
        client = V2Client(_Proto, "unused", 0, timeout_ms=10, socket=socket)
        with patch("v2_client.time.monotonic", side_effect=lambda: clock.now):
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    client.request(342, b"read", 343)
            with self.assertRaises(TimeoutError):
                client.request(344, b"cancel", 345)
        self.assertEqual(len(socket.requests), 3)
        self.assertEqual(len(socket.received_ids), 2)
        self.assertLess(socket.poll_timeouts[-1], socket.poll_timeouts[-2])

    def test_send_timeout_is_distinguished_from_receive_timeout(self):
        socket = _Socket()
        client = V2Client(_Proto, "unused", 0, socket=socket)
        with patch.object(socket, "send", side_effect=_Again()):
            with self.assertRaisesRegex(TimeoutError, "Timed out sending request"):
                client.request(206, b"request", 207)
        self.assertFalse(client._expired_replies)

    def test_request_populates_and_checks_v2_envelope(self):
        socket = _Socket()
        client = V2Client(
            _Proto,
            "unused",
            0,
            route="mezz/4",
            socket=socket,
        )
        response = client.request(206, b"request", 207)
        self.assertEqual(response.payload, b"reply")
        self.assertEqual(socket.request.version, 2)
        self.assertEqual(socket.request.dir, _Proto.DIR_REQUEST)
        self.assertEqual(socket.request.type, 206)
        self.assertEqual(socket.request.payload, b"request")
        self.assertEqual(socket.request.route, "mezz/4")
        self.assertNotEqual(socket.request.msg_id, 0)

    def test_request_rejects_wrong_response_type(self):
        client = V2Client(_Proto, "unused", 0, socket=_Socket(999))
        with self.assertRaisesRegex(RuntimeError, "Unexpected response type"):
            client.request(206, b"request", 207)

    def test_request_rejects_bad_correlation(self):
        client = V2Client(
            _Proto,
            "unused",
            0,
            socket=_Socket(correl_delta=1),
        )
        with self.assertRaisesRegex(RuntimeError, "correlation mismatch"):
            client.request(206, b"request", 207)


class _LateSocket(_Socket):
    """Deliver timed-out replies only after the next request has been sent."""
    def __init__(self, timeouts=1):
        super().__init__()
        self.timeouts = timeouts
        self.requests = []
        self.delayed = []
        self.ready = []
        self.received_ids = []
        self.poll_timeouts = []
        self.after_recv = lambda: None

    def send(self, payload):
        super().send(payload)
        self.requests.append(self.request)
        response = _Envelope()
        response.ParseFromString(self.reply)
        response.type = self.request.type + 1
        if len(self.requests) <= self.timeouts:
            self.delayed.append(response)
        else:
            self.ready.extend(self.delayed + [response])
            self.delayed.clear()

    def poll(self, timeout):
        self.poll_timeouts.append(timeout)
        return bool(self.ready)

    def recv(self):
        response = self.ready.pop(0)
        self.received_ids.append(response.correl_id)
        self.after_recv()
        return response.SerializeToString()


if __name__ == "__main__":
    unittest.main()
