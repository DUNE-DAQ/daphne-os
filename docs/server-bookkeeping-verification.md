# Server bookkeeping: DAPHNE-015 qualification

Server source `d0e6e1f`, client test `e1e059c`, self-trigger ABI 2 firmware
`0x03F17F1B`. This is an application update, not a new FPGA or boot image.

## What changed

- The ROUTER thread answers bookkeeping request **326**, response **327**,
  while one separate worker serializes hardware commands. Status is therefore
  observable during Configure; hardware commands are not run in parallel.
- `ServerState` reports process/boot identity, a one-second router heartbeat,
  executor request IDs, configuration progress and the last correlated result.
- A successful complete 40-channel/five-AFE Configure records SHA-256 of
  canonical executed settings, admitted FPGA identity and selected hardware
  readbacks. Equivalent AFE order and legacy gain 0/x1 normalize identically.
  A caller-supplied hash is never accepted as evidence.
- Rejected aggregate preflight preserves previous valid evidence. Once writes
  begin, failure invalidates it. Direct control writes, relevant resets and
  known protective actions invalidate it. Restart begins without valid evidence.
- `ControlEnvelopeV2.transport_error` reports executor/dispatch errors. Clients
  must check it before decoding payloads; an empty failed payload is not zero.

The digest is **command evidence, not analog calibration**. Validity covers
known local invalidations, not every possible external reset. Heartbeat means
router progress, not FPGA/timing health. Wall-clock timestamps remain unverified;
use monotonic times with the process and boot IDs. The ordinary SystemStatus
request still queues behind hardware work; use request 326 for responsive status.

## Verification

All 13 native C++ suites and their 13 ARM builds passed on the board. Coverage
includes heartbeat/restart, correlation, partial/preflight/post-write outcomes,
protective-event races, SHA-256 vectors, canonicalization, serialized execution,
bounded queues and shutdown under reply backpressure. Five new Python tests pass.
Fault-injection and restart-state tests are hardware-free; no board power or
nonzero-BIAS fault was introduced.

Live maintenance qualification passed:

- Full zero-BIAS configuration in normal and shuffled AFE order; 16 in-progress
  observations and three heartbeat advances per configuration.
- Maximum bookkeeping round trip **267 ms**, including the CERN SSH path.
- Same SHA-256 for both equivalent configurations.
- Invalid gain=3 rejected before writes, preserving the previous hash/validity.
- Rewriting channel 0's existing offset invalidated aggregate evidence; the
  following full Configure restored valid evidence.
- The aggregate regression passed all 153 exchanges: both AFE orders, five-AFE
  alignment and fresh register reads, and four unclipped 1024-sample captures on
  every one of the 40 channels per order. The carrier/service suite passed 16
  further exchanges, including rejected requests; applied evidence stayed valid.
- All four named temperature observations and ten voltage readings remained
  available. The server stayed active with zero automatic restarts. External
  timing remained not ready (local-clock bench setup), not falsely healthy.

## Repeat

Build server and matching Python protobufs using the
[build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
With the approved localhost SSH forward, the default check is read-only:

```bash
python daphne-server/scripts/verify_server_bookkeeping.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B
```

Add `--apply-zero-bias-configuration` only during the authorized maintenance
window. It applies the full reference FE profile twice with BIAS=0, BIASCTRL=0,
offset=2200/x1, trim=0 and VGAIN=1700; it retains the existing enable policy.
It also rewrites that same channel-0 offset once to test invalidation. After any
runtime restart, restore the full FE setup before alignment. Follow with the
[aggregate/all-channel test](aggregate-bias-verification.md) and
[carrier/service checks](carrier-telemetry-and-services-verification.md).

## Deployment evidence

Evidence directory: `completion-VEpMKkGG`. Candidate SHA-256:
`c0f28a628c9cab628c8d3acd92585de3e420df7399e5aebcf5732ee2fe65abe4`.
Raw capture SHA-256:
`5e5baae12b0ac79599403f8d48bf6a19263ccc760a277d926bf603348c21227e`.
The old binary is retained as `/usr/bin/daphneServer.pre-bookkeeping-d0e6e1f`.
The candidate was checksummed and tested on ARM before a stopped-service atomic
replacement. The runtime target then reloaded the same FPGA application.
All eight protected network, SSH, firmware-selector and board-env files matched
their original checksums before and after the update. No network identity,
DHCP policy, population declaration or generator-enable policy was changed.

Remaining work is tracked in [the completion plan](server-v05-completion-plan.md).
This qualification does not establish full-stream hardware operation, external
timing readiness, detection of every external reset, or analog gain accuracy.
