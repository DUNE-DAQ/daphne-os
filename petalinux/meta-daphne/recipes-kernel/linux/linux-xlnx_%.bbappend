FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Experimental test-image opt-in. No change to existing image defaults.
DAPHNE_ENABLE_RAW_DMA_DIAG ?= "0"
SRC_URI:append = "${@bb.utils.contains('DAPHNE_ENABLE_RAW_DMA_DIAG', '1', ' file://raw-dma.cfg file://0001-xilinx-dma-bound-atomic-polling.patch', '', d)}"
