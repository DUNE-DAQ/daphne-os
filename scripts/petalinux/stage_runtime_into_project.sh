#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: stage_runtime_into_project.sh PETALINUX_PROJECT_DIR RUNTIME_BUNDLE_TGZ

Copy a qualified DAPHNE userspace runtime bundle into the repo-owned
meta-daphne layer inside an initialized PetaLinux project.

If BUILD-METADATA.txt is adjacent to the input bundle, it is preserved after
its artifact digest, pinned server commit, target, qualification record, and
daphneServer command-line contract are validated.  An adjacent SHA256SUMS is
also checked when present.  A bare bundle is staged with generated metadata,
but remains explicitly unqualified and the release recipe will reject it.

The staged canonical filenames are:
  - daphne-server-runtime-minimal.tgz
  - BUILD-METADATA.txt
  - SHA256SUMS
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 2 ]]; then
  usage
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi

PROJECT_DIR="$(unset CDPATH; cd -- "$1" && pwd)"
RUNTIME_BUNDLE_INPUT="$2"
RUNTIME_BUNDLE="$(unset CDPATH; cd -- "$(dirname -- "$RUNTIME_BUNDLE_INPUT")" && pwd)/$(basename -- "$RUNTIME_BUNDLE_INPUT")"
META_LAYER_DIR="$PROJECT_DIR/project-spec/meta-daphne"
RECIPE_DIR="$META_LAYER_DIR/recipes-apps/daphne-server"
STAGED_DIR="$RECIPE_DIR/files/staged"
CONTRACT_INC="$RECIPE_DIR/daphne-server-contract.inc"
VERSION_INC="$RECIPE_DIR/daphne-server-version.inc"
RUNTIME_INPUT_DIR="$(dirname -- "$RUNTIME_BUNDLE")"
RUNTIME_INPUT_NAME="$(basename -- "$RUNTIME_BUNDLE")"
SOURCE_METADATA="$RUNTIME_INPUT_DIR/BUILD-METADATA.txt"
SOURCE_SUMS="$RUNTIME_INPUT_DIR/SHA256SUMS"

if [[ ! -d "$PROJECT_DIR/project-spec" || ! -d "$PROJECT_DIR/build/conf" ]]; then
  echo "ERROR: $PROJECT_DIR does not look like an initialized PetaLinux project." >&2
  exit 2
fi

if [[ ! -d "$META_LAYER_DIR" ]]; then
  echo "ERROR: missing project-spec/meta-daphne in $PROJECT_DIR" >&2
  echo "Run scripts/petalinux/bootstrap_kr260_project.sh first." >&2
  exit 2
fi

if [[ ! -f "$RUNTIME_BUNDLE" ]]; then
  echo "ERROR: missing runtime bundle: $RUNTIME_BUNDLE" >&2
  exit 2
fi
if [[ ! -f "$CONTRACT_INC" || ! -f "$VERSION_INC" ]]; then
  echo "ERROR: missing daphne-server compatibility contract in $RECIPE_DIR" >&2
  echo "Run scripts/petalinux/bootstrap_kr260_project.sh with the current meta-daphne layer." >&2
  exit 2
fi

for command_name in awk grep mktemp readelf sha256sum strings tar; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "ERROR: required command '$command_name' not found on PATH" >&2
    exit 2
  }
done

