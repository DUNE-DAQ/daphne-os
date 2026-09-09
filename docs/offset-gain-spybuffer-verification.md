# Offset DAC gain: spybuffer verification

**Historical, superseded:** this run lacked the full FE configuration. Its
near-zero baseline response and AFE0 exclusion do not describe normal configured
operation. See the [full-configuration follow-up](offset-gain-full-configuration-verification.md)
for the deployed fix, successful alignment of all five AFEs and remaining
analog differences. Statements below describe only the earlier run.

DAPHNE-015, 2026-09-09 (workstation date; board wall clock is unverified).
Client/test commit `2f7fa3e`; running server `c267a6c`; self-trigger ABI 2.0,
firmware build `0x03F17F1B`. No server update or firmware reload was required.

## Result

**32 channels passed the proposed equivalence check.** For board AFEs 1–4
(channels 8–39), 2200/x1 and 1100/x2 produced effectively the same baseline.
Each setting used 12 software-triggered waveforms of 1,024 samples/channel.

| Measurement | Observed across 32 channels |
| --- | --- |
| Baseline difference: 1100/x2 minus 2200/x1 | −1 to +2 ADC counts |
| Repeat 2200/x1 versus initial 2200/x1 | At most 1 ADC count |
| Control 1100/x1 versus 2200/x1 | −31 to −11 ADC counts |
| Within-waveform RMS at initial 2200/x1 | 2.73–6.04 ADC counts |
| Rail/clipping samples | None |

Baseline means the median of the 12 waveform medians, not an individual sample.
The configured comparison allowance was 164 counts (about 1% of the 14-bit
span), with additional rejection of stale, clipped or unresponsive captures.
That allowance is an engineering check, not a calibration specification; the
observed maximum difference was only 2 counts. The control demonstrates that
the baseline responds to offset changes, rather than merely remaining equal.

AFE register 4 was zero: output is 14-bit **two's complement**. Sign-extend
bit 13 before computing statistics; raw 16383 is −1, not the upper ADC rail.
This follows the [AFE5808A register map, p. 47](https://www.ti.com/lit/ds/symlink/afe5808a.pdf).
Registers 2, 4 and 51 were read twice before and after the test and were
unchanged on each tested AFE. Test patterns were disabled; PGA was unchanged.
The initial exploratory run used unsigned statistics and is not the final
qualification record. The corrected client repeated the complete comparison.

## Boundaries and final board state

- The existing alignment command changed FPGA delay/bitslip settings. PL AFEs
  1–4 each passed four frame-clock checks against `0x00FF00FF`.
- AFE0 failed alignment and is excluded; channels 0–7 received no offset writes.
  This test does not diagnose or repair AFE0.
- Only offsets on board AFEs 1–4 were changed: 2200/x1 → 1100/x2 → 1100/x1
  control → 2200/x1 repeat. They were left at **2200/x1**, not restored to an
  unknown original DAC state. Final commands were acknowledged; the repeated
  waveform capture supplies the analog evidence, not the DAC software cache.
- No trim, bias/HV, PGA, clock-source or network configuration changes were
  requested. The server remained active with the same PID and no restarts;
  protected network/SSH/firmware-environment checksums matched.
- This verifies the **low-level offset DAC path and x1/x2 interpretation** on
  these 32 channels. It does not exercise the new aggregate Configure handler,
  which remains software-tested/cross-built but not deployed. No full-range
  DAC calibration or full-stream qualification is claimed.

## Repeat the test

Maintenance only: first verify alignment and select only qualified board AFEs.
Use the client virtual environment and generated protobuf modules described in
the [build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
The endpoint below is a local SSH forward, not a board address or credential.

```bash
python daphne-server/tests/test_offset_gain_spybuffer.py -v
python daphne-server/scripts/verify_offset_gain_spybuffer.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --afes 1 2 3 4 --waveforms 12 --samples 1024 \
  --tolerance-adc 164 --output-dir /path/to/new-results \
  --apply-offsets
```

The tool sends offset-only requests, never an aggregate Configure request.
Each capture is triggered, allowed to settle, then read without retriggering.
It records raw unsigned samples in `captures.jsonl`, format-aware statistics
and command outcomes in `summary.json`. Reusing an existing capture file is
rejected. Seven hardware-free tests check the statistics and false-pass guards.

Final run: `offset-analog-zZjMTRp1`, 165 protocol exchanges. Raw capture SHA-256:
`3a8a500ca24b83d56b0dc694727b0a7996936aab3c0382be69872d487062dc51`.
