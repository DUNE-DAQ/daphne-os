# Mezzanine monitoring cache: driver step

Source **6514092** adds the cache to `HDMezzDriver`. **Not deployed and not yet
connected to the background monitor/status RPC/client.** DAPHNE-015, the image
pin and the ONL runtime remain **fb82e0a**. No mezzanines are fitted.

## What changes

One driver mutex now protects a complete per-block acquisition and publication.
The cached snapshot contains both rails' voltage/current/power, TCA output
requests, driver enable/configured flags, quality, monotonic acquisition/state
times, attempt number and last-good time. `monitoringSnapshot()` is cache-only.
The existing `3V3` name means the schematic's **CE** rail.

GOOD requires a complete acquisition within 100 ms, matching manufacturer,
configuration, calibration and alert-limit words before/after the measurements,
TCA directions, and fresh acceptable INA232 status. These are sequential register
observations—not simultaneous ADC conversions, physical calibration, actual
power or proof against an undetected change-and-return. The TI manufacturer
word is not a unique device/model identity.

Numerical values and power/configuration-validity claims are suppressed on
unavailable/error/invalid/stale samples. Cache age over five seconds is stale;
missing/backward clocks are invalid. Control attempts invalidate before possible
hardware mutation, including failed writes; rejected inputs and an idempotent
enable do not. A calibration RPC may return GOOD **raw** codes that differ from
the requested scale; that mismatch invalidates scaled monitoring data without
changing the driver's configured flag or issuing a control write.

## Alerts remain separate history

Reading INA232 Mask/Enable clears its latched AFF. Record the observation before
attempting the existing removal of both TCA power requests. A failed or uncertain
write must not erase the already consumed alert. Continue polling the other
rail's alert even if measurement acquisition or the first rail failed.
MemError/OVF and invalid control bits suppress measurements; they do not add a
new automatic shutdown policy. See the [TI register definitions, section
7.6.1.7](https://www.ti.com/lit/ds/symlink/ina232.pdf).

Retain the existing policy of not repeatedly reading a software-latched rail's
clearing status. Its history timestamp is not refreshed. Without fresh device
status, subsequent numerical samples are unavailable; removal of power requests
is still retried. Only explicit software clear or **successful** disable clears
the history. Clear does not read hardware or re-enable power. Historical alert
evidence can survive a bad/missing timestamp, but cannot make a sample GOOD.

`powerRequestsOffConfirmed` is valid only for a GOOD snapshot and refers to the
TCA latch, not measured physical rail power. `protectiveActionAttempted` records
an attempt, not its success. BiasEnable/BIASCTRL/SC ownership are untouched.

## Verification boundary

Clean source passes **34 host C++ suites**, including the 33 driver cases below,
and **222 Python tests per independently generated host/ARM binding set** with
no skips. The complete **AArch64 server cross-build** and host metadata probe
pass; **the new ARM executable has not been run on the Kria**. All 140 packaging
tests and the exact 251-row XLSX/export audit pass. No native-board or live RPC
test, service restart, firmware load or board/network/time/SC write was issued.

The 33 fake-bus driver cases include all 54 normal poll transfer positions
(mux and downstream), all 24 INA word-read positions as short transfers,
configuration/identity/calibration/limit bit changes, status flags, timing and
freshness boundaries, signed units and valid zeroes, failed/uncertain protective
writes, explicit clear/disable, control invalidation and concurrent whole cycles.
Cache-only and disabled/unconfigured paths assert zero bus traffic.

Evidence directory: `server-v05-fixes-20260909/mezzanine-monitor.UaWZ44yu`.
Clean source: `65140925c748a6780b20fa74e0ec99a9423b6a65`.
Server subtree: `7f7415d99926eaa101fa830bcd3abe216c3e1761`.
Qualification results are recorded with that evidence; do not substitute the
earlier de420e0 native proof for this new code. No hardware action is needed for
these tests. Using an explicitly configured build directory:

```bash
cmake --build "$BUILD_DIR" --target hdmezz_driver_tests
ctest --test-dir "$BUILD_DIR" -R '^hdmezz_driver_unit$' --output-on-failure
```

## Next small commit

Wire background polling and status/clear handlers to this cache; remove the
independent atomics. Add compatible response quality/time/presence metadata and
client validation/rendering that never displays unavailable defaults as measured
zero. Keep alert history separate from current sample validity. Then qualify
the combined candidate, including native ARM fixtures and no-mezzanine live
responses, before any server-only deployment. Populated-hardware/metrology and
the remaining firmware/database requirements remain open. Workbook I203/I204
and I207–I214 are still **partial**, not closed by an internal helper.
