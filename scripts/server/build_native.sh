#!/usr/bin/env bash
# Compile and test only. Never install a binary, open MMIO, or change a service.
set -euo pipefail
if [[ $# != 2 ]]; then
    echo "Usage: $0 SERVER_SOURCE_DIR NEW_BUILD_DIR" >&2
    exit 2
fi
case "$(uname -m)" in
    aarch64|arm64) ;;
    *) echo 'Run this script inside the AArch64 DAPHNE developer image.' >&2; exit 2 ;;
esac
source_dir=$(CDPATH='' cd -- "$1" && pwd)
build_dir=$2
test -f "$source_dir/CMakeLists.txt"
if [[ -e "$build_dir" ]]; then
    echo 'Choose a new build directory; existing build trees are not overwritten.' >&2
    exit 2
fi
for tool in gcc g++ make cmake ctest protoc pkg-config python3; do
    command -v "$tool" || {
        echo "Missing required native build tool: $tool" >&2
        exit 2
    }
done
case "$(g++ -dumpmachine)" in
    aarch64*) ;;
    *) echo 'The selected compiler does not target AArch64.' >&2; exit 2 ;;
esac
# Use matching system headers, protoc, and libraries, not private runtime libs.
unset LD_LIBRARY_PATH CMAKE_PREFIX_PATH CMAKE_TOOLCHAIN_FILE
gcc --version
g++ --version
cmake --version
protoc --version
pkg-config --modversion protobuf libzmq
cmake -S "$source_dir" -B "$build_dir" -G 'Unix Makefiles' \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_COMPILER="$(command -v g++)" \
    -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
    -Dprotobuf_MODULE_COMPATIBLE=ON \
    -DDAPHNE_DEPS_TARBALL_DIR= \
    -DDAPHNE_BUNDLE_ZEROMQ=OFF \
    -DDAPHNE_BUILD_SERVER=ON \
    -DDAPHNE_BUILD_PY_PROTO=ON \
    -DBUILD_TESTING=ON \
    -DDAPHNE_ENABLE_HARDWARE_TESTS=OFF
cmake --build "$build_dir" --parallel "${DAPHNE_BUILD_JOBS:-2}"
ctest --test-dir "$build_dir" --output-on-failure --no-tests=error -L unit
"$build_dir/daphneServer" --help
python3 - "$build_dir/srcs/protobuf" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import daphneV3_high_level_confs_pb2
import daphneV3_low_level_confs_pb2
import zmq
print("Generated Python protobuf imports and pyzmq: PASS")
PY
printf 'NATIVE_DAPHNE_SERVER_BUILD=PASS\nbinary=%s/daphneServer\n' "$build_dir"
