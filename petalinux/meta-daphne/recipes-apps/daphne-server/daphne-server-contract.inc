# Immutable userspace/gateware compatibility contract for this release line.
# Update this only with a reviewed daphne-server commit that enforces the
# declared identity ABI and supports both --gateware-mode variants.
# This is a DUNE-DAQ/daphne-os commit, with source under daphne-server/;
# it is not an ecristal/daphneZMQ revision. See
# docs/afe-global-readback-verification.md for native and live evidence.
DAPHNE_SERVER_REQUIRED_GIT_COMMIT = "78504f11dec0ebc5971bd0bbc9ba8b3f76ca89cd"
DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MAJOR = "2"
# Explicit supported minors of the pinned server, not of the packaging tools.
# Native ARM software qualification and live self-trigger ABI 2.0 regression
# passed for the pinned binary. These are source capabilities, NOT proof of
# routed ABI 2.1/2.2 firmware, full-stream hardware or a complete image build.
DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS = "0 1 2"
