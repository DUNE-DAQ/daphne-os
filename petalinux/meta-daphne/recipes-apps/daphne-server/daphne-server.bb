SUMMARY = "Prebuilt DAPHNE runtime payload"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

DEPENDS += "patchelf-native"

require daphne-server-contract.inc
require daphne-server-version.inc
# Cross-recipe version input: changing either staged overlay invalidates the
# server task signature and rechecks compatibility, regardless of staging order.
require recipes-firmware/daphne-overlay/daphne-overlay-version.inc

python validate_daphne_server_runtime () {
    import re

    if d.getVar("DAPHNE_SERVER_RUNTIME_QUALIFIED") != "1":
        bb.fatal(
            "A dual-gateware-compatible daphne-server bundle must be staged with "
            "scripts/petalinux/stage_runtime_into_project.sh before building daphne-server"
        )

    expected_commit = d.getVar("DAPHNE_SERVER_REQUIRED_GIT_COMMIT") or ""
    staged_commit = d.getVar("DAPHNE_SERVER_RUNTIME_GIT_COMMIT") or ""
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        bb.fatal("Malformed daphne-server source commit contract")
    if staged_commit != expected_commit:
        bb.fatal(
            f"Staged daphne-server commit {staged_commit!r} does not match "
            f"the release contract {expected_commit!r}"
        )

    if d.getVar("DAPHNE_SERVER_RUNTIME_EXECUTION_KIND") not in ("native-aarch64", "qemu-aarch64"):
        bb.fatal("Staged runtime lacks an explicit ARM execution method; restage the runtime with its validation record")

    expected_abi = d.getVar("DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MAJOR") or ""
    staged_abi = d.getVar("DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MAJOR") or ""
    if expected_abi != "2" or staged_abi != expected_abi:
        bb.fatal(
            f"Staged daphne-server ABI {staged_abi!r} does not match "
            f"the gateware ABI contract {expected_abi!r}"
        )

    expected_minors = d.getVar("DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS") or ""
    staged_minors = d.getVar("DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS") or ""
    if expected_minors not in ("0", "1", "0 1") or staged_minors != expected_minors:
        bb.fatal("Staged daphne-server ABI minor capabilities do not match the reviewed source contract; restage the runtime")

    if d.getVar("DAPHNE_DUAL_OVERLAY_STAGED") != "1":
        bb.fatal("Both gateware overlays must be staged before validating server/image compatibility")
    for prefix, mode in (("DAPHNE_SELF_TRIGGER", "self-trigger"),
                         ("DAPHNE_FULL_STREAM", "full-stream")):
        # Only pre-extension stagers omit the minor; those bundles are ABI 2.0.
        minor = d.getVar(prefix + "_ABI_MINOR")
        if minor is None:
            minor = "0"
        if minor not in expected_minors.split(" "):
            bb.fatal(f"The pinned daphne-server does not support {mode} overlay ABI 2.{minor}; qualify and stage a compatible server runtime")
        if minor == "1" and d.getVar(prefix + "_IDENTITY_SEALED") != "1":
            bb.fatal(f"The {mode} ABI 2.1 overlay lacks its sealed identity declaration")

    runtime_sha = d.getVar("DAPHNE_SERVER_RUNTIME_SHA256") or ""
    if re.fullmatch(r"[0-9a-f]{64}", runtime_sha) is None:
        bb.fatal("DAPHNE_SERVER_RUNTIME_SHA256 is not a lowercase SHA-256 digest")
}

do_fetch[prefuncs] += "validate_daphne_server_runtime"
# The guard constructs these getVar names; make task dependencies explicit so
# changing only the inactive variant cannot reuse a prior successful task.
validate_daphne_server_runtime[vardeps] += " \
    DAPHNE_SELF_TRIGGER_ABI_MINOR DAPHNE_FULL_STREAM_ABI_MINOR \
    DAPHNE_SELF_TRIGGER_IDENTITY_SEALED DAPHNE_FULL_STREAM_IDENTITY_SEALED \
"

RDEPENDS:${PN} += " \
    i2c-tools \
    zlib \
"

SRC_URI += " \
  file://README.server \
  file://staged/BUILD-METADATA.txt \
  file://staged/SHA256SUMS \
  file://staged/daphne-server-runtime-minimal.tgz;unpack=0 \
"

