#!/usr/bin/env bash
# Native ARM server build only. Driver is cross-built in daphne-dev/PetaLinux.
set -euo pipefail
cd "$(dirname "$0")/../.."
test "$(uname -m)" = aarch64
mkdir -p evidence
sha256sum -c SHA256SUMS > evidence/source-verification.log
{ uname -a; cmake --version; c++ --version; protoc --version; } > evidence/build-host.txt
cmake -S daphne-server -B build/dma-server -DCMAKE_BUILD_TYPE=Release \
  -DDAPHNE_BUILD_DMA_DIAG=ON -DDAPHNE_BUILD_PY_PROTO=ON \
  -DDAPHNE_ENABLE_HARDWARE_TESTS=OFF > evidence/configure.log 2>&1
cmake --build build/dma-server --parallel 2 > evidence/build.log 2>&1
ctest --test-dir build/dma-server --output-on-failure > evidence/ctest.log 2>&1
sha256sum build/dma-server/daphneServer build/dma-server/dma/daphne-afe-session-probe \
  daphne-server/kernel/daphne-afe-dma/daphne_afe_session_uapi.h \
  daphne-server/srcs/protobuf/*.proto build/dma-server/srcs/protobuf/*_pb2.py > evidence/products.sha256
python3 daphne-server/kernel/daphne-afe-dma/test_session_contract.py --output "$PWD/build/session-contract" > evidence/driver-contract.log 2>&1
python3 daphne-server/kernel/daphne-afe-dma/test_session_service.py --output "$PWD/build/session-service" > evidence/driver-service.log 2>&1
