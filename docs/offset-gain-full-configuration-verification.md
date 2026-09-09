# Offset gain after full configuration

Follow-up: the [local unsaturated sweep](offset-gain-sweep-verification.md)
confirms approximately doubled slopes on all 40 channels, with 36/40 meeting
the same baseline criterion across five points. This page preserves the
preceding full-configuration and single-point results.

The zero-BIAS workaround described below was required by the server used for
these runs. The later [aggregate BIAS fix](aggregate-bias-verification.md)
removes that requirement; its dedicated verifier tests without the workaround.

DAPHNE-015, 2026-09-09 (workstation date; board clock unverified).
Deployed server: `b631271`; test clients: `9c6e2fa`, then `8da57ac`.
Self-trigger ABI 2.0, firmware `0x03F17F1B`. This supersedes the earlier
[32-channel observation](offset-gain-spybuffer-verification.md), which lacked
the full FE configuration and is not evidence for normal configured operation.

## Outcome

**Full Configure applies offset gain on all 40 channels. All five AFEs align,
including AFE0. No alignment code was changed.** Full initialization was the
missing prerequisite, not an established AFE0 hardware defect.

The requested 2200/x1 versus 1100/x2 comparison was measured with 12 distinct
waveforms of 1,024 samples per channel per setting. Baseline is the median of
the waveform medians. The allowance remains 164 ADC counts (~1% of the 14-bit
span), an engineering criterion rather than a calibration specification.

| Run | A/B difference | Repeat A difference | Overall criterion |
| --- | --- | --- | --- |
| Full Configure + alignment at each setting | −161.5 to +238 counts | +76 to +135.5 | 34/40 pass |
| Initialized FE; offsets only; control before repeat | −162.5 to +236 | +172 to +231.5 | 0/40 pass; 37/40 satisfy A/B alone |
| Initialized FE; A → B → A, then control | −159 to +236 | −3.5 to +5.5 | 37/40 pass |

The 1100/x1 control clips at zero on every channel. Moving it **after** A/B/A
removes that excursion from the repeatability measurement. The large earlier
repeat shifts are therefore not clean evidence of gain error. All runs are
retained; no tolerance was relaxed or result discarded.

In the final run, channels **15, 19 and 36** exceed the allowance by reporting
A/B differences of **+235, +236 and +196.5** counts respectively. The largest
difference is 1.44% of the ADC span; the median absolute difference is 67.875
counts. A/B/A captures do not clip; within-waveform RMS is 1.69–2.45 counts.
The residual is much larger than waveform noise. Its analog cause has not
been established: do not claim calibrated equivalence or all-40-channel pass.
An unsaturated offset sweep or direct DAC measurement is the next diagnostic,
not another alignment patch or a looser pass criterion.

## Configuration and safeguards

- Before each full Configure: explicitly write **BIASCTRL=0 and all five
  BIAS=0**. The server used here skipped `v_bias=0`, so its zero-valued
  field alone does not clear a previous DAC setting. The explicit writes are
  a test workaround; skip-zero semantics were not changed here.
- Preserve the existing enable policy. Normal Configure asserts the separate
  generator-enable bit; that is not a request for nonzero BIASCTRL.
- Full profile: trim=0; VGAIN=1700; 14-bit offset-binary, LSB first; PGA=24 dB,
  LPF=10 MHz; LNA=12 dB, clamp=1.15 Vpp; both integrators disabled. The script's
  `zero_bias_profile()` and each full-run request contain the complete setup.
- All four full Configures acknowledge the requested offset gain on 40/40
  channels, followed by five settled alignment passes. Fresh reads on all
  five AFEs match registers 1/2/3/4/51/52 =
  `0 / 0 / 0x2000 / 0x0008 / 0x0058 / 0x5400`.
- Final commands: all channels **2200/x1**, BIASCTRL and all BIAS codes zero.
  Bias cache reads confirm the requested codes, **not physical voltage**.
  AD5327 output readback and working bias-voltage telemetry are unavailable.
- Server/runtime active; no automatic server restarts. Protected network,
  SSH-key and firmware-environment checksums match. MAC/IP, partitions and
  installed OS/firmware files were not changed by this application update.
  Starting the runtime reloaded the same FPGA application.

Six C++ tests passed natively and on the board; ten hardware-free Python
verifier tests pass. Deployed executable SHA-256:
`ad15adf71cb02e62a83911f946f3ae2f95d98ae41ebd14f49733c3c4d5cee1c5`.

## Repeat, maintenance only

Use the [client environment](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients)
and an approved local SSH forward. No board address, MAC or credential is in
these commands. Use a **new result directory** for each run.

```bash
python daphne-server/tests/test_offset_gain_spybuffer.py -v
python daphne-server/scripts/verify_offset_gain_spybuffer.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --afes 0 1 2 3 4 --waveforms 12 --samples 1024 \
  --tolerance-adc 164 --output-dir /path/to/new-full-results \
  --apply-offsets --configure-zero-bias
```

That flag changes the complete FE setup and aligns at every setting. After
successful initialization, repeat without `--configure-zero-bias`, choosing
another output directory: only offset DAC commands and spybuffer triggers
are then sent, plus identity/AFE-register reads. Current client `8da57ac`
orders A/B/A before the control, and finally commands 2200/x1 after it.
Exit 0 means all comparison criteria pass; 1 means an execution error;
2 means the measured comparison did not fully pass. **All three recorded
runs exited 2.**

## Evidence

The ONL-home bundle `daphne015-offset-fullconf-8da57ac.tgz` contains raw
captures, summaries, server/test binaries, source, generated Python protobuf
modules and checksums. It preserves both earlier runs and the final bracketed
run. Capture SHA-256 values:

| Directory / protocol exchanges | Raw capture SHA-256 |
| --- | --- |
| `offset-fullconf-0gqoduQn` / 434 | `c2fdaa5de18dbffef3459a6f67ff7d3ef3eb468922063ba5531dd8fd6754fa32` |
| `offset-initialized-Mty8lDYV` / 242 | `66252e7575c0c604d6f4ed54230292be3b7dbbf0f31bf564abe9a5be75106d34` |
| `offset-bracketed-gi20N93G` / 242 | `b08871a8f3f66585a3d4643df4c906f37349e6941554dc96cb6cb515514db0d8` |
