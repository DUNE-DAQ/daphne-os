# Aggregate Configure: five BIAS values, including zero

DAPHNE-015, 2026-09-09 (workstation date). Server fix **`53b6566` deployed**;
verifier `df7d441`. Self-trigger ABI 2.0 firmware remains `0x03F17F1B`.

## What changed

Configure already carries one `v_bias` per AFE ID. The server used to skip
zero-valued entries. It now applies **every present AFE's BIAS code**, including
zero, through the existing board-to-PL mapping. No new protocol field or client
wire-format change is needed. BIASCTRL handling and generator-enable policy
are unchanged.

```text
AFE IDs: [0, 1, 2, 3, 4]
BIAS:    [0, 0, 0, 0, 0]  -> five zero-BIAS commands, not five skipped writes
```

Important compatibility detail: protobuf defaults an omitted scalar `v_bias`
to zero. If its AFE entry is present, that zero is now applied. An absent AFE
entry does not generate a per-AFE BIAS command. This is still full Configure,
not a promise to preserve every other board setting.

## Verification

| Check | Result |
| --- | --- |
| Six C++ tests, native and on-board ARM64 | Pass |
| Five-AFE mapping, all 120 input permutations | 1,800 mock writes: distinct values, mixed zeros, all zeros |
| Default zero, invalid IDs/ranges/duplicates | Pass; invalid complete requests rejected before mock writes |
| Python verifier tests | 18 pass, including missing/duplicate/nonzero acknowledgement rejection |
| Direct aggregate hardware Configure | Two passes, normal and shuffled AFE order |
| Each hardware pass | Five zero-BIAS command acknowledgements; BIASCTRL and BIAS cache all zero |
| Alignment and fresh AFE register checks | All five AFEs pass after each Configure |
| Spybuffer capture | All 40 channels usable; no rail samples |

Hardware requests used AFE orders `[0,1,2,3,4]` and `[4,1,3,0,2]`, both with
all BIAS=0 and BIASCTRL=0. **No low-level bias-write workaround or nonzero bias
command was sent.** Distinct nonzero values were tested only with mock writes.
The hardware test completed 153 exchanges, exit 0.

Eight follow-up read-only protocol exchanges also pass: identity, status,
40 counters, telemetry quality and fresh register-51 reads on all five AFEs.
Timing remains not-ready on the selected local clock; voltage telemetry is
explicitly unavailable. Neither is relabelled as qualified by this patch.

Four distinct 1,024-sample waveforms/channel were captured after each setup;
baselines ranged 6460–7833 ADC counts. The reference profile remains trim=0,
offset=2200/x1, VGAIN=1700, PGA=24 dB, LNA=12 dB, 14-bit offset-binary output.
Full request dictionaries and fresh register values are saved in the report.

Command acknowledgements and cached DAC codes are **not physical bias-voltage
readback**. This qualifies zero-code handling, not nonzero-bias operation,
analog bias-voltage accuracy or full-stream operation. Earlier offset-gain
calibration limitations remain unchanged.

## Repeat, maintenance only

Use the [build/client environment](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients)
and approved local SSH forward. This command changes the full FE setup, then
aligns and captures data; it deliberately does not use the old workaround.

```bash
python daphne-server/tests/test_aggregate_zero_bias.py -v
python daphne-server/scripts/verify_aggregate_zero_bias.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B \
  --output-dir /path/to/new-zero-bias-results \
  --apply-zero-bias-configuration
```

## Deployment and evidence

The candidate passed its checksums, six ARM tests and `--help` on the board
before installation. Previous application retained at
`/usr/bin/daphneServer.pre-zero-bias-53b6566`. After verifying the service had
stopped, the binary was replaced atomically and `daphne-runtime.target` started.
This reloaded the **same** installed FPGA application; no new OS/FPGA image,
runtime libraries, service arguments or partition changes were installed.

Final server/runtime active; PID 7825, NRestarts=0. Network/MAC/IP, SSH and
firmware-environment protected checksums match. Final BIAS/BIASCTRL command
codes are zero and all channels are at 2200/x1. Server SHA-256:
`1526187ed92d59cb51f3e46555e04b67fcf78143a4ca0a52c8f17bf3873fec27`.

Evidence: `aggregate-zero-hardware-r97ckrUY`; raw capture SHA-256
`ded477cb9ae2428beeef1ffe97cc1640be6fcb2cec4c3539d9dca1688c809c24`.
ONL-home bundle `daphne015-zero-bias-53b6566.tgz` includes the server, six ARM
tests, source, verifier clients, Python protobuf modules, raw captures,
reports, commands and internal/external checksums. Previous bundles remain.
