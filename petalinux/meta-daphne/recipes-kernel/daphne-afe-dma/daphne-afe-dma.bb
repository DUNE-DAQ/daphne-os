SUMMARY = "Experimental finite DAPHNE AFE DMA chunk client"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"
DAPHNE_AFE_DMA_SOURCE_DIR ?= ""
FILESEXTRAPATHS:prepend := "${DAPHNE_AFE_DMA_SOURCE_DIR}:"
SRC_URI = "file://daphne-afe-dma.c;subdir=daphne-afe-dma file://daphne_afe_dma_uapi.h;subdir=daphne-afe-dma file://Makefile;subdir=daphne-afe-dma"
S = "${@d.getVar('UNPACKDIR') or d.getVar('WORKDIR')}/daphne-afe-dma"
inherit module
python do_fetch:prepend() {
    if d.getVar('DAPHNE_ENABLE_RAW_DMA_DIAG') != '1' or not d.getVar('DAPHNE_AFE_DMA_SOURCE_DIR'):
        bb.fatal('AFE DMA is opt-in: enable bounded raw-dma test kernel and set DAPHNE_AFE_DMA_SOURCE_DIR')
}
EXTRA_OEMAKE += "KDIR=${STAGING_KERNEL_DIR}"
