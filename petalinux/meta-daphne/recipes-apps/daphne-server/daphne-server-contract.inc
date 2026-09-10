# Immutable userspace/gateware compatibility contract for this release line.
# Update this only with a reviewed daphne-server commit that enforces the
# declared identity ABI and supports both --gateware-mode variants.
# This is a DUNE-DAQ/daphne-os commit, with source under daphne-server/;
# it is not an ecristal/daphneZMQ revision. See
# docs/sc-bias-enable-ownership.md for native and live SC-preservation evidence.
DAPHNE_SERVER_REQUIRED_GIT_COMMIT = "fb82e0a6f6607e9486a98ed6fc1a26b07b0b0665"
DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MAJOR = "2"
# Explicit supported minors of the pinned server, not of the packaging tools.
# Native ARM software qualification and live self-trigger ABI 2.0 regression
# passed for the pinned binary. These are source capabilities, NOT proof of
# routed ABI 2.1/2.2 firmware, full-stream hardware or a complete image build.
DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS = "0 1 2"
