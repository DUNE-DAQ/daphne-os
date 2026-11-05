#!/usr/bin/env bash
# Scan identity is inherited by Python clients, which append their process ID.
parse_daphne_identity() {
    DAPHNE_CLIENT_ARGS=()
    while (( $# )); do
        case "$1" in
            --identity|-identity)
                if (( $# < 2 )) || [[ -z "$2" ]]; then
                    echo "ERROR: $1 requires a nonempty identity" >&2
                    return 2
                fi
                export DAPHNE_IDENTITY="$2"
                shift 2
                ;;
            --identity=*|-identity=*)
                if [[ -z "${1#*=}" ]]; then
                    echo "ERROR: identity must not be empty" >&2
                    return 2
                fi
                export DAPHNE_IDENTITY="${1#*=}"
                shift
                ;;
            *)
                DAPHNE_CLIENT_ARGS+=("$1")
                shift
                ;;
        esac
    done
}
