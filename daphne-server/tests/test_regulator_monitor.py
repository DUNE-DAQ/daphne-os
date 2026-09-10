import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from verify_regulator_monitor import ROUTES, READS, check_regulator, check_profile, expected_flags, linear11


def sample(index=0):
    name, reference, address = ROUTES[index]
    r = h.RegulatorMonitor(name=name, schematic_reference=reference, address=address, source="PL 9c000000",
        pec_required=True, identity_quality=h.MEASUREMENT_GOOD, identity_bracket_verified=True,
        acquisition_started_monotonic_ns=1, observed_monotonic_ns=100, observed_host_unix_ns=200,
        output_voltage_v=3.3046875, output_current_a=.3125, voltage_quality=h.MEASUREMENT_GOOD,
        current_quality=h.MEASUREMENT_GOOD, status_changed=False, message="synthetic")
    values = {0xd0:0x0056, 0x98:0x11, 0x19:0xb0, 0x20:0x17, 0x8b:0x069c, 0x8c:0xe005, 0x8e:35, 0x38:0x886d, 0x39:0xe7ff}
    for i, (n, c, width) in enumerate(READS):
        v = r.registers.add(name=n, command=c, width_bits=width)
        if c == 0x80:
            v.quality=h.MEASUREMENT_UNAVAILABLE; v.message="unqualified"
        else:
            v.raw=values.get(c,0); v.quality=h.MEASUREMENT_GOOD; v.observed_monotonic_ns=i+2
    t = r.temperature
    t.name=reference + " regulator READ_TEMPERATURE_2"; t.source="synthetic"; t.message="synthetic"
    t.temperature_c=35; t.valid=True; t.quality=h.MEASUREMENT_GOOD
    t.observed_monotonic_ns=next(v.observed_monotonic_ns for v in r.registers if v.command == 0x8e)
    t.observed_host_unix_ns=200
    t.alarm.state=h.TEMPERATURE_ALARM_GOOD; t.alarm.warning_c=85; t.alarm.high_c=95; t.alarm.critical_c=105
    t.alarm.maximum_age_ms=5000; t.alarm.evaluated_monotonic_ns=100
    t.alarm.observation_age_ns=100-t.observed_monotonic_ns; t.alarm.policy_source="synthetic"; t.alarm.message="synthetic"
    return r


class RegulatorTests(unittest.TestCase):
    def test_both_abi_variants(self):
        s = h.SystemStatusSnapshot(success=True)
        s.gateware_identity.magic=0x44415048; s.gateware_identity.abi=0x20000; s.gateware_identity.build_id=123
        for mode, variant in (("self-trigger",1),("full-stream",2)):
            s.gateware_identity.variant=variant; check_profile(s,mode,123)
            for wrong in (0,3):
                s.gateware_identity.variant=wrong
                with self.assertRaises(RuntimeError): check_profile(s,mode,123)

    def test_all_routes_and_roundtrip(self):
        for index in range(4):
            r = sample(index)
            check_regulator(h.RegulatorMonitor.FromString(r.SerializeToString()), h, index)

    def test_missing_wrong_fields_are_rejected(self):
        changes = [lambda r: r.ClearField("output_voltage_v"), lambda r: r.ClearField("output_current_a"),
                   lambda r: setattr(r,"output_current_a",-.3125), lambda r: setattr(r,"pec_required",False),
                   lambda r: setattr(r,"identity_bracket_verified",False), lambda r: setattr(r,"status_changed",True),
                   lambda r: setattr(r,"observed_monotonic_ns",6_000_000_000),
                   lambda r: setattr(r.registers[0],"raw",0), lambda r: setattr(r.registers[1],"raw",0x5a),
                   lambda r: setattr(r.registers[-1],"raw",0x16), lambda r: setattr(r.registers[7],"raw",0x8000),
                   lambda r: setattr(r.temperature,"temperature_c",0), lambda r: setattr(r.temperature.alarm,"state",0),
                   lambda r: setattr(r.registers[8],"observed_monotonic_ns",999)]
        for change in changes:
            r = sample(); change(r)
            with self.assertRaises(RuntimeError): check_regulator(r,h,0)

    def test_each_raw_read_is_required(self):
        for i in range(1,len(READS)):
            r = sample(); r.registers[i].ClearField("raw")
            with self.assertRaises(RuntimeError): check_regulator(r,h,0)

    def test_flags_are_retained_and_not_health(self):
        r = sample()
        for v in r.registers:
            if v.command in (0x79,0x7e): v.raw=2
        r.asserted_status_flags.extend(expected_flags(r.registers))
        self.assertEqual(len(r.asserted_status_flags),4)
        check_regulator(r,h,0)  # Readout is valid despite pre-existing status bits.
        r.ClearField("asserted_status_flags")
        with self.assertRaises(RuntimeError): check_regulator(r,h,0)

    def test_zero_is_present_and_l11_is_signed(self):
        r = sample(); r.output_voltage_v=0; r.output_current_a=0
        for v in r.registers:
            if v.command == 0x8b: v.raw=0
            if v.command == 0x8c: v.raw=0xe000
        check_regulator(r,h,0)
        self.assertEqual(linear11(0xe7ff),-.0625)
        self.assertEqual(linear11(0x07fb),-5)


if __name__ == "__main__":
    unittest.main()
