# v0.5 Server Platform: complete row assessment

All **251 rows** are now individually assessed in the
[spreadsheet-friendly CSV](server-v05-row-audit.csv). The
[provenance and evidence groups](server-v05-row-audit.json) define each source,
test scope and limitation. The original XLSX is unchanged.

Source snapshot: **fb82e0a**, correcting Configure's implicit SC-enable write;
33 host/33 actual ARM suites and 216 Python tests per binding pass. This candidate
is not deployed. Installed server: **4e74f10**, adding AFE-reset health assessment;
its clean/native tests, standalone probes and full live RPC regression pass.
DAPHNE-015 retains unchanged self-trigger firmware
**3f17f1b / ABI 2.0**. Native and live RPC/full regression, the complete runtime
and image pin/35-file ONL handoff pass. This audit is
not a full-workbook completion claim.

| Assessment | Rows | Meaning |
| --- | ---: | --- |
| Implemented | 90 | Concrete producer/export provides the observation within its stated scope |
| Partial | 92 | Related code exists, but semantics, readback, quality, completeness or retained reporting are missing |
| Missing | 56 | No corresponding server observation; a schema field/internal helper is not enough |
| Contract pending | 13 | Authority, authenticated identity, lease/safety or boot-recovery policy must be established |

**Implemented does not mean hardware-qualified everywhere.** Every row retains
the workbook's exact meaning, mode and priority, plus its mapping and remaining
work. Conditional RPU/mezzanine/transceiver requirements are not discarded.
No full-stream, new routed ABI 2.1/2.2 firmware, complete image, absolute-current
calibration or overall FPGA-health qualification is inferred.

## Important findings

- **SC003/I288 ownership:** candidate fb82e0a leaves BiasEnable untouched by
  aggregate Configure and fingerprints that no enable command was issued.
  The old installed server still forces enable. Live preservation and the
  dedicated/authenticated SC request contract remain open; see
  [correction and verification scope](sc-bias-enable-ownership.md).
- **I283–I288, AFE global state:** the candidate now supplies admitted,
  bracketed read-only register observations with quality/times; two native
  probes passed. [AFE readback evidence](afe-global-readback-verification.md)
  separates SC-owned BiasEnable from the cached BIASCTRL DAC setpoint.
  Live RPC/full regression and runtime checks now pass; physical transitions
  and full-stream/new-firmware qualification remain separate.
- **I284, reset-health follow-up:** deployed 4e74f10 derives a sixteenth
  prerequisite from qualified readback, without SC bias/power policy changes.
  33 host/33 actual ARM suites, 208 Python tests per binding and two native
  probes and full live RPC regression pass. Runtime/native loader and image pin
  and 35-file ONL handoff/five exported clients pass. See
  [verification and scope](afe-reset-health-verification.md).
- **I207–I214, mezzanine samples:** independent cached atomics have no coherent
  quality/time; monitor exceptions can leave old values visible. No mezzanines
  are fitted on this bench, so physical qualification remains unavailable.
- **I225/I226, mezzanine calibration:** `getShuntCal()` returns cached codes,
  not fresh INA232 calibration-register readback.
- **I029–I040, command audit:** the existing record covers Configure, not every
  accepted/rejected mutation. ZMQ routing identity is not authentication.
- **I249–I257, fans, and I159–I173, I2C inventory:** schema/internal helpers exist,
  but the corresponding general status collectors are not populated.
- **I108/I109, services:** systemd restart count is not guaranteed boot-lifetime
  history; monotonic start timestamps are not UTC event times.
- **I144, schema compatibility:** hashes and envelope version are reported;
  they are not a semantic compatibility policy. **I238** needs the workbook's
  Mbps label reconciled with the SFP's reported MBd signaling rate.

These distinctions refine the earlier selected-issue
[coverage report](server-v05-register-coverage.md); its historical test counts
and deployment evidence are retained, not retroactively upgraded.

## Next implementation order

First finish the [SC-enable correction's live maintenance and handoff gates](sc-bias-enable-ownership.md)
without reloading firmware or changing SC state. The producer backlog remains:

1. **AFE reset-health implementation/handoff is qualified on ABI 2.0**:
   deployed 4e74f10, full regression, runtime/native loader, image pin and ONL
   clients pass. Physical transitions and full-stream remain separate gaps;
   proceed with the missing producers below without changing SC policy.
2. Correct **mezzanine cache quality/time and calibration provenance** with
   deterministic tests. Keep no-mezzanine behavior explicitly unavailable;
   hardware readback/metrology needs populated hardware.
3. Add **read-only fan command/raw tach** observations after checking the exact
   deployed RTL and board wiring. RPM, presence and stall claims need validated
   pulse/scaling/population and an approved minimum-speed policy; no PWM writes.
4. Add **I2C/SPI transaction bookkeeping** at actual serializers, with honest
   process/boot/reset scope. No broad scans, bus recovery or device-control writes.
5. Fill **identity/network/service metadata** gaps from approved sources with
   private opt-ins. Preserve CERN MAC/IP/DHCP/SSH. Do not invent missing DB values.
6. Keep authority/lease/safe-state and corruption-recovery proposals separate
   until their enforcement and recovery contracts are established.

The original objective is wider than this sheet. Assigned crate/slot/detector,
management address and one Hermes MAC/IP assignment are already reported from
the verified private artifact. Approved timing-endpoint/management-MAC assignments
and physical Hermes mapping remain missing. ADS1261 raw readout, provisional
temperature alarms and sampled FPGA health are implemented; current calibration,
the suspect SFP wiring/population and actual firmware/full-stream qualification
remain open. See the [full objective ledger](server-v05-completion-plan.md).

## Check completeness and provenance

```bash
python3 scripts/check_server_v05_audit.py
python3 -m unittest discover -s tests/petalinux -p test_server_v05_audit.py -v
```

To compare against the original user-provided inputs, set explicit paths:

```bash
python3 scripts/check_server_v05_audit.py \
  --workbook "$V05_WORKBOOK" --source-export "$V05_SERVER_EXPORT"
```

All 251 IDs/meanings/row positions and **all 30 worksheet/export columns** match
the hash-pinned inputs. The checker verifies 55 reviewed code-file hashes and
all evidence references; 12 positive/negative tests pass. The source XLSX
SHA-256 is `7c58f7f469523b7dd69ff3836f43d1a59bffdae49e2925bb328ac182122d8fd8`.
No extra Python packages are needed. The checker is read-only and does not
independently prove the human semantic assessments or rerun hardware tests.
