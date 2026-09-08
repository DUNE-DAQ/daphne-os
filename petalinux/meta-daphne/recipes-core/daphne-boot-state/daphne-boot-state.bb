SUMMARY = "Fleet-neutral DAPHNE A/B boot-state support"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit allarch systemd

SRC_URI += " \
  file://daphne-boot-ok.sh \
  file://daphne-boot-ok.service \
  file://fw_env.config \
"

RDEPENDS:${PN} += "libubootenv-bin"
PACKAGE_ARCH = "${MACHINE_ARCH}"

SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = "daphne-boot-ok.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
    install -d ${D}${prefix}/local/bin
    install -d ${D}${systemd_system_unitdir}
    install -d ${D}${sysconfdir}

    install -m 0755 ${WORKDIR}/daphne-boot-ok.sh \
        ${D}${prefix}/local/bin/daphne-boot-ok.sh
    install -m 0644 ${WORKDIR}/daphne-boot-ok.service \
        ${D}${systemd_system_unitdir}/daphne-boot-ok.service
    install -m 0644 ${WORKDIR}/fw_env.config \
        ${D}${sysconfdir}/fw_env.config
}

FILES:${PN} += " \
    ${prefix}/local/bin/daphne-boot-ok.sh \
    ${systemd_system_unitdir}/daphne-boot-ok.service \
    /etc/fw_env.config \
"

CONFFILES:${PN} += "/etc/fw_env.config"
