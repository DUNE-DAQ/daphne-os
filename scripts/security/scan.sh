#!/usr/bin/env bash
# Reports stay outside the checkout and never print credential values.
set -euo pipefail
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
scanner=${GITLEAKS_BIN:-gitleaks}
umask 077
report_dir=$(mktemp -d "${TMPDIR:-/tmp}/daphne-os-secrets-XXXXXXXX")

scan() {
    local name=$1
    shift
    local result=0
    "$scanner" "$@" --config "$root/.gitleaks.toml" \
        --gitleaks-ignore-path "$report_dir" --ignore-gitleaks-allow \
        --redact=100 --no-banner --no-color --report-format json \
        --report-path "$report_dir/$name.json" || result=$?
    if [[ $result != 0 && $result != 1 ]]; then
        echo "Credential scanner failed to complete: $name" >&2
        return "$result"
    fi
    python3 "$root/scripts/security/verify_findings.py" \
        "$report_dir/$name.json" --repository "$root"
}

scan history git "$root" --log-opts='--all --full-history -m'
scan current dir "$root" --max-archive-depth 3
git -C "$root" log --all --format=%B | scan messages stdin
git -C "$root" for-each-ref --format='%(contents)' refs/tags | scan tags stdin
echo 'Credential checks completed; redacted reports remain in a private temporary directory.'
