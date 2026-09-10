# Mezzanine calibration: requested code versus register readback

Candidate **de420e0 is native-tested, not deployed**. DAPHNE-015 and its ONL
bundle remain **fb82e0a**, with the SC-owned enable state preserved. No mezzanines
are fitted. This fixes the producer for workbook **I225/I226**; it does not
qualify physical current measurement or close the mezzanine telemetry backlog.

## Correction

Previously `readHDMezzBlockConfig` called `getShuntCal()`, which returns the
software calculation. The response labelled that cached number as readback.
Commit **d212e13** adds a driver acquisition; **de420e0** connects it to the
protocol and client. Existing field numbers are unchanged.

| Response data | Meaning |
| --- | --- |
| `shunt_cal_5V`, `shunt_cal_3V3` | Actual register-0x05 values, usable only with GOOD quality |
| `requested_shunt_cal_*`, fields 4–13 | Cached requested/derived settings; require `requested_settings_available` |
| `block_enabled`, `driver_configured` | Software access selection and last programming result; not physical presence or fresh protection validation |
| Quality and monotonic interval | Complete acquisition outcome; not UTC or a hardware sample latch |

`3V3` remains the legacy wire name for **CE**. A GOOD pair can differ from its
requested codes—including actual reset value zero. The separate comparison flag
reports that mismatch; it does not automatically recalibrate or change power.
GOOD means the register pair was acquired, not that the protection settings match.

## Acquisition and side effects

One driver lock protects the requested-settings snapshot and the complete I2C
sequence. The mux selects only the explicitly enabled block. Both devices'
manufacturer IDs bracket two reads of each calibration register. Reject wrong
IDs, changing values, short/failed transfers, reserved bit 15, missing/backward
monotonic time or an interval over 100 ms. Never return a partial or old pair.

The manufacturer's value is a TI/address sanity check, **not a unique device
or INA232 model identifier**. These are sequential software-coherent observations,
not simultaneous conversions or protection against an undetected change-and-return.

Only mux selection and non-clearing register reads occur. No block enable,
configuration, calibration write, TCA output write or alert-register read is
performed. Reading Mask/Enable can clear the latched alert, so that register
must not be added casually to a read-only RPC. See the
[TI INA232 register map, sections 7.6.1.6–7.6.1.9](https://www.ti.com/lit/ds/symlink/ina232.pdf).
The existing protective monitor and explicit power commands are unchanged.

Disabled/missing drivers return unavailable without bus access. An enabled but
not configured block may report its actual calibration registers. Legacy clients
receive `success=false` when no complete pair exists; zero codes on such a
response are protobuf defaults, not measurements. New clients label an old
server's response `legacy-unqualified` instead of treating cached codes as readback.

## Verification

Clean detached source `de420e0f3bf3d6eecd9a6bd0e9f29b0985cf02cf`, server subtree
`4df9f11b3aae70cad7cc364553bf786389430c95`:

- **34 host and 34 actual ARM C++ suites**, including 21 driver cases.
- **222 Python tests per independently generated binding set**, no skips.
- Eight read positions tested for both exceptions and short transfers, after a
  successful acquisition; no partial/previous pair accepted.
- Changed identity/calibration, reserved bits, requested/readback mismatch, reset
  zero, disabled/unconfigured blocks and timing boundaries tested.
- Concurrent block acquisitions remain complete and mux-coherent. Bus logs
  assert no downstream writes or reads outside manufacturer/calibration registers.
- Protobuf tests cover failure masking, timestamps, requested-versus-actual
  values, missing-driver state and preservation of all 15 original field numbers.
- Python validates wire values and the actual CLI renderer; handler-source guards
  check wiring, not a simulated execution of the complete hardware constructor.
- Complete ARM server build, native metadata probe and candidate `--help` pass.
  The executable is **not installed**. Both binding sets independently decode
  and verify the native proof against the clean sources.

Native binary SHA-256:
`0adae2adff22b65eda2c46f7eb43c3a9643adc08a3ffae73d93f388b18708663`.
Native proof SHA-256:
`d7e93459548556c51a8ebd3c0fcc54d5473fd9a153c00a61ee8ec4c694ccd1dd`.
Evidence directory: `server-v05-fixes-20260909/mezzanine-readback.wZfqKwmJ`.
Initial Python commands had an unquoted PATH containing spaces; corrected runs
pass. The adapted proof checker initially used an old guard-field name; the
corrected checker verifies the unchanged complete guard and all four control words.
Failed attempts are retained; no hardware test or deployment was retried.

Before/after guards are identical: installed fb82e0a, same process/boot/runtime,
firmware, Hermes and protected settings, enable1 and selectors0/0. No Configure,
mezzanine I2C, bias, network/time write or service restart was issued by this phase.
Native hardware-free fixtures ran from a private RAM directory.

## Client command after a qualified deployment

With matching generated bindings and an approved local SSH forward:

```bash
DAPHNE_BUILD_DIR="$BUILD_DIR" python daphne-server/client/hdmezz_control_v2.py \
  read-block-config --ip 127.0.0.1 --port 19876 --afe 0
```

Set `BUILD_DIR` explicitly. This command neither enables nor configures a block.
Do not enable absent hardware just to obtain a GOOD response. On the currently
installed old server, this new readback is not available.

## Next gate

Replace the independent measurement atomics with one quality/timed cache;
invalidate failed, stale, disabled and unconfigured samples while retaining
alert evidence and the existing protective behavior. Fresh calibration mismatch
must not be mistaken for proof that cached current scaling remains valid.
I203/I204 remain partial: the new flags are process bookkeeping, not a complete
qualified block/protection-state observation. Finish that work and its client
tests before the next server-only deployment. Populated-hardware readback,
metrology, firmware/full-stream and the remaining register/database requirements
remain open. Current deployment and bundle pins are intentionally unchanged.
