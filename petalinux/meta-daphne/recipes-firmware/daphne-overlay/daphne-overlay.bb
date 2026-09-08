SUMMARY = "DAPHNE immutable self-trigger and full-stream FPGA apps"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit allarch

require daphne-overlay-version.inc

python validate_dual_overlay () {
    import re

    if d.getVar("DAPHNE_DUAL_OVERLAY_STAGED") != "1":
        bb.fatal(
            "Both qualified gateware bundles must be staged with "
            "scripts/petalinux/stage_overlay_into_project.sh before building daphne-overlay"
        )

    contracts = (
        ("DAPHNE_SELF_TRIGGER_APP", "daphne_selftrigger_ol", "DAPHNE_SELF_TRIGGER_FIRMWARE_NAME"),
        ("DAPHNE_FULL_STREAM_APP", "daphne_fullstream_ol", "DAPHNE_FULL_STREAM_FIRMWARE_NAME"),
    )
    for app_var, app_prefix, firmware_var in contracts:
        app = d.getVar(app_var) or ""
        firmware_name = d.getVar(firmware_var) or ""
        match = re.fullmatch(rf"{app_prefix}_([0-9a-f]{{7}})", app)
        if match is None:
            bb.fatal(f"{app_var} is not an immutable SHA7 app name: {app!r}")
        expected_firmware_name = f"{app}.bin"
        if firmware_name != expected_firmware_name:
            bb.fatal(
                f"{firmware_var}={firmware_name!r} does not match {app_var}={app!r}"
            )
}

do_fetch[prefuncs] += "validate_dual_overlay"

SRC_URI += " \
  file://README.overlay \
  file://staged/self-trigger/BUILD-METADATA.txt \
  file://staged/self-trigger/${DAPHNE_SELF_TRIGGER_APP}.dtbo \
  file://staged/self-trigger/${DAPHNE_SELF_TRIGGER_APP}.bin \
  file://staged/self-trigger/shell.json \
  file://staged/self-trigger/SHA256SUMS \
  file://staged/full-stream/BUILD-METADATA.txt \
  file://staged/full-stream/${DAPHNE_FULL_STREAM_APP}.dtbo \
  file://staged/full-stream/${DAPHNE_FULL_STREAM_APP}.bin \
  file://staged/full-stream/shell.json \
  file://staged/full-stream/SHA256SUMS \
"

do_install() {
    firmware_dir="${D}${nonarch_base_libdir}/firmware"

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

    install -d "${firmware_dir}/xilinx"
    install -d ${D}${datadir}/daphne-firmware
    install -m 0644 ${WORKDIR}/README.overlay \
        ${D}${datadir}/daphne-firmware/README.overlay

    install_app() {
        app="$1"
        mode="$2"
        firmware_name="$3"
        source_dir="${WORKDIR}/staged/${mode}"
        app_dir="${firmware_dir}/xilinx/${app}"

        for checksum_path in "${app}.bin" "${app}.dtbo" shell.json BUILD-METADATA.txt; do
            verify_manifest_path_once "${source_dir}/SHA256SUMS" "$checksum_path"
        done
        (cd "${source_dir}" && sha256sum --check --strict SHA256SUMS)
        install -d "${app_dir}"
        install -m 0644 "${source_dir}/BUILD-METADATA.txt" "${app_dir}/BUILD-METADATA.txt"
        install -m 0644 "${source_dir}/SHA256SUMS" "${app_dir}/SHA256SUMS"
        install -m 0644 "${source_dir}/shell.json" "${app_dir}/shell.json"
        install -m 0644 "${source_dir}/${app}.bin" "${app_dir}/${app}.bin"
        install -m 0644 "${source_dir}/${app}.dtbo" "${app_dir}/${app}.dtbo"
        ln -snf "xilinx/${app}/${app}.bin" "${firmware_dir}/${firmware_name}"
    }

    install_app \
        "${DAPHNE_SELF_TRIGGER_APP}" \
        self-trigger \
        "${DAPHNE_SELF_TRIGGER_FIRMWARE_NAME}"
    install_app \
        "${DAPHNE_FULL_STREAM_APP}" \
        full-stream \
        "${DAPHNE_FULL_STREAM_FIRMWARE_NAME}"
}

FILES:${PN} += " \
    ${datadir}/daphne-firmware/README.overlay \
    ${nonarch_base_libdir}/firmware/${DAPHNE_SELF_TRIGGER_FIRMWARE_NAME} \
    ${nonarch_base_libdir}/firmware/${DAPHNE_FULL_STREAM_FIRMWARE_NAME} \
    ${nonarch_base_libdir}/firmware/xilinx/${DAPHNE_SELF_TRIGGER_APP} \
    ${nonarch_base_libdir}/firmware/xilinx/${DAPHNE_SELF_TRIGGER_APP}/* \
    ${nonarch_base_libdir}/firmware/xilinx/${DAPHNE_FULL_STREAM_APP} \
    ${nonarch_base_libdir}/firmware/xilinx/${DAPHNE_FULL_STREAM_APP}/* \
"
