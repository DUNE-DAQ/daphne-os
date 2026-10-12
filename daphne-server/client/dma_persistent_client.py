"""Revision 3 bounded streaming; caller ACKs only after processing/file writes."""
import time
import numpy as np

UNBOUNDED_SESSION_TARGET = (1 << 64) - 1


def id_tuple(event):
    return event.session, event.sequence, event.generation, event.slot


class PersistentClientMixin:
    def start_session(self, channels, samples, target, trigger_source='software', timeout_ms=30000,
                      pretrigger=0, job_timeout_ms=0, pressure_timeout_ms=0, force_acq=False):
        if self.job_id is not None:
            raise RuntimeError('ACK or cancel the previous job first')
        if self.capabilities is None or self.capabilities.protocol_revision != 3:
            self.probe(trigger_source, 'persistent', pretrigger)
        self._check_trigger(trigger_source, 'persistent', pretrigger)
        self._check_force_acq(force_acq)
        self.batch_limit(channels, samples, 'persistent', pretrigger)
        unbounded = target == 0
        if unbounded:
            if self.capabilities.maximum_target_waveforms != UNBOUNDED_SESSION_TARGET:
                raise RuntimeError('Unbounded session requires the full uint64 target range; no session rollover')
            target = UNBOUNDED_SESSION_TARGET
        if not 1 <= target <= self.capabilities.maximum_target_waveforms:
            raise ValueError('Persistent N outside advertised range')
        if not 10 <= timeout_ms <= 600000 or not 0 <= job_timeout_ms <= 7*24*3600*1000 or (0 < job_timeout_ms < 10):
            raise ValueError('Invalid persistent trigger/total deadline')
        if pressure_timeout_ms and not 10 <= pressure_timeout_ms <= 600000:
            raise ValueError('Invalid persistent pressure deadline')
        self._check_stop()
        p = self.pb
        request = p.DmaAcquireRequest(backend=p.ACQUISITION_DMA, channels=channels, samples=samples,
            target_waveforms=target, trigger_source=getattr(p, 'DMA_TRIGGER_' + trigger_source.upper()),
            timeout_ms=timeout_ms, capture_mode=p.DMA_CAPTURE_PERSISTENT, pretrigger_samples=pretrigger,
            protocol_revision=3, job_timeout_ms=job_timeout_ms, pressure_timeout_ms=pressure_timeout_ms)
        if force_acq:
            request.force_acquisition = True
        initial = self._call('DMA_ACQUIRE', request, p.DmaJobResponse)
        self.job_id = initial.job_id
        self._stream_request = request
        self._stream_unbounded = unbounded
        self._stream_channels = list(channels)
        self._stream_source = trigger_source
        self._stream_sequence = self._stream_read = self._stream_acked = 0
        self._stream_session = None
        self._stream_previous = None
        self._stream_pending = []
        self._stream_read_rpc_ns = self._stream_decode_ns = 0
        self._stream_deadline = time.monotonic() + job_timeout_ms / 1000 if job_timeout_ms else None
        self._last_keepalive = time.monotonic()
        try:
            self._validate_stream_status(initial)
        except BaseException:
            self.cancel()
            raise
        return initial

    def _validate_stream_status(self, reply):
        p, request = self.pb, self._stream_request
        if (reply.job_id != self.job_id or reply.backend != p.ACQUISITION_DMA or reply.contract_version != 3 or
                reply.capture_mode != p.DMA_CAPTURE_PERSISTENT or reply.trigger_source != request.trigger_source or
                reply.pretrigger_samples != request.pretrigger_samples or reply.job_timeout_ms != request.job_timeout_ms or
                not reply.HasField('session_progress') or reply.session_progress.target != request.target_waveforms):
            raise RuntimeError('Persistent status identity/contract changed')
        if getattr(request, 'force_acquisition', False) and not getattr(reply, 'force_acquisition', False):
            raise RuntimeError('Persistent force acquisition acknowledgement missing')
        if reply.state not in (p.DMA_JOB_RUNNING, p.DMA_JOB_READY):
            raise RuntimeError(reply.message or 'Persistent session failed/cancelled')
        s = reply.session_progress
        if (s.error or s.hardware_error or s.staged_events > self.capabilities.maximum_staged_events or
                s.staged_bytes > self.capabilities.maximum_job_bytes or
                s.staged_events != len(reply.available_events) or s.acknowledged != self._stream_acked or
                not s.acknowledged <= s.delivered <= s.staged <= request.target_waveforms or
                not s.driver_released <= s.driver_delivered <= s.completed <= s.accepted <= request.target_waveforms):
            raise RuntimeError('Persistent counters/queue mismatch')
        if s.session:
            if self._stream_session is not None and self._stream_session != s.session:
                raise RuntimeError('Persistent hardware session changed')
            self._stream_session = s.session
        previous = self._stream_previous
        counters = tuple(getattr(s, f) for f in ('accepted', 'completed', 'driver_delivered', 'driver_released',
                        'staged', 'delivered', 'acknowledged', 'pauses', 'segment', 'starts', 'stops'))
        if previous is not None and any(a < b for a, b in zip(counters, previous)):
            raise RuntimeError('Persistent counters regressed')
        self._stream_previous = counters
        for i, event in enumerate(reply.available_events):
            seq = self._stream_acked + i + 1
            slots = self.capabilities.session_slots
            if id_tuple(event) != (self._stream_session, seq, (seq-1)//slots+1, (seq-1)%slots):
                raise RuntimeError('Persistent queue ID/order mismatch')
        return reply

    def session_status(self):
        self._check_stop()
        if self._stream_deadline and time.monotonic() >= self._stream_deadline:
            raise TimeoutError('Persistent total deadline expired')
        reply = self._call('DMA_STATUS', self.pb.DmaJobRequest(job_id=self.job_id), self.pb.DmaJobResponse)
        self._validate_stream_status(reply)
        self._last_keepalive = time.monotonic()
        if self.progress_callback:
            self.progress_callback(reply.session_progress.completed, reply.session_progress.target, reply.phase)
        return reply

    def read_batch(self, maximum_events=1):
        if self.job_id is None or not hasattr(self, '_stream_request'):
            raise RuntimeError('Start a persistent session first')
        if self._stream_pending:
            raise RuntimeError('ACK the previous event batch first')
        request, c, p = self._stream_request, self.capabilities, self.pb
        if not 1 <= maximum_events <= self.batch_limit(self._stream_channels, request.samples, 'persistent', request.pretrigger_samples):
            raise ValueError('Invalid bounded transport batch')
        if self._stream_read == request.target_waveforms:
            raise StopIteration
        status = self.session_status()
        while not status.available_events:
            if status.state == p.DMA_JOB_READY:
                raise RuntimeError('Producer finished with missing events')
            time.sleep(.002)
            status = self.session_status()
        ids = list(status.available_events[:maximum_events])
        channels, samples = self._stream_channels, request.samples
        routes = {r: sorted(ch for ch in channels if ch//16 == r) for r in range(3)}
        active = [r for r in routes if routes[r]]
        order = {ch: i for i, ch in enumerate(channels)}
        data = np.empty((len(ids), len(channels), samples), dtype=np.uint16)
        metadata = []
        for w, event in enumerate(ids):
            encoded = None
            event_meta = None
            for route in active:
                tick = 0
                while tick < samples:
                    self._check_stop()
                    self._renew_lease()
                    rpc_begin = time.perf_counter_ns()
                    reply = self._call('DMA_READ', p.DmaReadRequest(job_id=self.job_id, event_id=event,
                        route=route, tick_offset=tick, maximum_bytes=c.maximum_fragment_bytes), p.DmaReadResponse)
                    self._stream_read_rpc_ns += time.perf_counter_ns() - rpc_begin
                    decode_begin = time.perf_counter_ns()
                    count, end = reply.tick_count, tick + reply.tick_count
                    final_route = end == samples
                    final_wave = final_route and route == active[-1]
                    if (reply.job_id != self.job_id or reply.backend != p.ACQUISITION_DMA or reply.route != route or
                            reply.fragment_sequence != self._stream_sequence or reply.target_waveforms != request.target_waveforms or
                            list(reply.channels) != routes[route] or reply.samples != samples or reply.tick_offset != tick or
                            count <= 0 or end > samples or reply.sample_format != 1 or reply.gateware_build_id != c.gateware_build_id or
                            len(reply.raw16_le) != count*2*len(routes[route]) or len(reply.raw16_le) > c.maximum_fragment_bytes or
                            reply.final_route != final_route or reply.final_waveform != final_wave or
                            reply.final_job != (final_wave and event.sequence == request.target_waveforms) or
                            reply.independently_software_triggered or not reply.HasField('waveform_metadata')):
                        raise RuntimeError('Persistent fragment contract/sequence mismatch')
                    m = reply.waveform_metadata
                    valid_bytes = [samples*2*len(routes[r]) for r in range(3)]
                    if (m.contract_version != 3 or m.capture_mode != p.DMA_CAPTURE_PERSISTENT or
                            id_tuple(m.event_id) != id_tuple(event) or m.channel_mask != sum(1 << ch for ch in channels) or
                            m.samples != samples or m.pretrigger_samples != request.pretrigger_samples or
                            m.trigger_source != request.trigger_source or m.period_ticks != c.period_ticks or
                            m.trigger_index < request.pretrigger_samples or m.window_first != m.trigger_index-request.pretrigger_samples or
                            m.fence_end % c.period_ticks or not samples <= m.fence_end-m.first_cursor < samples+c.period_ticks or
                            list(m.valid_bytes) != valid_bytes or len(m.ignored) != 4 or
                            reply.timestamp != m.trigger_timestamp or reply.timestamp_valid != m.trigger_timestamp_valid):
                        raise RuntimeError('Persistent event/window/route metadata mismatch')
                    serial = m.SerializeToString()
                    if encoded is not None and encoded != serial:
                        raise RuntimeError('Persistent metadata changed within event')
                    encoded = serial
                    event_meta = dict(event_id=dict(session=event.session, sequence=event.sequence,
                        generation=event.generation, slot=event.slot), channel_mask=m.channel_mask,
                        first_cursor=m.first_cursor, fence_end=m.fence_end, trigger_index=m.trigger_index,
                        window_first=m.window_first, segment=m.segment, valid_bytes=list(m.valid_bytes),
                        ignored=list(m.ignored), samples=samples, pretrigger_samples=request.pretrigger_samples,
                        trigger_timestamp=m.trigger_timestamp, trigger_timestamp_valid=m.trigger_timestamp_valid)
                    raw = np.frombuffer(reply.raw16_le, dtype='<u2').reshape(count, len(routes[route]))
                    if np.any(raw & 3):
                        raise RuntimeError('DMA ADC14 framing error')
                    for i, ch in enumerate(routes[route]):
                        data[w, order[ch], tick:end] = raw[:, i]
                    self._stream_decode_ns += time.perf_counter_ns() - decode_begin
                    tick = end
                    self._stream_sequence += 1
            metadata.append(dict(waveform=event.sequence-1, timestamp_valid=event_meta['trigger_timestamp_valid'],
                hardware_timestamp=event_meta['trigger_timestamp'] if event_meta['trigger_timestamp_valid'] else None,
                trigger=event_meta))
        decode_begin = time.perf_counter_ns()
        np.right_shift(data, 2, out=data)
        np.bitwise_xor(data, 0x2000, out=data)
        self._stream_decode_ns += time.perf_counter_ns() - decode_begin
        self._stream_pending = ids
        self._stream_read += len(ids)
        metadata = dict(backend='dma', capture_mode='persistent', wire_format='raw16_le',
            saved_format='adc14_u16_le', saved_encoding='offset_binary',
            wire_encoding='adc14_twos_complement_left_shift_2', build_id=c.gateware_build_id,
            job_id=self.job_id, channels=channels, samples=samples, waveforms=metadata,
            trigger_source=self._stream_source, pretrigger_samples=request.pretrigger_samples,
            independent_software_triggers=False, continuous=False, timestamp_reference='adc_index_by_segment')
        if self._stream_unbounded:
            metadata['unbounded_session'] = True
        return data, metadata

    def ack_batch(self):
        if not self._stream_pending:
            raise RuntimeError('No pending event ACK')
        reply = self._call('DMA_CONTROL', self.pb.DmaControlRequest(job_id=self.job_id,
            action=self.pb.DMA_ACK, event_ids=self._stream_pending), self.pb.DmaJobResponse)
        # Never replay a successful ACK even if response validation later fails.
        self._stream_acked += len(self._stream_pending)
        self._stream_pending = []
        self._validate_stream_status(reply)
        return reply

    def finish_session(self):
        if self._stream_unbounded:
            raise RuntimeError('Unbounded sessions end with cancel, not a finite final ACK')
        if self._stream_pending or self._stream_acked != self._stream_request.target_waveforms:
            raise RuntimeError('Finish requires all events processed and ACKed')
        reply = self.session_status()
        while reply.state == self.pb.DMA_JOB_RUNNING:
            time.sleep(.002)
            reply = self.session_status()
        s = reply.session_progress
        n = self._stream_request.target_waveforms
        if (not s.producer_complete or not s.guards_ok or s.starts != 1 or s.stops != 1 or
                any(v != n for v in (s.accepted, s.completed, s.driver_delivered, s.driver_released,
                                     s.staged, s.delivered, s.acknowledged))):
            raise RuntimeError('Persistent final counts/idle mismatch')
        self.acknowledge()
        return reply
