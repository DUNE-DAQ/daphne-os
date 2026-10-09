FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Experimental test-image opt-in. No change to existing image defaults.
DAPHNE_ENABLE_RAW_DMA_DIAG ?= "0"
SRC_URI:append = "${@bb.utils.contains('DAPHNE_ENABLE_RAW_DMA_DIAG', '1', ' file://raw-dma.cfg', '', d)}"
