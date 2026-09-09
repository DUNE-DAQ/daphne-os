"""Run with pyzmq and generated protobuf modules on PYTHONPATH; no board needed."""
from pathlib import Path
import socket
import subprocess
import sys
import unittest


class CounterClientTests(unittest.TestCase):
    def test_timeout_is_nonzero_exit_without_fabricated_measurements(self):
        # Reserve a local TCP port that never speaks ZeroMQ, so no hardware or
        # unrelated service can accidentally receive this request.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            script = Path(__file__).resolve().parents[1] / "client" / "test_counters.py"
            result = subprocess.run(
                [sys.executable, str(script), "--ip", "127.0.0.1", "--port", str(port), "--timeout", "50"],
                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Counter measurements unavailable", result.stdout)
        self.assertNotIn("REC_CNT", result.stdout)
        self.assertNotIn("THR(28b)", result.stdout)


if __name__ == "__main__":
    unittest.main()
