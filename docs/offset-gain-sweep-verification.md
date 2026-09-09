# Offset gain: local analog sweep

DAPHNE-015, 2026-09-09 (workstation date). Verifier `877caa7`; unchanged
server `b631271`, self-trigger ABI 2.0 firmware `0x03F17F1B`.
Follows the [full-configuration test](offset-gain-full-configuration-verification.md).

## What it establishes

**Gain selection works on all 40 channels; exact baseline equivalence is not
qualified.** The local response to one DAC-code step at x2 is approximately
twice the response at x1. The remaining mismatch is repeatable and
channel-dependent, not explained by a missing gain bit or failed alignment.
This does not isolate the responsible analog component or justify a server
calibration correction.

Five equivalent x1 codes were tested in order: **2200, 2190, 2210, 2180, 2220**.
At each point: x1 → half-code/x2 → original-code/x1. No clipping control,
Configure, reset, alignment or bias write was sent. Each stage settled for
1 second, then captured 12 distinct waveforms of 1,024 samples/channel.
A final 2200/x1 capture completes the record.

| Check | Result across all 40 channels |
| --- | --- |
| Baseline range across every setting | 6044.5–8451 ADC counts; no rail samples |
| Local x1 slope | 18.99–21.155 ADC counts per DAC code |
| Local x2 slope | 38.03–42.12 ADC counts per DAC code |
| x2/x1 slope ratio | 1.934–2.062; median 1.983 |
| Maximum residual from local straight-line fit | 3.575 counts at x1; 6.2 at x2 |
| Maximum A/B/A repeat difference | 11 ADC counts |
| Within-waveform RMS | 1.71–2.55 ADC counts |
| Unchanged 164-count criterion at every point | **36/40 channels pass** |

The four exceptions are below. The DAC-code equivalent is the A/B bracket
difference divided by the measured local x1 slope, **not a proposed correction**.

| Channel | B minus A, ADC counts | Equivalent x1 DAC-code difference | Slope ratio |
| --- | --- | --- | --- |
| 15 | +224…+246 | +11.15…+11.80 | 1.966 |
| 19 | +226…+248.5 | +11.75…+12.62 | 1.954 |
| 36 | +179…+203.5 | +9.12…+10.00 | 1.953 |
| 38 | −181…−149 | −8.68…−7.43 | 1.934 |

Channel 38 was borderline in the previous single-point test and crosses the
criterion at some points here. At 2200, this run passes 36/40 rather than the
previous run's 37/40. Both records stand; the tolerance was not increased.
All 40 channels exhibit a clear, positive offset response in both gain modes.

The [AD5327 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ad5307_5317_5327.pdf),
pages 3 and 17, specifies the gain-selection bit and nonzero analog offset,
gain and linearity errors. Ideal code-times-gain equivalence therefore need
not give identical measured baselines. Our measurement includes the entire
analog chain and does **not** establish compliance with the DAC specifications.
The 164-count criterion is not a manufacturer or detector calibration limit.

## Repeat

First establish the reference full FE configuration and zero bias using the
[preceding procedure](offset-gain-full-configuration-verification.md).
The sweep refuses a different AFE register profile or nonzero cached bias
commands before any offset write. It aborts remaining points on unusable
captures and attempts to return touched AFEs to 2200/x1.

```bash
python daphne-server/tests/test_offset_gain_spybuffer.py -v
python daphne-server/scripts/verify_offset_gain_spybuffer.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --afes 0 1 2 3 4 --waveforms 12 --samples 1024 \
  --sweep-equivalent-codes 2200 2190 2210 2180 2220 \
  --settle-seconds 1 --tolerance-adc 164 \
  --output-dir /path/to/new-sweep-results --apply-offsets
```

Use the approved SSH forward and client environment. Do not combine the sweep
with `--configure-zero-bias`: this comparison deliberately preserves FE setup.
Slopes use actual DAC codes, not ADC codes or the equivalent x1 code for x2.
The x1 fit uses the mean of each A/repeat-A baseline; no gain ratio is forced
in the fit. Fifteen hardware-free verifier tests pass.

## Final state and evidence

All channels finish at **2200/x1**. BIASCTRL and all five BIAS cached commands
are zero before and after; these are **not physical voltage measurements**.
All checked AFE registers are unchanged. Server PID 6639, NRestarts=0; service
and runtime active. Server binary, protected network/SSH/firmware settings and
MAC/IP configuration are unchanged. No deployment or FPGA reload was needed.

Run `offset-sweep-G6rPB8Qk`: 602 protocol exchanges; exit **2** (completed
comparison did not fully pass), no execution error. Raw capture SHA-256:
`adc2438c7aa7505e41d7cf65d70292dc834ad262f4a64e06a49d74d91dd50ed0`.
ONL-home evidence bundle: `daphne015-offset-sweep-877caa7.tgz`, with external
and internal checksums, raw captures, summaries, verifier/source and protobuf
modules. Prior bundles remain intact.

The offset-gain implementation needs no additional patch on this evidence.
Remaining analog calibration/acceptance is separate. Next software item:
explicit zero-BIAS handling in aggregate Configure, without changing the
generator-enable policy or silently breaking omitted-field behavior.
