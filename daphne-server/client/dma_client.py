"""Finite raw-DMA jobs: capability negotiation, strict fragments, explicit ACK.

RPC is injected so CLI and Qt use the same decoder and validation. ACK belongs
to the caller, after processing and any requested file writes have succeeded.
"""
import time
import numpy as np


class DmaClient:
    def __init__(self, pb, rpc, stop_checker=lambda: False):
        self.pb, self.rpc, self.stop_checker = pb, rpc, stop_checker
        self.capabilities = None
        self.job_id = None

    def _call(self, name, request, response_class):
        p = self.pb
        response = self.rpc(getattr(p, "MT2_" + name + "_REQ"), request,
                            getattr(p, "MT2_" + name + "_RESP"), response_class)
        if not response.success:
            raise RuntimeError(response.message or "DMA RPC rejected (old schema/server?)")
        return response

    def probe(self, trigger_source=None):
        p = self.pb
        c = self._call("ACQUISITION_CAPABILITIES", p.AcquisitionCapabilitiesRequest(),
                       p.AcquisitionCapabilitiesResponse)
        if (c.protocol_revision != 1 or c.backend != p.ACQUISITION_DMA or
                p.ACQUISITION_DMA not in c.available_backends or not c.dma_available or
                c.gateware_abi != 0x20000 or not (c.gateware_capabilities & 16) or
                c.sample_format != 1 or not c.maximum_job_bytes or
                not c.maximum_waveforms or not (1 <= c.maximum_fragment_bytes <= 1048576)):
            raise RuntimeError("BACKEND_MISMATCH: compatible raw DMA server/driver unavailable")
        if trigger_source is not None:
            source = getattr(p, "DMA_TRIGGER_" + trigger_source.upper())
            if source not in c.dma_trigger_sources:
                raise RuntimeError(f"TRIGGER_UNSUPPORTED: DMA {trigger_source} requires trigger firmware; use software")
        self.capabilities = c
        return c

    def batch_limit(self, channels, samples):
        if (not channels or len(set(channels)) != len(channels) or
                any(ch < 0 or ch > 39 for ch in channels) or samples <= 0):
            raise ValueError("DMA requires unique channels 0..39 and positive L")
        c = self.capabilities or self.probe()
        result = min(c.maximum_waveforms, c.maximum_job_bytes // (2 * len(channels) * samples))
        if samples > c.maximum_samples or result < 1:
            raise ValueError("DMA waveform exceeds the advertised sample/byte budget")
        return result

    def _control(self, action):
        if self.job_id is None:
            return None
        return self._call("DMA_CONTROL", self.pb.DmaControlRequest(job_id=self.job_id, action=action),
                          self.pb.DmaJobResponse)

    def acknowledge(self):
        self._control(self.pb.DMA_ACK)
        self.job_id = None

    def keepalive(self):
        self._control(self.pb.DMA_KEEPALIVE)

    def cancel(self):
        if self.job_id is None:
            return
        r = self._control(self.pb.DMA_CANCEL)
        deadline = time.monotonic() + 5
        while r.state == self.pb.DMA_JOB_RUNNING and time.monotonic() < deadline:
            time.sleep(.02)
            r = self._call("DMA_STATUS", self.pb.DmaJobRequest(job_id=self.job_id), self.pb.DmaJobResponse)
        if r.state == self.pb.DMA_JOB_RUNNING:
            raise RuntimeError("DMA cancellation still pending; do not unload the overlay")
        if r.state != self.pb.DMA_JOB_IDLE:
            self._control(self.pb.DMA_CANCEL)
        self.job_id = None

    def _wait(self, initial, timeout_s):
        if not initial.job_id or initial.backend != self.pb.ACQUISITION_DMA:
            raise RuntimeError("Invalid DMA job identity/backend")
        self.job_id = initial.job_id
        deadline = time.monotonic() + timeout_s
        r = initial
        while r.state == self.pb.DMA_JOB_RUNNING:
            self._check_stop()
            if time.monotonic() >= deadline:
                raise TimeoutError("DMA job deadline expired")
            time.sleep(.02)
            r = self._call("DMA_STATUS", self.pb.DmaJobRequest(job_id=self.job_id), self.pb.DmaJobResponse)
            if r.job_id != self.job_id or r.backend != self.pb.ACQUISITION_DMA:
                raise RuntimeError("DMA status identity/backend changed")
        if r.state != self.pb.DMA_JOB_READY:
            raise RuntimeError(r.message or "DMA job failed/cancelled")
        return r

    def _check_stop(self):
        if self.stop_checker():
            raise InterruptedError("DMA acquisition stopped")

    def acquire(self, channels, samples, waveforms=1, trigger_source="software", timeout_ms=10000):
        """Return ADC14 [N, requested channels, L], metadata; caller then ACKs."""
        p = self.pb
        if self.job_id is not None:
            raise RuntimeError("ACK or cancel the previous DMA job first")
        self.probe(trigger_source)
        if not 1 <= waveforms <= self.batch_limit(channels, samples):
            raise ValueError("DMA N exceeds batch budget")
        if not 10 <= timeout_ms <= 600000:
            raise ValueError("DMA capture timeout must be 10..600000 ms")
        self._check_stop()
        try:
            initial = self._call("DMA_ACQUIRE", p.DmaAcquireRequest(backend=p.ACQUISITION_DMA,
                channels=channels, samples=samples, waveforms=waveforms,
                trigger_source=getattr(p, "DMA_TRIGGER_" + trigger_source.upper()), timeout_ms=timeout_ms), p.DmaJobResponse)
            ready = self._wait(initial, waveforms * (timeout_ms / 1000 + 2) + 5)
            if ready.completed_waveforms != waveforms or ready.expected_waveforms != waveforms:
                raise RuntimeError("DMA waveform count mismatch")
            raw = np.empty((waveforms, len(channels), samples), dtype=np.uint16)
            order = {ch: i for i, ch in enumerate(channels)}
            routes = {r: sorted(ch for ch in channels if ch // 16 == r) for r in range(3)}
            active = [r for r in routes if routes[r]]
            sequence = 0
            metadata = []
            c = self.capabilities
            for w in range(waveforms):
                timestamp = None
                for route in active:
                    tick = 0
                    expected_channels = routes[route]
                    while tick < samples:
                        self._check_stop()
                        reply = self._call("DMA_READ", p.DmaReadRequest(job_id=self.job_id, waveform=w,
                            route=route, tick_offset=tick, maximum_bytes=c.maximum_fragment_bytes), p.DmaReadResponse)
                        count = reply.tick_count
                        end = tick + count
                        final_route = end == samples
                        final_wave = final_route and route == active[-1]
                        final_job = final_wave and w == waveforms - 1
                        if (reply.backend != p.ACQUISITION_DMA or reply.job_id != self.job_id or
                            reply.waveform != w or reply.route != route or reply.sequence != sequence or
                            list(reply.channels) != expected_channels or reply.samples != samples or
                            reply.expected_waveforms != waveforms or reply.tick_offset != tick or
                            not count or end > samples or reply.sample_format != 1 or
                            reply.gateware_build_id != c.gateware_build_id or
                            len(reply.raw16_le) != count * 2 * len(expected_channels) or
                            len(reply.raw16_le) > c.maximum_fragment_bytes or
                            reply.final_route != final_route or reply.final_waveform != final_wave or
                            reply.final_job != final_job or not reply.independently_software_triggered):
                            raise RuntimeError("DMA fragment metadata/length/sequence mismatch")
                        ts = (reply.timestamp_valid, reply.timestamp)
                        if timestamp is not None and ts != timestamp:
                            raise RuntimeError("DMA timestamp changed within a waveform")
                        timestamp = ts
                        data = np.frombuffer(reply.raw16_le, dtype="<u2").reshape(count, len(expected_channels))
                        for i, ch in enumerate(expected_channels):
                            raw[w, order[ch], tick:end] = data[:, i]
                        tick = end
                        sequence += 1
                metadata.append({"waveform": w, "timestamp_valid": timestamp[0],
                                 "hardware_timestamp": timestamp[1] if timestamp[0] else None})
            adc14 = np.right_shift(raw, 2)
            np.bitwise_and(adc14, 0x3fff, out=adc14)
            return adc14, {"backend": "dma", "wire_format": "raw16_le", "saved_format": "adc14_u16_le",
                "build_id": c.gateware_build_id, "channels": list(channels), "samples": samples,
                "waveforms": metadata, "trigger_source": trigger_source,
                "independent_software_triggers": True, "continuous": False, "pretrigger_samples": 0}
        except BaseException as error:
            try:
                self.cancel()
            except Exception as cleanup:
                raise RuntimeError(f"{error}; DMA cleanup unconfirmed: {cleanup}; keep the overlay loaded until idle is proven") from error
            raise

    def scan(self, request):
        p = self.pb
        if self.job_id is not None:
            raise RuntimeError("ACK or cancel the previous DMA job first")
        self.probe()
        try:
            initial = self._call("DMA_SCAN", request, p.DmaJobResponse)
            ready = self._wait(initial, (request.timeout_ms or 600000) / 1000 + 5)
            if not ready.HasField("scan_result") or ready.scan_result.backend != p.ACQUISITION_DMA:
                raise RuntimeError("Missing DMA scan result")
            return ready.scan_result
        except BaseException as error:
            try:
                self.cancel()
            except Exception as cleanup:
                raise RuntimeError(f"{error}; DMA cleanup unconfirmed: {cleanup}; keep the overlay loaded until idle is proven") from error
            raise


def link_rpc(pb, link, route):
    """Adapt osc.V2Link without interrupting an in-flight reply correlation."""
    def rpc(request_type, request, response_type, response_class):
        _, envelope, _ = link.request(request_type, request.SerializeToString(), route=route)
        if envelope.version != 2 or envelope.type != response_type:
            raise RuntimeError("DMA EnvelopeV2 response type/version mismatch")
        result = response_class()
        result.ParseFromString(envelope.payload)
        return result
    return rpc