PACKAGE_ARCH = "${MACHINE_ARCH}"

FILES_SOLIBSDEV = ""
INSANE_SKIP:${PN} += "dev-so rpaths"

DAPHNE_RUNTIME_LIBDIR = "${libdir}/daphne-server"

do_install() {
    runtime_manifest="${WORKDIR}/staged/SHA256SUMS"
    runtime_artifact="daphne-server-runtime-minimal.tgz"

    verify_manifest_path_once() {
        manifest="$1"
        checksum_path="$2"
        match_count="$(awk -v path="$checksum_path" '
            {
                name = $2
                sub(/^\*/, "", name)
                if (NF == 2 && name == path) count += 1
            }
            END { print count + 0 }
        ' "$manifest")"
        if [ "$match_count" != "1" ]; then
            bbfatal "$manifest must contain exactly one checksum for $checksum_path (found $match_count)"
        fi
    }

    for checksum_path in "$runtime_artifact" BUILD-METADATA.txt; do
        verify_manifest_path_once "$runtime_manifest" "$checksum_path"
    done
    expected_sha="$(awk -v path="$runtime_artifact" '
        {
            name = $2
            sub(/^\*/, "", name)
            if (NF == 2 && name == path) print $1
        }
    ' "$runtime_manifest")"
    actual_sha="$(sha256sum ${WORKDIR}/staged/daphne-server-runtime-minimal.tgz | awk '{print $1}')"
    if [ -z "${expected_sha}" ] || [ "${actual_sha}" != "${expected_sha}" ]; then
        bbfatal "DAPHNE runtime bundle checksum verification failed"
    fi
    if [ "${actual_sha}" != "${DAPHNE_SERVER_RUNTIME_SHA256}" ]; then
        bbfatal "DAPHNE runtime bundle does not match daphne-server-version.inc"
    fi
    (cd ${WORKDIR}/staged && sha256sum --check --strict SHA256SUMS) || \
        bbfatal "DAPHNE staged runtime checksum set verification failed"

    runtime_root="${WORKDIR}/runtime-root"
    rm -rf "${runtime_root}"
    install -d "${runtime_root}"
    tar -xzf "${WORKDIR}/staged/daphne-server-runtime-minimal.tgz" \
        -C "${runtime_root}"
    deps_root="${runtime_root}/home/petalinux/daphne-server/build-petalinux/_deps"
    lib_src_dir="$(find "${deps_root}" -mindepth 3 -maxdepth 3 -type d -path '*/prefix/lib' | sort | head -n 1)"
    if [ -z "${lib_src_dir}" ]; then
        bbfatal "Could not locate daphne-server dependency lib directory under ${deps_root}"
    fi

    install -d ${D}${bindir}
    install -d ${D}${DAPHNE_RUNTIME_LIBDIR}
    install -d ${D}${datadir}/daphne-server

    install -m 0755 "${runtime_root}/bin/hermes_udp_srv" \
        ${D}${bindir}/hermes_udp_srv
    install -m 0755 "${runtime_root}/home/petalinux/daphne-server/build-petalinux/daphneServer" \
        ${D}${bindir}/daphneServer

    for lib in \
        libprotobuf.so \
        libprotobuf.so.30.1.0 \
        libutf8_validity.so \
        libutf8_validity.so.30.1.0 \
        libzmq.so \
        libzmq.so.5 \
        libzmq.so.5.2.4; do
        install -m 0644 "${lib_src_dir}/${lib}" "${D}${DAPHNE_RUNTIME_LIBDIR}/${lib}"
    done

    ${STAGING_BINDIR_NATIVE}/patchelf \
        --set-rpath ${DAPHNE_RUNTIME_LIBDIR} \
        ${D}${bindir}/daphneServer

    install -m 0644 ${WORKDIR}/README.server \
        ${D}${datadir}/daphne-server/README.server
    install -m 0644 ${WORKDIR}/staged/BUILD-METADATA.txt \
        ${D}${datadir}/daphne-server/BUILD-METADATA.txt
}

FILES:${PN} += " \
    ${bindir}/daphneServer \
    ${bindir}/hermes_udp_srv \
    ${libdir}/daphne-server/* \
    ${datadir}/daphne-server/README.server \
    ${datadir}/daphne-server/BUILD-METADATA.txt \
"
