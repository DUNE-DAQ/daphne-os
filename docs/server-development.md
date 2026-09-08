# Server development

The server source is [daphne-server/](../daphne-server/). Its CMake project is
self-contained in that directory. It is the unchanged source tree from
`ecristal/daphneZMQ@77b39b7eb75204e1f2025f251a3a76ecf69d1d74` at import.

## Build inside DAPHNE

The PetaLinux `developer` profile includes native GCC/G++, CMake, `protoc`,
ZeroMQ, Protobuf development libraries, and Python client dependencies.
The `minimal` image is not a native development environment.

From a clone of `daphne-os` on the board:

```bash
./scripts/server/build_native.sh ./daphne-server ./build/server-native
```

Choose a new build directory for the initial build. After editing sources:

```bash
cmake --build build/server-native --parallel 2
ctest --test-dir build/server-native --output-on-failure -L unit
```

Hardware tests remain disabled. The helper clears private runtime library
overrides so matching system headers, `protoc`, and libraries are used. It
does not replace the qualified service binary or switch FPGA applications.

The full server uses ARM NEON and is not an x86 workstation target. CI runs
this same helper on a native AArch64 runner, including both hardware-free
unit tests and generated client binding imports.

The pre-split developer image was validated with its actual AArch64 compiler
under QEMU/PRoot on Cooper, including both server unit tests. That was not a
physical-board build or hardware qualification. Repository migration likewise
does not qualify new images or custom binaries.

## Generate client protobuf files

Run from the imported server directory, using a compatible `protoc` and Python
protobuf runtime:

```bash
cd daphne-server
protoc -I srcs/protobuf --python_out=srcs/protobuf \
  srcs/protobuf/daphneV3_high_level_confs.proto \
  srcs/protobuf/daphneV3_low_level_confs.proto
```

The normal CMake build generates both C++ bindings and Python modules into its
build tree. With the native build path above, Python modules are in
`build/server-native/srcs/protobuf/` relative to the OS repository.

## Installing a custom server

Compilation is separate from installation. Coordinate the maintenance window,
preserve the previous binary and service configuration, and retain the
`daphne.service` gateware mode/ABI/build-ID arguments and runtime dependencies.
Use [the runtime runbook](dual-gateware-deployment.md) to stop and verify the
complete service chain. Do not overwrite the running binary or start a second
server against live hardware as part of a build.

The image staging recipe still requires the pinned, qualified RC1 runtime
contract. Do not label an edited server as the unchanged `77b39b7` release to
bypass that check. Requalifying a custom runtime is a separate release action.
