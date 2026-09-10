from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daphneV3_high_level_confs_pb2 as h
from timesync import check_timesync, META_FIELDS, SAMPLE_FIELDS, SOURCE


def fixture(sample=True):
    status = h.SystemStatusSnapshot()
    item = status.host_time.timesync
    item.CopyFrom(h.TimesyncObservation(quality=h.MEASUREMENT_GOOD, source=SOURCE, detail="Historical service snapshot",
        acquisition_started_monotonic_ns=100, observed_monotonic_ns=200, bus_id='a'*32, unique_owner=':1.55',
        owner_bracket_verified=True, details_included=False, selected_name_present=True, selected_address_present=True,
        poll_interval_us=32000000, poll_minimum_us=32000000, poll_maximum_us=2048000000, root_distance_maximum_us=5000000,
        processed_packet_count=(1 << 64)-1 if sample else 0, frequency_scaled_ppm=-123456))
    item.last_sample.CopyFrom(h.NtpSampleObservation(quality=h.MEASUREMENT_UNAVAILABLE,
        age_bound_quality=h.MEASUREMENT_UNAVAILABLE, detail='No sample'))
    if sample:
        item.last_sample.CopyFrom(h.NtpSampleObservation(quality=h.MEASUREMENT_GOOD, detail='Processed, possibly ignored sample',
            leap=0, version=4, mode=4, stratum=2, precision_exponent=-20, root_delay_us=1000, root_dispersion_us=2000,
            origin_unix_us=1700000000000000, receive_unix_us=1700000000000101, transmit_unix_us=1700000000000111,
            destination_unix_us=1700000000000200, ignored_spike=True, jitter_us=300, offset_ns=6000,
            round_trip_delay_ns=190000, age_bound_quality=h.MEASUREMENT_UNAVAILABLE))
    return status


class TimesyncTests(unittest.TestCase):
    def check(self, status, **kwargs):
        return check_timesync(status, h, now_monotonic_ns=300, **kwargs)

    def test_exact_counter_historical_spike_and_unknown_age(self):
        report = self.check(h.SystemStatusSnapshot.FromString(fixture().SerializeToString()))
        self.assertEqual(report['processed_packet_count'], (1 << 64)-1)
        self.assertTrue(report['historical_sample']['ignored_spike'])
        self.assertEqual(report['historical_sample']['offset_ns'], 6000)
        self.assertIsNone(report['sample_age_upper_bound_ns'])

    def test_no_sample_is_unavailable_not_zero_offset(self):
        report = self.check(fixture(False))
        self.assertEqual(report['processed_packet_count'], 0)
        self.assertIsNone(report['historical_sample']['offset_ns'])
        status = fixture(False); status.host_time.timesync.last_sample.offset_ns = 0
        with self.assertRaises(RuntimeError): self.check(status)

    def test_missing_fields_owner_poll_ranges_and_partial_sample_fail(self):
        for fields, group in ((META_FIELDS, ''), (SAMPLE_FIELDS, 'last_sample')):
            for field in fields:
                status = fixture(); item = status.host_time.timesync
                if group: item = item.last_sample
                item.ClearField(field)
                with self.subTest(field=field), self.assertRaises(RuntimeError): self.check(status)
        for field, value in (('owner_bracket_verified', False), ('bus_id','x'*32), ('unique_owner','not-owner'),
                             ('poll_minimum_us',0), ('poll_interval_us',1), ('root_distance_maximum_us',0)):
            status=fixture(); setattr(status.host_time.timesync, field,value)
            with self.assertRaises(RuntimeError): self.check(status)

    def test_unavailable_and_error_queries_are_not_measurements(self):
        for quality in (h.MEASUREMENT_ERROR, h.MEASUREMENT_UNAVAILABLE):
            status=fixture(False); item=status.host_time.timesync
            item.quality=quality
            with self.assertRaises(RuntimeError): self.check(status)
            for field in META_FIELDS+('bus_id','unique_owner','owner_bracket_verified','observed_monotonic_ns'): item.ClearField(field)
            self.assertFalse(self.check(status)['service_observed'])
            with self.assertRaises(RuntimeError): self.check(status, require_available=True)

    def test_private_details_require_explicit_optin_but_are_never_echoed(self):
        status=fixture(); item=status.host_time.timesync
        item.details_included=True
        item.selected_server_name='private-peer.example.invalid'; item.selected_server_address='192.0.2.10'
        with self.assertRaises(RuntimeError): self.check(status)
        report=str(self.check(status, private_requested=True))
        self.assertNotIn('private-peer',report); self.assertNotIn('192.0.2.10',report)
        item.detail='private-secret'; item.last_sample.detail='private-secret'
        self.assertNotIn('private-secret',str(self.check(status, private_requested=True)))
        item.selected_server_name='private/secret'
        with self.assertRaisesRegex(RuntimeError,'details suppressed'): self.check(status, private_requested=True)

    def test_stale_future_reversed_and_overlong_queries_fail(self):
        with self.assertRaises(RuntimeError): check_timesync(fixture(),h,now_monotonic_ns=5000000201)
        for start,end in ((0,200),(201,200),(100,301),(1,2000000002)):
            status=fixture(); item=status.host_time.timesync
            item.acquisition_started_monotonic_ns=start; item.observed_monotonic_ns=end
            with self.assertRaises(RuntimeError): self.check(status)

    def test_age_bound_is_consistent_and_never_implied_by_wall_time(self):
        status=fixture(); sample=status.host_time.timesync.last_sample
        sample.age_bound_quality=h.MEASUREMENT_GOOD; sample.not_before_monotonic_ns=50; sample.maximum_age_ns=150
        self.assertEqual(self.check(status)['sample_age_upper_bound_ns'],150)
        for field,value in (('maximum_age_ns',151),('not_before_monotonic_ns',0),('not_before_monotonic_ns',101),
                            ('age_bound_quality',h.MEASUREMENT_UNAVAILABLE)):
            broken=h.SystemStatusSnapshot.FromString(status.SerializeToString())
            setattr(broken.host_time.timesync.last_sample,field,value)
            with self.assertRaises(RuntimeError): self.check(broken)

    def test_sample_arithmetic_units_and_protocol_are_independent(self):
        for field,value in (('offset_ns',0),('round_trip_delay_ns',0),('origin_unix_us',0),('version',2),('leap',3),
                            ('mode',3),('stratum',0),('precision_exponent',128),('destination_unix_us',(1<<64)-1)):
            status=fixture(); setattr(status.host_time.timesync.last_sample,field,value)
            with self.assertRaises(RuntimeError): self.check(status)
        status=fixture(); item=status.host_time.timesync.last_sample
        item.origin_unix_us=100; item.receive_unix_us=105; item.transmit_unix_us=115; item.destination_unix_us=121
        item.offset_ns=-500; item.round_trip_delay_ns=11000
        self.assertEqual(self.check(status)['historical_sample']['offset_ns'],-500)


if __name__=='__main__': unittest.main()
