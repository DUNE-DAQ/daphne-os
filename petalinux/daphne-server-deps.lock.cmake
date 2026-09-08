# Synced from the current `daphne-server` checkout so firmware deployment and
# server deployment can use the same pinned runtime dependency bundle.
#
# Update this file together with the corresponding lockfile in `daphne-server`
# whenever protobuf / zeromq / supporting runtime headers are repackaged.

set(DAPHNE_DEPS_TARBALL_NAME "daphne-deps-petalinux2024.1-aarch64-glibc2.36-protobuf30.1-zeromq4.3.4.tar.gz")
set(DAPHNE_DEPS_TARBALL_SHA256 "109de97c1b635989fec9822927847edcf5bfd122b21084ec2dee673b63f9267c")
