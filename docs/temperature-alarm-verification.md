# Observation-only temperature alarms

Server source `4558bbf`; client qualification `72dafbc`. No sensor comparator,
power, shutdown, clock or network-setting writes are introduced by this feature.
The existing protection/enable policy is unchanged.

Every named `TemperatureStatus` now contains additive `alarm` field 9, including
the carrier observation inside `GeneralInfo`. It reports the active thresholds,
maximum permitted observation age, evaluation time, optional measured age,
reason and policy source. Existing temperature/quality/timestamp fields retain
their acquisition meaning.

| State | Meaning |
| --- | --- |
| Good | Fresh valid value below warning threshold |
| Warning / High / Critical | Fresh value at or above the respective threshold |
| Missing | Explicit unavailable observation, without a fabricated value/time |
| Invalid | Bad value, quality, metadata or future/missing monotonic timestamp |
| Stale | Otherwise valid observation older than the policy permits |
| Unspecified | No evaluation; notably an older server, never implicitly Good |

Default provisional commissioning thresholds are **85 / 95 / 105 degrees C**;
maximum age is **5000 ms**. These high initial limits are not component ratings
or certified safe operating limits. Evaluation is sampled, non-latching,
without hysteresis and observation-only: a Critical result does not power down
the board or provide a DPS permit. Missing/stale data must not be treated as cool.
The external consumer must also detect stale replies or loss of the server.

## Configuration

Set at server startup; all values are validated before hardware initialization:

```text
--temperature-warning-c       / DAPHNE_TEMP_WARNING_C
--temperature-high-c          / DAPHNE_TEMP_HIGH_C
--temperature-critical-c      / DAPHNE_TEMP_CRITICAL_C
--temperature-maximum-age-ms   / DAPHNE_TEMP_MAXIMUM_AGE_MS
```

Thresholds must be finite and strictly ordered, between -273.15 and 1000 C.
Age must be 1..60000 ms. Those parser bounds are not hardware ratings.
CLI values take precedence over environment values; changing service startup
configuration requires a planned restart and subsequent full FE restoration.
No public network setter or unauthenticated remote protection-policy write was
added. Active values are readable in every evaluation.

## Verification

All 14 native C++ suites and their 14 ARM executables passed. Alarm tests cover
threshold boundaries, zero/negative/NaN/infinite inputs, missing/invalid/stale
metadata, age limits, wire presence, custom policies and non-latching recovery.
Five new Python tests validate the independent consumer-side contract. Previous
AMS, carrier/service and bookkeeping Python suites also passed (16 tests).
On the Kria, an invalid policy exited **78** before driver initialization.

Live DAPHNE-015 checks passed: all four sensors and the GeneralInfo carrier
observation reported Good with the default policy (carrier 31.4375 C, die
38.577..39.619 C). All 153 aggregate regression exchanges passed again,
including alignment, fresh AFE registers and four unclipped waveforms per
channel in both AFE orders. The 16-exchange telemetry/service/rejection suite
passed. After restart, bookkeeping correctly began with a new process ID and
no applied configuration; full zero-BIAS Configure restored valid evidence.
The server had zero automatic restarts. The approved live management MAC/IP/
route and all eight protected file checksums remained unchanged.

Read-only qualification, using the approved localhost SSH forward and matching
generated protobufs:

```bash
python daphne-server/scripts/verify_server_v05.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --require-ams-temperatures --require-carrier-temperature \
  --require-voltages --require-services --require-temperature-alarms
```

Invalid/high/stale alarm behavior was tested with synthetic observations, not
by heating the board or disabling real sensors. Live alarm qualification does
not establish analog accuracy or thermal protection.

Candidate SHA-256:
`f9178dfc9c799b6e25c166f2199c46095b593b4074c48c2ceec3a2ccef19e3d0`.
Previous application retained as
`/usr/bin/daphneServer.pre-temperature-alarm-4558bbf`.
Evidence directory: `completion-VEpMKkGG`, files prefixed `temperature-alarm-`.
Raw capture SHA-256:
`d04b08cef7c8757682d2ca547c60e7dbd41682df47fdc4608bda255b0ac25af2`.
