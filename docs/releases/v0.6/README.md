# v0.6 register checkpoint — DAPHNE-015

**Deployed server: `a23e5a9`.** Firmware remains self-trigger `3f17f1b`, ABI 2.0.
CERN network/identity settings, runtime/Hermes and SC BiasEnable=1 were preserved.
BIAS and BIASCTRL remain zero. Only the server executable was replaced.

[Download the v0.6 workbook](DAPHNE_Operations_Variable_Ownership_Draft_v0.6.xlsx).
The original v0.5 file is untouched. The new workbook keeps every original row,
updates Server Platform, and adds **Server Open Issues**, **Server Resolved**
and **v0.6 Release Notes** tabs.

- **102 resolved implementation rows:** their open implementation action is cleared.
- **149 open rows:** 85 partial, 51 missing and 13 contract-pending.
- Qualification limits remain visible even on resolved rows. Non-server domains
  and cross-domain summaries retain their v0.5 assessments; they are not newly certified.

## Delivered

ADS1261 raw 40-channel reads; server bookkeeping; available identity assignments;
temperature alarms; regulator/SFP telemetry; FPGA/AFE readback; SC-preserving
Configure; coherent no-mezzanine reporting; and now shared fan PWM/raw tach reads.
Build/image staging is pinned to the deployed server source, not the older runtime.

Verification: **35 host + 35 actual ARM suites; 246 Python tests per binding;
144 packaging tests.** Native fan probes, deployed fan RPCs, 158-exchange
zero-bias/all-channel test, busy-Configure bookkeeping, six collector regressions,
metadata clients and no-mezzanine RPC/CLI checks pass.
The [deployment record](deployment.json) states the exact binary hash and scope.
Health still reports **12 PASS / 1 external-timing FAIL / 3 UNKNOWN**.

The [verified runtime/report bundle](onl-handoff.json) is saved on ONL at
`/nfs/home/marroyav/daphne015-server-v0.6-a23e5a9` (owner-only; SHA256SUMS included).
It contains the exact deployed userspace binary and unchanged dependencies,
not a new bootable OS/firmware image. Existing bundles were not overwritten.
The actual archive passes runtime staging with the new pin; no image build is inferred.

## Still missing

- Calibrated ADC current/analog verification; fitted-mezzanine protection and actual Qt testing.
- Approved timing endpoint/management MAC assignments and physical Hermes-link mapping.
- Population/wiring confirmation for three unanswered SFP paths.
- Physical fan RPM, source sample timestamp, presence/stall policy and control ownership.
- Complete I2C/SPI transaction counters and mutation-wide command auditing.
- Authenticated SC requests, leases and agreed safety/protection contracts.
- Routed ABI 2.1/2.2 firmware, full-stream and complete-image qualification. No Cooper synthesis job has run.
- Proven corrupted-slot failover/network recovery for underground operation without JTAG.

The detailed row-by-row remainder is in the workbook, not hidden by the green rows.

## Reproduce the workbook

Use Python with `openpyxl==3.1.5`; supply the original hash-pinned v0.5 workbook.
No board access or private network configuration is required:

```bash
python3 scripts/build_register_workbook_v06.py \
  --v05 "$DAPHNE_V05_WORKBOOK" \
  --audit-csv docs/server-v05-row-audit.csv \
  --audit-json docs/server-v05-row-audit.json \
  --deployment-proof docs/releases/v0.6/deployment.json \
  --output /tmp/DAPHNE_Operations_Variable_Ownership_Draft_v0.6.xlsx
```

The builder refuses overwrites and verifies all original non-server cell values,
row IDs, 251 server rows, resolved/open counts and retained qualification notes.
This is a checked XLSX artifact; an interactive Excel rendering was not tested.
