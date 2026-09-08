# daphne-server Contract

The firmware build needs to preserve the PL/PS register contract currently used
by `daphne-server`.

## AXI map that must remain stable

From the imported block design scripts and memory map:

- `0x8000_0000`: AFE SPI control
- `0x8400_0000`: timing endpoint control
- `0x8800_0000`: frontend alignment / trigger control
- `0x8C00_0000`: DAC SPI control
- `0x9000_0000`: spy buffer window
- `0x9400_0000`: general config + trigger masks
- `0x9800_0000`: Hermes/10G sender
- `0x9C00_0000`: AXI IIC
- `0x9C01_0000`: AXI interrupt controller
- `0x9C02_0000`: AXI Quad SPI
- `0xA000_0000`: output buffer
- `0xA001_0000`: per-channel self-trigger threshold window

## Specific register behavior used by the server

- `frontendTrigger` corresponds to `0x8800_0008` and is pulsed with `0xBABA`
  for spy-buffer snapshots.
- Trigger enable masks are expected at `0x9400_0020` and `0x9400_0024`.
- Threshold registers are expected at `0xA001_0000` with a stride of `0x20`
  per channel.
- Endpoint status/control are expected relative to `0x8400_0000`.

## Software/runtime dependencies expected on the target

From the current `daphne-server` build:

- CMake
- a C++17 compiler
- ZeroMQ runtime (`libzmq`) plus `cppzmq` headers
- Protobuf library plus `protoc`
- `CLI11` headers
- `libi2c`

The pinned standalone runtime tarball is mirrored into
`petalinux/daphne-server-deps.lock.cmake`.

## Deployment implication

Any future board port or register-map cleanup in this repo should be checked
against:

- `daphne-server/README.md`
- `daphne-server/srcs/FpgaRegDict.cpp`
- `daphne-server/srcs/server_controller/handlers.cpp`

The current HDL smoke coverage in this repo exercises the threshold window and
the frontend trigger register path used for spy-buffer snapshots.
