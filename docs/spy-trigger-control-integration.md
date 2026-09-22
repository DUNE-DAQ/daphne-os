# Spy trigger control integration

## Source and destination

The integration starts from `daphne-os/develop` at
`2d5b5cd00ce84d7197ebab4de9265992c0bd80dd` and imports
`archive/daphneZMQ/feature/spy-trigger-control` at
`f8f8016f0ebeb029837caad662d3ee44c4a9d487` under `daphne-server/`.
There are 35 source commits outside the original develop history, including
12 commits after the initial archived tip `ffe3963`.

Merge commit `085782a` preserves the original commit IDs and parents. It was
created with `git merge --no-commit --no-ff -Xsubtree=daphne-server`, since
the local Git installation does not provide the optional `git subtree` command.
The two textual conflicts were resolved by retaining both the gateware and
AFE delay-sweep headers, and both branches' unit-test targets.

The imported work includes spybuffer trigger-source RPCs, freshness and readout
guards, AFE diagnostics, configuration readback, pedestal calibration, and
resumable VGAIN scans. Existing dual-gateware code and tests are retained.
The separate `fix/server-v05-register-coverage` branch is not part of this merge.

## Integration adjustments

- Accept fast-forwarded archive branches in the history checker while rejecting
  loss of their original ancestry and any change to archived tags. Six tests
  exercise real Git histories, including rewinds and unrelated replacement tips.
- Register the imported AFE delay analysis tests with CTest, alongside the other
  imported Python tests and the existing gateware tests.
- Update source provenance documentation and remove the pre-existing broken
  `TODO.md` link from the documentation index.

## Local verification

Verification ran on an x86_64 workstation without accessing DAPHNE hardware:

| Check | Result |
| --- | --- |
| Server Python unit tests | 58 passed |
| Deployment tests | 70 passed |
| PetaLinux tests | 68 passed |
| Remote tooling tests | 10 passed |
| Migration and provenance tests | 11 passed |
| Security fixture tests | 6 passed |
| Gateware mode, FPGA register dictionary, readout inhibit C++ tests | 3 executables compiled and passed |
| Original migration inventory | All 245 commits and 40 references verified |
| Documentation links, Python syntax, VGAIN shell syntax, whitespace | Passed |

Test-only dependencies were installed or built outside the repository.
The PetaLinux MAC policy test required a temporary build of `dtc` and `fdtget`;
it passed when that build's `libfdt` was supplied to the loader.

## Remaining verification

The full server uses ARM NEON. Its complete build, generated protobuf bindings,
and complete CTest run still need a native AArch64 environment or the existing
`native-server` CI job. Run from this revision on the developer image:

```bash
./scripts/server/build_native.sh ./daphne-server ./build/server-spy-trigger
```

Use a fresh build directory. No hardware qualification, runtime bundle rebuild,
deployment, or update of the pinned RC1 server binary was performed. The source
integration does not change the existing runtime qualification requirements.
