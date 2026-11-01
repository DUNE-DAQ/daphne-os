"""CLI cancellation requests must not interrupt an in-flight RPC."""
from pathlib import Path
import signal
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from dma_cli_signals import DmaCliSignals


class DmaCliSignalTests(unittest.TestCase):
    def test_signal_is_deferred_and_previous_handlers_are_restored(self):
        signals = [getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP")
                   if hasattr(signal, name)]
        previous = {signum: signal.getsignal(signum) for signum in signals}
        with DmaCliSignals() as guard:
            self.assertFalse(guard.stop_requested())
            guard.check()
            # Invoke the installed OS handler without sending a process signal
            # (Windows and POSIX differ in process-signal delivery).
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            self.assertTrue(guard.stop_requested())
            with self.assertRaisesRegex(RuntimeError, "SIGTERM"):
                guard.check()
        self.assertEqual({signum: signal.getsignal(signum) for signum in signals}, previous)

    def test_disabled_guard_preserves_spybuffer_signal_behavior(self):
        previous = signal.getsignal(signal.SIGINT)
        with DmaCliSignals(enabled=False) as guard:
            self.assertEqual(signal.getsignal(signal.SIGINT), previous)
            self.assertFalse(guard.stop_requested())

    def test_exception_restores_signal_handlers(self):
        previous = signal.getsignal(signal.SIGTERM)
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with DmaCliSignals():
                raise RuntimeError("test failure")
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)


if __name__ == "__main__":
    unittest.main()
