"""Defer CLI signals until an RPC completes, so DMA cleanup keeps correlation."""
import signal
import threading


class DmaCliSignals:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.received = None
        self._previous = {}

    def __enter__(self):
        if self.enabled and threading.current_thread() is threading.main_thread():
            for name in ("SIGINT", "SIGTERM", "SIGHUP"):
                signum = getattr(signal, name, None)
                if signum is not None:
                    self._previous[signum] = signal.signal(signum, self._receive)
        return self

    def _receive(self, signum, frame):
        self.received = signum

    def stop_requested(self):
        return self.received is not None

    def check(self):
        if self.stop_requested():
            raise RuntimeError(f"DMA cancelled by {signal.Signals(self.received).name}")

    def __exit__(self, exc_type, exc_value, traceback):
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)
