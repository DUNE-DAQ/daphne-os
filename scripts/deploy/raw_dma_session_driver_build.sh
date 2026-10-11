#!/usr/bin/env bash
# Cross-build only, using the PetaLinux project that generated the running image.
set -euo pipefail
cd "$(dirname "$0")/../.."
task_project="${PETALINUX_PROJECT:-/home/ecristal/daphne/daphne-dual-rc1-work/petalinux-dev}"
task_kdir="$task_project/build/tmp/work-shared/xilinx-k26-kr/kernel-build-artifacts"
task_release="${EXPECTED_KERNEL_RELEASE:-6.18.10-xilinx-g4f7afe14f724}"
test -f "$task_kdir/Module.symvers"
test "$(cat "$task_kdir/include/config/kernel.release")" = "$task_release"
mkdir -p evidence build
# Keep userspace tests on the host compiler before loading the cross SDK.
python3 daphne-server/kernel/daphne-afe-dma/test_session_contract.py --output "$PWD/build/session-contract" > evidence/driver-contract.log 2>&1
python3 daphne-server/kernel/daphne-afe-dma/test_session_service.py --output "$PWD/build/session-service" > evidence/driver-service.log 2>&1
task_recipe="$task_project/build/tmp/work/xilinx_k26_kr-amd-linux/linux-xlnx/6.18.10+git+v2026.1"
export CROSS_COMPILE="$task_recipe/recipe-sysroot-native/usr/bin/aarch64-amd-linux/aarch64-amd-linux-"
test -x "${CROSS_COMPILE}gcc"
{ hostname; uname -a; "${CROSS_COMPILE}gcc" --version; printf 'KDIR=%s\n' "$task_kdir"; cat "$task_kdir/include/config/kernel.release"; sha256sum "$task_kdir/.config" "$task_kdir/Module.symvers"; } > evidence/driver-build-host.txt
make -C daphne-server/kernel/daphne-afe-dma KDIR="$task_kdir" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" W=1 > evidence/module-build.log 2>&1
task_module=daphne-server/kernel/daphne-afe-dma/daphne-afe-dma.ko
modinfo "$task_module" > evidence/modinfo.txt
test "$(modinfo -F vermagic "$task_module" | cut -d ' ' -f 1)" = "$task_release"
sha256sum "$task_module" daphne-server/kernel/daphne-afe-dma/daphne_afe_session_uapi.h > evidence/driver-products.sha256
