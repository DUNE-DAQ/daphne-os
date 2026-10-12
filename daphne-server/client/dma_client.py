"""Finite and triggered DMA jobs: negotiation, strict fragments, explicit ACK.

RPC is injected so CLI and Qt use the same decoder and validation. ACK belongs
to the caller, after processing and any requested file writes have succeeded.
"""
import time
import numpy as np
from dma_persistent_client import PersistentClientMixin


class DmaClient(PersistentClientMixin):
    def __init__(self, pb, rpc, stop_checker=lambda: False, progress_callback=None):
        self.pb, self.rpc, self.stop_checker = pb, rpc, stop_checker
        self.capabilities = None
        self.job_id = None
        self.progress_callback = progress_callback
        self._last_keepalive = time.monotonic()

    def _call(self, name, request, response_class):
        p = self.pb
        response = self.rpc(getattr(p, "MT2_" + name + "_REQ"), request,
                            getattr(p, "MT2_" + name + "_RESP"), response_class)
        if not response.success:
            raise RuntimeError(response.message or "DMA RPC rejected (old schema/server?)")
        return response

    def probe(self, trigger_source=None, capture_mode="finite", pretrigger=0):
        p = self.pb
        query = p.AcquisitionCapabilitiesRequest()
        if hasattr(query, 'maximum_protocol_revision'):
            query.maximum_protocol_revision = 3 if capture_mode == 'persistent' else 2
        c = self._call("ACQUISITION_CAPABILITIES", query,
                       p.AcquisitionCapabilitiesResponse)
        if (c.protocol_revision not in (1, 2, 3) or c.backend != p.ACQUISITION_DMA or
                p.ACQUISITION_DMA not in c.available_backends or not c.dma_available or
                c.gateware_abi != 0x20000 or not (c.gateware_capabilities & 16) or
                c.sample_format != 1 or not c.maximum_job_bytes or
                not c.maximum_waveforms or not (1 <= c.maximum_fragment_bytes <= 1048576)):
            raise RuntimeError("BACKEND_MISMATCH: compatible raw DMA server/driver unavailable")
        self.capabilities = c
        self._check_trigger(trigger_source, capture_mode, pretrigger)
        return c

    def _check_trigger(self, trigger_source, capture_mode="finite", pretrigger=0):
        if capture_mode not in ('finite', 'triggered', 'persistent') or pretrigger < 0:
            raise ValueError('Invalid DMA capture mode/pretrigger')
        if capture_mode == 'finite' and pretrigger:
            raise ValueError('Finite DMA requires P=0')
        sources = self.capabilities.dma_trigger_sources
        if capture_mode == 'persistent':
            c, p = self.capabilities, self.pb
            if (c.protocol_revision != 3 or not hasattr(p, 'DMA_CAPTURE_PERSISTENT') or
                    not hasattr(p, 'DmaEventId') or c.session_abi != 1 or (c.session_features & 31) != 31 or
                    not (c.gateware_capabilities & 128) or not c.maximum_target_waveforms or
                    not 2 <= c.session_slots <= 32 or c.session_slots & (c.session_slots - 1) or
                    not 1 <= c.maximum_staged_events <= 16):
                raise RuntimeError('PERSISTENT_UNAVAILABLE: revision 3/ABI 1/features 31 required; no fallback')
            mode = next((m for m in c.capture_modes if m.mode == p.DMA_CAPTURE_PERSISTENT), None)
            if mode is None or not mode.available or (pretrigger and not mode.pretrigger_available):
                raise RuntimeError('PERSISTENT_UNAVAILABLE: driver/provider support unavailable')
            sources = mode.trigger_sources
        if capture_mode == 'triggered':
            p = self.pb
            if (self.capabilities.protocol_revision != 2 or not hasattr(p, 'DMA_CAPTURE_TRIGGERED') or
                    not hasattr(p, 'DmaWaveformMetadata') or not (self.capabilities.gateware_capabilities & 64)):
                raise RuntimeError('TRIGGERED_UNAVAILABLE: updated bindings/server/firmware required; no finite fallback')
            mode = next((m for m in self.capabilities.capture_modes if m.mode == p.DMA_CAPTURE_TRIGGERED), None)
            if mode is None or not mode.available or (pretrigger and not mode.pretrigger_available):
                raise RuntimeError('TRIGGERED_UNAVAILABLE: driver/provider or pretrigger support unavailable')
            sources = mode.trigger_sources
        if trigger_source is not None:
            if capture_mode == 'finite' and trigger_source != 'software':
                raise RuntimeError('TRIGGER_UNSUPPORTED: finite DMA requires software trigger')
            if trigger_source not in ('software', 'external', 'timing'):
                raise RuntimeError('TRIGGER_UNSUPPORTED: DMA supports software/external/timing')
            source = getattr(self.pb, "DMA_TRIGGER_" + trigger_source.upper())
            if source not in sources:
                raise RuntimeError(f"TRIGGER_UNSUPPORTED: DMA {capture_mode}/{trigger_source} is unavailable")

    def batch_limit(self, channels, samples, capture_mode="finite", pretrigger=0):
        if (not channels or len(set(channels)) != len(channels) or
                any(ch < 0 or ch > 39 for ch in channels) or samples <= 0):
            raise ValueError("DMA requires unique channels 0..39 and positive L")
        c = self.capabilities or self.probe()
        self._check_trigger(None, capture_mode, pretrigger)
        if pretrigger >= samples:
            raise ValueError('DMA requires 0 <= P < L')
        if capture_mode in ('triggered', 'persistent'):
            d = c.period_ticks
            if not d or d & (d - 1) or not 8 <= d <= 1048576 or not c.maximum_ring_bytes:
                raise RuntimeError('Invalid triggered ring capabilities')
            ring = ((samples + 3 * d - 1) // d) * d
            if capture_mode == 'persistent':
                ring = max(ring, 8*d)
            sizes = [sum(ch // 16 == r for ch in channels) for r in range(3)]
            allocation = sum(((2*k*ring + 128 + 4095)//4096)*4096 for k in sizes if k)
            if ring // d > 512 or allocation > c.maximum_ring_bytes or any(2*k*ring > 256<<20 for k in sizes):
                raise ValueError('DMA waveform exceeds advertised triggered ring budget')
        result = min(c.maximum_waveforms, c.maximum_job_bytes // (2 * len(channels) * samples))
        if capture_mode == 'persistent':
            if allocation > c.session_pool_bytes or any(2*k*ring > c.session_route_bytes for k in sizes):
                raise ValueError('DMA waveform exceeds persistent pool budget')
            result = min(c.maximum_staged_events, c.maximum_job_bytes // (2 * len(channels) * samples))
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
        self._last_keepalive = time.monotonic()

    def _renew_lease(self):
        lease = getattr(self.capabilities, 'lease_ms', 0) or 30000
        if time.monotonic() - self._last_keepalive >= min(5., lease / 3000):
            self.keepalive()

    def cancel(self):
        if self.job_id is None:
            return
        r = self._control(self.pb.DMA_CANCEL)
        cleanup = getattr(self.capabilities, 'cleanup_timeout_ms', 0) or 10000
        deadline = time.monotonic() + cleanup / 1000 + 5
        while r.state == self.pb.DMA_JOB_RUNNING and time.monotonic() < deadline:
            time.sleep(.02)
            r = self._call("DMA_STATUS", self.pb.DmaJobRequest(job_id=self.job_id), self.pb.DmaJobResponse)
        if r.state == self.pb.DMA_JOB_RUNNING:
            raise RuntimeError("DMA cancellation still pending; do not unload the overlay")
        if 'QUARANTINED' in r.message:
            raise RuntimeError(r.message + '; DMA idle could not be proven; keep the overlay loaded')
        if r.state != self.pb.DMA_JOB_IDLE:
            self._control(self.pb.DMA_CANCEL)
        self.job_id = None

    def _wait(self, initial, timeout_s):
        if not initial.job_id or initial.backend != self.pb.ACQUISITION_DMA:
            raise RuntimeError("Invalid DMA job identity/backend")
        self.job_id = initial.job_id
        self._last_keepalive = time.monotonic()
        deadline = time.monotonic() + timeout_s
        r = initial
        delay = .002
        previous_progress = None
        while r.state == self.pb.DMA_JOB_RUNNING:
            self._check_stop()
            self._renew_lease()
            progress = (r.completed_waveforms, r.expected_waveforms, getattr(r, 'phase', 0))
            if self.progress_callback and progress != previous_progress:
                self.progress_callback(*progress)
                previous_progress = progress
            if time.monotonic() >= deadline:
                raise TimeoutError("DMA job deadline expired")
            r = self._call("DMA_STATUS", self.pb.DmaJobRequest(job_id=self.job_id), self.pb.DmaJobResponse)
            if r.job_id != self.job_id or r.backend != self.pb.ACQUISITION_DMA:
                raise RuntimeError("DMA status identity/backend changed")
            if getattr(initial, 'force_acquisition', False) and not getattr(r, 'force_acquisition', False):
                raise RuntimeError('DMA force acquisition acknowledgement changed')
            if getattr(initial, 'contract_version', 0) == 2 and any(
                    getattr(r, field) != getattr(initial, field) for field in
                    ('contract_version', 'capture_mode', 'trigger_source', 'pretrigger_samples', 'job_timeout_ms')):
                raise RuntimeError('DMA accepted contract changed during acquisition')
            if r.state == self.pb.DMA_JOB_RUNNING:
                time.sleep(delay)
                delay = min(.02, delay * 2)
        if r.state != self.pb.DMA_JOB_READY:
            raise RuntimeError(r.message or "DMA job failed/cancelled")
        return r

    def _check_stop(self):
        if self.stop_checker():
            raise InterruptedError("DMA acquisition stopped")

    def _trigger_metadata(self, reply, samples, pretrigger, source):
        p = self.pb
        if not reply.HasField('waveform_metadata'):
            raise RuntimeError('Missing triggered waveform metadata')
        m = reply.waveform_metadata
        d = self.capabilities.period_ticks
        ring = ((samples + 3*d - 1)//d)*d
        end = m.window_first + samples
        if (m.contract_version != 1 or m.capture_mode != p.DMA_CAPTURE_TRIGGERED or
                m.trigger_source != source or m.samples != samples or m.pretrigger_samples != pretrigger or
                m.trigger_index < pretrigger or m.window_first != m.trigger_index - pretrigger or
                m.period_ticks != d or m.ring_ticks != ring or m.stream_ticks % d or
                not end <= m.stream_ticks < end + d or m.stream_ticks - m.window_first > ring):
            raise RuntimeError('Triggered waveform metadata/window mismatch')
        return m

    def acquire(self, channels, samples, waveforms=1, trigger_source="software", timeout_ms=10000,
                capture_mode="finite", pretrigger=0, job_timeout_ms=0, force_acq=False):
        """Return ADC14 [N, requested channels, L], metadata; caller then ACKs."""
        p = self.pb
        if capture_mode == 'persistent':
            raise ValueError('Persistent acquisition requires start_session/read_batch/ack_batch/finish_session')
        if self.job_id is not None:
            raise RuntimeError("ACK or cancel the previous DMA job first")
        if self.capabilities is None:
            self.probe()
        self._check_trigger(trigger_source, capture_mode, pretrigger)
        self._check_force_acq(force_acq)
        if not 1 <= waveforms <= self.batch_limit(channels, samples, capture_mode, pretrigger):
            raise ValueError("DMA N exceeds batch budget")
        if not 10 <= timeout_ms <= 600000:
            raise ValueError("DMA capture timeout must be 10..600000 ms")
        if job_timeout_ms < 0:
            raise ValueError('DMA total job timeout must be nonnegative')
        self._check_stop()
        try:
            request = p.DmaAcquireRequest(backend=p.ACQUISITION_DMA,
                channels=channels, samples=samples, waveforms=waveforms,
                trigger_source=getattr(p, "DMA_TRIGGER_" + trigger_source.upper()), timeout_ms=timeout_ms)
            if force_acq:
                request.force_acquisition = True
            if self.capabilities.protocol_revision == 2:
                request.capture_mode = p.DMA_CAPTURE_TRIGGERED if capture_mode == 'triggered' else p.DMA_CAPTURE_FINITE
                request.pretrigger_samples = pretrigger
                request.job_timeout_ms = job_timeout_ms
            elif job_timeout_ms:
                raise ValueError('A total job deadline requires protocol revision 2')
            initial = self._call("DMA_ACQUIRE", request, p.DmaJobResponse)
            self.job_id = initial.job_id
            if force_acq and not initial.force_acquisition:
                raise RuntimeError('Server did not accept force acquisition')
            if self.capabilities.protocol_revision == 2:
                if (initial.contract_version != 2 or initial.capture_mode != request.capture_mode or
                        initial.trigger_source != request.trigger_source or initial.pretrigger_samples != pretrigger):
                    raise RuntimeError('DMA accepted mode/source/P mismatch; no finite fallback')
            cleanup = getattr(self.capabilities, 'cleanup_timeout_ms', 0) or 10000
            total = job_timeout_ms or (waveforms * (timeout_ms + cleanup) + 5000)
            if self.capabilities.protocol_revision == 2 and initial.job_timeout_ms != total:
                raise RuntimeError('DMA total job deadline mismatch')
            ready = self._wait(initial, (total + cleanup) / 1000)
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
                trigger_metadata = None
                trigger_bytes = None
                for route in active:
                    tick = 0
                    expected_channels = routes[route]
                    while tick < samples:
                        self._check_stop()
                        self._renew_lease()
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
                            reply.final_job != final_job or
                            reply.independently_software_triggered != (trigger_source == 'software')):
                            raise RuntimeError("DMA fragment metadata/length/sequence mismatch")
                        if capture_mode == 'triggered':
                            m = self._trigger_metadata(reply, samples, pretrigger, request.trigger_source)
                            encoded = m.SerializeToString()
                            if trigger_bytes is not None and trigger_bytes != encoded:
                                raise RuntimeError('Triggered metadata changed within a waveform')
                            trigger_bytes = encoded
                            trigger_metadata = {field.name: getattr(m, field.name) for field in m.DESCRIPTOR.fields if field.number <= 13}
                        elif hasattr(reply, 'waveform_metadata') and reply.HasField('waveform_metadata'):
                            raise RuntimeError('Unexpected triggered metadata in finite acquisition')
                        ts = (reply.timestamp_valid, reply.timestamp)
                        if timestamp is not None and ts != timestamp:
                            raise RuntimeError("DMA timestamp changed within a waveform")
                        timestamp = ts
                        data = np.frombuffer(reply.raw16_le, dtype="<u2").reshape(count, len(expected_channels))
                        if np.any(data & 3):
                            raise RuntimeError("DMA ADC14 framing error: nonzero padding bits")
                        for i, ch in enumerate(expected_channels):
                            raw[w, order[ch], tick:end] = data[:, i]
                        tick = end
                        sequence += 1
                item = {"waveform": w, "timestamp_valid": timestamp[0],
                        "hardware_timestamp": timestamp[1] if timestamp[0] else None}
                if trigger_metadata is not None:
                    item['trigger'] = trigger_metadata
                metadata.append(item)
            adc14 = np.right_shift(raw, 2)
            np.bitwise_and(adc14, 0x3fff, out=adc14)
            # ADC_OUTPUT_FORMAT=0 is two's complement, not offset binary.
            # Normalize to the same unsigned ADC14 convention as spybuffer.
            np.bitwise_xor(adc14, 0x2000, out=adc14)
            return adc14, {"backend": "dma", "wire_format": "raw16_le", "saved_format": "adc14_u16_le",
                "wire_encoding": "adc14_twos_complement_left_shift_2", "saved_encoding": "offset_binary",
                "build_id": c.gateware_build_id, "job_id": self.job_id, "channels": list(channels), "samples": samples,
                "waveforms": metadata, "trigger_source": trigger_source,
                "capture_mode": capture_mode, "independent_software_triggers": trigger_source == 'software',
                "continuous": False, "pretrigger_samples": pretrigger,
                "timestamp_reference": "first_stream_tick" if capture_mode == 'triggered' else "finite_capture"}
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
        if getattr(request, 'skip_ramp_verification', False) and not getattr(self.capabilities, 'skip_ramp_verification_supported', False):
            raise RuntimeError('Server does not support skipping final ramp verification')
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

    def _check_force_acq(self, force_acq):
        if force_acq and not getattr(self.capabilities, 'force_acquisition_supported', False):
            raise RuntimeError('Server does not support force acquisition')


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