contract_value() {
  local key="$1"
  local count value
  count="$(awk -v key="$key" '$1 == key && $2 == "=" { count++ } END { print count + 0 }' "$CONTRACT_INC")"
  if [[ "$count" != "1" ]]; then
    echo "ERROR: expected exactly one $key assignment in $CONTRACT_INC" >&2
    exit 2
  fi
  value="$(awk -v key="$key" '
    $1 == key && $2 == "=" {
      value = $0
      sub(/^[^"]*"/, "", value)
      sub(/"[^\"]*$/, "", value)
      print value
    }
  ' "$CONTRACT_INC")"
  if [[ -z "$value" ]]; then
    echo "ERROR: empty $key assignment in $CONTRACT_INC" >&2
    exit 2
  fi
  printf '%s\n' "$value"
}

metadata_value() {
  local key="$1"
  local count
  count="$(awk -v prefix="$key=" 'index($0, prefix) == 1 { count++ } END { print count + 0 }' "$SOURCE_METADATA")"
  if [[ "$count" != "1" ]]; then
    echo "ERROR: expected exactly one '$key=' record in $SOURCE_METADATA" >&2
    exit 2
  fi
  awk -v prefix="$key=" 'index($0, prefix) == 1 { print substr($0, length(prefix) + 1) }' "$SOURCE_METADATA"
}

validate_digest() {
  local label="$1"
  local expected="${2,,}"
  local actual="${3,,}"
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "ERROR: invalid SHA-256 for $label: '$2'" >&2
    exit 2
  fi
  if [[ "$expected" != "$actual" ]]; then
    echo "ERROR: SHA-256 mismatch for $label: expected $expected, got $actual" >&2
    exit 2
  fi
}

required_commit="$(contract_value DAPHNE_SERVER_REQUIRED_GIT_COMMIT)"
required_abi="$(contract_value DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MAJOR)"
if [[ ! "$required_commit" =~ ^[0-9a-f]{40}$ || ! "$required_abi" =~ ^[0-9]+$ ]]; then
  echo "ERROR: malformed daphne-server compatibility contract in $CONTRACT_INC" >&2
  exit 2
fi

bundle_sha256="$(sha256sum "$RUNTIME_BUNDLE" | awk '{ print $1 }')"

if [[ -f "$SOURCE_SUMS" ]]; then
  mapfile -t source_manifest_hashes < <(
    awk -v artifact="$RUNTIME_INPUT_NAME" '
      {
        name = $2
        sub(/^\*/, "", name)
        if (NF == 2 && name == artifact) print $1
      }
    ' "$SOURCE_SUMS"
  )
  if (( ${#source_manifest_hashes[@]} != 1 )); then
    echo "ERROR: $SOURCE_SUMS must contain exactly one checksum for $RUNTIME_INPUT_NAME" >&2
    exit 2
  fi
  validate_digest "$SOURCE_SUMS:$RUNTIME_INPUT_NAME" "${source_manifest_hashes[0]}" "$bundle_sha256"
fi

qualified=0
metadata_server_commit="unqualified"
temporary_validation="$(mktemp -d)"
temporary_staged=""
temporary_inc=""
backup_root=""
transaction_active=0
had_staged=0

cleanup() {
  if (( transaction_active == 1 )); then
    set +e
    rm -rf -- "$STAGED_DIR"
    rm -f -- "$VERSION_INC"
    if (( had_staged == 1 )) && [[ -e "$backup_root/staged" ]]; then
      mv -- "$backup_root/staged" "$STAGED_DIR"
    fi
    [[ ! -e "$backup_root/daphne-server-version.inc" ]] || \
      mv -- "$backup_root/daphne-server-version.inc" "$VERSION_INC"
    set -e
  fi
  [[ -z "${temporary_validation:-}" || ! -e "$temporary_validation" ]] || rm -rf -- "$temporary_validation"
  [[ -z "${temporary_staged:-}" || ! -e "$temporary_staged" ]] || rm -rf -- "$temporary_staged"
  [[ -z "${temporary_inc:-}" || ! -e "$temporary_inc" ]] || rm -f -- "$temporary_inc"
  [[ -z "${backup_root:-}" || ! -e "$backup_root" ]] || rm -rf -- "$backup_root"
}
trap cleanup EXIT

if [[ -f "$SOURCE_METADATA" ]]; then
  metadata_artifact="$(metadata_value artifact)"
  metadata_sha256="$(metadata_value sha256)"
  metadata_server_commit="$(metadata_value server_git_commit)"
  metadata_source_clean="$(metadata_value source_tree_clean)"
  metadata_arch="$(metadata_value target_architecture)"
  metadata_recipe_compatible="$(metadata_value legacy_recipe_compatible)"
  metadata_qemu_validation="$(metadata_value qemu_validation)"
  metadata_binary_sha256="$(metadata_value binary_sha256)"

  if [[ "$metadata_artifact" != "$RUNTIME_INPUT_NAME" ]]; then
    echo "ERROR: metadata artifact '$metadata_artifact' does not name $RUNTIME_INPUT_NAME" >&2
    exit 2
  fi
  validate_digest "$SOURCE_METADATA:sha256" "$metadata_sha256" "$bundle_sha256"
  if [[ "$metadata_server_commit" != "$required_commit" ]]; then
    echo "ERROR: server_git_commit '$metadata_server_commit' does not match required commit '$required_commit'" >&2
    exit 2
  fi
  if [[ "$metadata_source_clean" != "true" || "$metadata_arch" != "aarch64" ]]; then
    echo "ERROR: runtime metadata must identify a clean aarch64 server build" >&2
    exit 2
  fi
  if [[ "$metadata_recipe_compatible" != "true" ]]; then
    echo "ERROR: runtime metadata does not declare legacy_recipe_compatible=true" >&2
    exit 2
  fi
  if [[ "$metadata_qemu_validation" != PASS:* ]]; then
    echo "ERROR: runtime metadata does not contain a passing qemu_validation record" >&2
    exit 2
  fi

  server_member="home/petalinux/daphne-server/build-petalinux/daphneServer"
  server_member_count="$(tar -tzf "$RUNTIME_BUNDLE" | grep -Fxc -- "$server_member" || true)"
  if [[ "$server_member_count" != "1" ]]; then
    echo "ERROR: runtime bundle must contain exactly one $server_member" >&2
    exit 2
  fi
  tar -xOzf "$RUNTIME_BUNDLE" "$server_member" > "$temporary_validation/daphneServer"
  binary_sha256="$(sha256sum "$temporary_validation/daphneServer" | awk '{ print $1 }')"
  validate_digest "$SOURCE_METADATA:binary_sha256" "$metadata_binary_sha256" "$binary_sha256"
  if ! LC_ALL=C readelf -h "$temporary_validation/daphneServer" > "$temporary_validation/daphneServer.elf-header" 2>/dev/null; then
    echo "ERROR: bundled daphneServer is not a readable ELF executable" >&2
    exit 2
  fi
  if ! grep -Eq '^[[:space:]]*Class:[[:space:]]+ELF64[[:space:]]*$' "$temporary_validation/daphneServer.elf-header" || \
     ! grep -Eq '^[[:space:]]*Machine:[[:space:]]+AArch64[[:space:]]*$' "$temporary_validation/daphneServer.elf-header"; then
    echo "ERROR: bundled daphneServer is not an ELF64 AArch64 executable" >&2
    exit 2
  fi
  strings "$temporary_validation/daphneServer" > "$temporary_validation/daphneServer.strings"
  for required_option in --gateware-mode --expected-gateware-build-id; do
    if ! grep -Fqx -- "$required_option" "$temporary_validation/daphneServer.strings"; then
      echo "ERROR: bundled daphneServer does not advertise required option $required_option" >&2
      exit 2
    fi
  done
  qualified=1
fi

mkdir -p "$(dirname -- "$STAGED_DIR")"
temporary_staged="$(mktemp -d "$(dirname -- "$STAGED_DIR")/.staged.runtime.XXXXXX")"
temporary_inc="$(mktemp "$RECIPE_DIR/.daphne-server-version.XXXXXX")"
cp -f "$RUNTIME_BUNDLE" "$temporary_staged/daphne-server-runtime-minimal.tgz"

if (( qualified == 1 )); then
  cp -f "$SOURCE_METADATA" "$temporary_staged/BUILD-METADATA.txt"
else
  cat > "$temporary_staged/BUILD-METADATA.txt" <<EOF
artifact=daphne-server-runtime-minimal.tgz
sha256=$bundle_sha256
provenance=external-unqualified-input
qualification=missing-adjacent-build-metadata
EOF
fi

(
  cd "$temporary_staged"
  sha256sum daphne-server-runtime-minimal.tgz BUILD-METADATA.txt > SHA256SUMS
  sha256sum --check --strict SHA256SUMS >/dev/null
)

cat > "$temporary_inc" <<EOF
# Generated by scripts/petalinux/stage_runtime_into_project.sh.
DAPHNE_SERVER_RUNTIME_QUALIFIED = "$qualified"
DAPHNE_SERVER_RUNTIME_GIT_COMMIT = "$metadata_server_commit"
DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MAJOR = "$([[ "$qualified" == "1" ]] && printf '%s' "$required_abi" || printf '%s' unqualified)"
DAPHNE_SERVER_RUNTIME_SHA256 = "$bundle_sha256"
EOF
chmod 0644 "$temporary_inc"

# Commit payload and compatibility sentinel together.  Validation failures
# above leave the last known staged runtime untouched.
backup_root="$(mktemp -d "$META_LAYER_DIR/.runtime-backup.XXXXXX")"
if [[ -e "$STAGED_DIR" ]]; then
  had_staged=1
  cp -a -- "$STAGED_DIR" "$backup_root/staged"
fi
cp -a -- "$VERSION_INC" "$backup_root/daphne-server-version.inc"

transaction_active=1
rm -rf -- "$STAGED_DIR"
mv -- "$temporary_staged" "$STAGED_DIR"
mv -- "$temporary_inc" "$VERSION_INC"
temporary_staged=""
temporary_inc=""
transaction_active=0
rm -rf -- "$backup_root"
backup_root=""

cat <<EOF
Staged runtime bundle into:
  $STAGED_DIR

Files:
  $STAGED_DIR/daphne-server-runtime-minimal.tgz
  $STAGED_DIR/BUILD-METADATA.txt
  $STAGED_DIR/SHA256SUMS

Release qualification:
  $([[ "$qualified" == "1" ]] && printf '%s' "PASS (server $metadata_server_commit, gateware ABI $required_abi)" || printf '%s' "UNQUALIFIED (adjacent BUILD-METADATA.txt was not supplied)")
Compatibility sentinel:
  $VERSION_INC
EOF
