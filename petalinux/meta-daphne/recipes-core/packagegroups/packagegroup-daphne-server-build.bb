SUMMARY = "On-target build dependencies for daphne-server / daphneZMQ"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# packagegroup snapshots this at inheritance time. Selecting the architecture
# afterwards leaves allarch inherited and breaks renamed library dependencies.
PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

# Protobuf's CMake exports reference static utf8_validity even when its main
# libraries are shared. Include that archive for native CMake consumers.
RDEPENDS:${PN} = " \
    packagegroup-core-buildessential \
    cmake \
    git \
    pkgconfig \
    python3 \
    python3-pip \
    python3-pyzmq \
    python3-protobuf \
    python3-numpy \
    python3-matplotlib \
    python3-tqdm \
    protobuf \
    protobuf-dev \
    protobuf-staticdev \
    protobuf-compiler \
    zeromq \
    zeromq-dev \
    cppzmq-dev \
    abseil-cpp \
    abseil-cpp-dev \
    cli11-dev \
    i2c-tools \
    i2c-tools-dev \
"
