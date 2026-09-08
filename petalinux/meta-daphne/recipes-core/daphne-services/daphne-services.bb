SUMMARY = "Systemd bring-up units for DAPHNE runtime"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit allarch systemd

SRC_URI += " \
  file://README.services \
  file://firmware.service \
  file://clockchip.service \
  file://endpoint.service \
  file://hermes.service \
  file://daphne.service \
  file://daphne-runtime.target \
  file://daphne-gateware-prepare.service \
  file://daphne-gateware-verify.service \
  file://daphne-gateware \
  file://daphne-gateware-self-trigger.conf \
  file://daphne-gateware-full-stream.conf \
  file://daphne-gateware-default-profile \
  file://daphne-fw.sh \
  file://daphne-fw-stop.sh \
  file://daphne-clockchip.sh \
  file://daphne-endpoint-init.py \
  file://daphne-runtime.defaults \
"

RDEPENDS:${PN} += " \
    bash \
    daphne-overlay \
    daphne-server \
    dfx-mgr \
    fpga-manager-script \
    i2c-tools \
    iproute2-ss \
    python3-core \
    python3-fcntl \
    python3-io \
    xmutil \
"

SYSTEMD_SERVICE:${PN} = "daphne-runtime.target"
SYSTEMD_AUTO_ENABLE = "enable"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -d ${D}/usr/local/bin
    install -d ${D}${sbindir}
    install -d ${D}${datadir}/daphne-services
    install -d ${D}${sysconfdir}/default
    install -d ${D}${sysconfdir}/daphne-gateware/profiles

    install -m 0644 ${WORKDIR}/README.services \
        ${D}${datadir}/daphne-services/README.services
    install -m 0644 ${WORKDIR}/daphne-runtime.defaults \
        ${D}${sysconfdir}/default/firmware
    install -m 0644 ${WORKDIR}/daphne-gateware-default-profile \
        ${D}${sysconfdir}/daphne-gateware/default-profile
    install -m 0644 ${WORKDIR}/daphne-gateware-self-trigger.conf \
        ${D}${sysconfdir}/daphne-gateware/profiles/self-trigger.conf
    install -m 0644 ${WORKDIR}/daphne-gateware-full-stream.conf \
        ${D}${sysconfdir}/daphne-gateware/profiles/full-stream.conf
    install -m 0755 ${WORKDIR}/daphne-gateware \
        ${D}${sbindir}/daphne-gateware

    for unit in \
        daphne-runtime.target \
        daphne-gateware-prepare.service \
        firmware.service \
        daphne-gateware-verify.service \
        clockchip.service \
        endpoint.service \
        hermes.service \
        daphne.service; do
        install -m 0644 ${WORKDIR}/${unit} ${D}${systemd_system_unitdir}/${unit}
    done

    for script in daphne-fw.sh daphne-fw-stop.sh daphne-clockchip.sh daphne-endpoint-init.py; do
        install -m 0755 ${WORKDIR}/${script} ${D}/usr/local/bin/${script}
    done
}

FILES:${PN} += " \
    ${systemd_system_unitdir}/firmware.service \
    ${systemd_system_unitdir}/clockchip.service \
    ${systemd_system_unitdir}/endpoint.service \
    ${systemd_system_unitdir}/hermes.service \
    ${systemd_system_unitdir}/daphne.service \
    ${systemd_system_unitdir}/daphne-runtime.target \
    ${systemd_system_unitdir}/daphne-gateware-prepare.service \
    ${systemd_system_unitdir}/daphne-gateware-verify.service \
    ${sbindir}/daphne-gateware \
    /usr/local/bin/daphne-fw.sh \
    /usr/local/bin/daphne-fw-stop.sh \
    /usr/local/bin/daphne-clockchip.sh \
    /usr/local/bin/daphne-endpoint-init.py \
    ${datadir}/daphne-services/README.services \
    ${sysconfdir}/default/firmware \
    ${sysconfdir}/daphne-gateware/default-profile \
    ${sysconfdir}/daphne-gateware/profiles/self-trigger.conf \
    ${sysconfdir}/daphne-gateware/profiles/full-stream.conf \
"

CONFFILES:${PN} += " \
    ${sysconfdir}/default/firmware \
    ${sysconfdir}/daphne-gateware/default-profile \
    ${sysconfdir}/daphne-gateware/profiles/self-trigger.conf \
    ${sysconfdir}/daphne-gateware/profiles/full-stream.conf \
"
