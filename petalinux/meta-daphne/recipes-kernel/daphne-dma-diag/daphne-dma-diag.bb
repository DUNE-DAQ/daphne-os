SUMMARY = "Experimental DAPHNE raw-dma diagnostic kernel client"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

# Set to the source directory in a pinned daphne-os checkout on the build host.
# Sources stay in one place; the recipe copies them into its own workdir.
DAPHNE_DMA_SOURCE_DIR ?= ""
FILESEXTRAPATHS:prepend := "${DAPHNE_DMA_SOURCE_DIR}:"
SRC_URI = "file://daphne-dma-diag.c;subdir=daphne-dma-diag file://daphne_dma_uapi.h;subdir=daphne-dma-diag file://dma_layout.h;subdir=daphne-dma-diag file://Makefile;subdir=daphne-dma-diag"
S = "${@d.getVar('UNPACKDIR') or d.getVar('WORKDIR')}/daphne-dma-diag"
inherit module

python do_fetch:prepend() {
    if d.getVar('DAPHNE_ENABLE_RAW_DMA_DIAG') != '1' or not d.getVar('DAPHNE_DMA_SOURCE_DIR'):
        bb.fatal('Set DAPHNE_ENABLE_RAW_DMA_DIAG=1 and DAPHNE_DMA_SOURCE_DIR for the experimental test image')
}

# module.bbclass provides KERNEL_SRC/KERNEL_PATH. Our out-of-tree Makefile
# deliberately accepts KDIR as well for native builds on the board.
EXTRA_OEMAKE += "KDIR=${STAGING_KERNEL_DIR}"
