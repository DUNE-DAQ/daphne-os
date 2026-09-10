# Immutable userspace/gateware compatibility contract for this release line.
# Update this only with a reviewed daphne-server commit that enforces the
# declared identity ABI and supports both --gateware-mode variants.
DAPHNE_SERVER_REQUIRED_GIT_COMMIT = "77b39b7eb75204e1f2025f251a3a76ecf69d1d74"
DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MAJOR = "2"
# Explicit supported minors of the pinned server, not of the packaging tools.
# RC1 predates the ABI 2.1 native-timestamp extension. Do not add 1 until the
# server pin and its ARM runtime have been updated and qualified together.
DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS = "0"
