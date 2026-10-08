# AFE0 CH0 synthetic SiPM configuration

The optional `afe0-synthetic` firmware profile injects synthetic SiPM pulses into
AFE0 CH0. The server configures only `SYN_CONFIG` at `0x94000050`; AFE0 CH1..7
are unchanged. This feature does not configure AFEs, alignment, bias, trigger
masks, spybuffer trigger source, or acquisition. General bring-up and alignment
of the reduced AFE profile remain separate from this register RPC.

Firmware authority: `daphne-firmware/docs/synthetic_sipm_generator.md`.

## V2 protocol

Send `ConfigureSyntheticSipmRequest` with message type
`MT2_CONFIGURE_SYNTHETIC_SIPM_REQ` (332):

- `amplitude_q8`: integer `round(A * 256)`, inclusive range 256..2560000.
  The amplitude is the filter excitation in ADC units, not a guaranteed output
  peak. Values are quantized to 1/256 ADC unit.
- `model`: `SYNTHETIC_SIPM_FBK` (0) or `SYNTHETIC_SIPM_HPK` (1).
- `enable`: false for bypass/cleared history, true to accept software events.

Every request specifies the complete configuration. Missing amplitude defaults
to zero and is rejected; the proto3 defaults for model and enable are FBK and
disabled. Invalid amplitude or model is rejected before MMIO access.

The response type is `MT2_CONFIGURE_SYNTHETIC_SIPM_RESP` (333), with payload
`SyntheticSipmConfigResponse`: `success`, `message`, `amplitude_q8`, `model`,
`enable`, and `raw_register`. Configuration fields are meaningful only on
success. FBK A=22.5 enabled reads `0x00801680`; HPK reads `0x00C01680`.

For a read-only query, send `ReadSyntheticSipmConfigRequest` with
`MT2_READ_SYNTHETIC_SIPM_CONFIG_REQ` (334). The response uses the same payload
and type `MT2_READ_SYNTHETIC_SIPM_CONFIG_RESP` (335).

## Server sequencing

The synchronous server handles the entire sequence within one RPC:

1. Read the old register and clear ENABLE while retaining its parameters.
2. Write the new amplitude/model with ENABLE=0.
3. If requested, write the same parameters with ENABLE=1.

Each write is a full, ordered 32-bit MMIO store, followed by readback verification
and a conservative 1 us wait. The firmware requires at least 80 ns between steps
and before triggering. The final wait completes before the response. AXI
readback confirms register storage, not acquisition-domain application: there
is no SYN_STATUS or apply acknowledgement. The acquisition clock must be running.

Every configuration call clears filter history, even with unchanged parameters.
On an access/verification failure, the server attempts to disable using the old
parameters and reports the error, including failure to verify that disabled
state. It does not restore an enabled configuration.

The default `full` profile reads zero and ignores writes at this address. A
valid nonzero amplitude cannot verify there, so configuration fails before any
enable write. A zero read is reported as unavailable or invalid configuration;
it cannot distinguish absent hardware from present hardware externally set to
zero. A configuration request can repair the latter. No startup capability
probe or configuration write is introduced.

Software events continue to use `MT2_DO_SOFTWARE_TRIGGER_REQ` and the existing
frontend trigger register `0x88000008`. The synchronized trigger must return low
between events. Spy source/inhibit do not gate synthetic excitation, so other
operations issuing software triggers (including diagnostics) can excite the
generator while it is enabled. The synthetic contribution begins three sample
clocks (48 ns) after the synchronized trigger rising edge.

## Validation

`synthetic_sipm_unit` uses fake MMIO and acquisition-domain settling to check
encoding, range/model rejection without access, disable/write/enable ordering,
history clearing, waits, read-only queries, unsupported firmware, write/read
failures, and best-effort disable. Run it through the hardware-free native build:

```sh
ctest --test-dir build/server-native --output-on-failure -R synthetic_sipm_unit
```

Regenerate C++ and Python protobuf bindings through the normal CMake build.
These tests do not qualify a bitstream or demonstrate pulses on a board.
