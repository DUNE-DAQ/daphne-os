#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: stage_overlay_into_project.sh PETALINUX_PROJECT_DIR [options]

Stage one qualified self-trigger bundle and one qualified full-stream bundle
into the repo-owned meta-daphne layer. Both variants are required: staging is
all-or-nothing so an image cannot silently contain only one gateware mode.

Options:
  --self-trigger-output DIR  Directory containing daphne_selftrigger_ol_*
  --full-stream-output DIR   Directory containing daphne_fullstream_ol_*
  --output-dir DIR           Shared directory containing both variants and
                             scoped manifests (or one aggregate manifest)
  --self-trigger-sha SHA7    Select this exact self-trigger build
  --full-stream-sha SHA7     Select this exact full-stream build
  -h, --help                 Show this help

If a SHA is omitted, its output directory must contain exactly one completed
bundle of that variant. A completed bundle consists of the immutable app
directory, its matching zip archive, and either an app-scoped
`<app>.SHA256SUMS` (preferred) or a root `SHA256SUMS` covering that app. A
shared output directory needs both app-scoped manifests or one aggregate root
manifest covering both apps, so one build cannot overwrite the other build's
checksum evidence.

Environment equivalents:
  DAPHNE_SELF_TRIGGER_OUTPUT_DIR
  DAPHNE_FULL_STREAM_OUTPUT_DIR
  DAPHNE_SELF_TRIGGER_SHA
  DAPHNE_FULL_STREAM_SHA
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

PROJECT_ARG="$1"
shift

SELF_OUTPUT="${DAPHNE_SELF_TRIGGER_OUTPUT_DIR:-}"
FULL_OUTPUT="${DAPHNE_FULL_STREAM_OUTPUT_DIR:-}"
SELF_SHA="${DAPHNE_SELF_TRIGGER_SHA:-}"
FULL_SHA="${DAPHNE_FULL_STREAM_SHA:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --self-trigger-output)
      [[ $# -ge 2 ]] || { echo "ERROR: --self-trigger-output requires a directory" >&2; exit 2; }
      SELF_OUTPUT="$2"
      shift 2
      ;;
    --full-stream-output)
      [[ $# -ge 2 ]] || { echo "ERROR: --full-stream-output requires a directory" >&2; exit 2; }
      FULL_OUTPUT="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --output-dir requires a directory" >&2; exit 2; }
      SELF_OUTPUT="$2"
      FULL_OUTPUT="$2"
      shift 2
      ;;
    --self-trigger-sha)
      [[ $# -ge 2 ]] || { echo "ERROR: --self-trigger-sha requires SHA7" >&2; exit 2; }
      SELF_SHA="$2"
      shift 2
      ;;
    --full-stream-sha)
      [[ $# -ge 2 ]] || { echo "ERROR: --full-stream-sha requires SHA7" >&2; exit 2; }
      FULL_SHA="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$SELF_OUTPUT" || -z "$FULL_OUTPUT" ]]; then
  echo "ERROR: both --self-trigger-output and --full-stream-output are required." >&2
  exit 2
fi

PROJECT_DIR="$(unset CDPATH; cd -- "$PROJECT_ARG" && pwd)"
SELF_OUTPUT="$(unset CDPATH; cd -- "$SELF_OUTPUT" && pwd)"
FULL_OUTPUT="$(unset CDPATH; cd -- "$FULL_OUTPUT" && pwd)"
META_LAYER_DIR="$PROJECT_DIR/project-spec/meta-daphne"
STAGED_DIR="$META_LAYER_DIR/recipes-firmware/daphne-overlay/files/staged"
VERSION_INC="$META_LAYER_DIR/recipes-firmware/daphne-overlay/daphne-overlay-version.inc"
SELF_PROFILE="$META_LAYER_DIR/recipes-core/daphne-services/files/daphne-gateware-self-trigger.conf"
FULL_PROFILE="$META_LAYER_DIR/recipes-core/daphne-services/files/daphne-gateware-full-stream.conf"

if [[ ! -d "$PROJECT_DIR/project-spec" || ! -d "$PROJECT_DIR/build/conf" ]]; then
  echo "ERROR: $PROJECT_DIR does not look like an initialized PetaLinux project." >&2
  exit 2
fi
if [[ ! -d "$META_LAYER_DIR" ]]; then
  echo "ERROR: missing project-spec/meta-daphne in $PROJECT_DIR" >&2
  echo "Run scripts/petalinux/bootstrap_kr260_project.sh first." >&2
  exit 2
fi
for profile_path in "$SELF_PROFILE" "$FULL_PROFILE"; do
  if [[ ! -f "$profile_path" ]]; then
    echo "ERROR: missing gateware runtime profile: $profile_path" >&2
    exit 2
  fi
done
if [[ ! -f "$VERSION_INC" ]]; then
  echo "ERROR: missing overlay version include: $VERSION_INC" >&2
  exit 2
fi

for command_name in find fdtget sha256sum unzip; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "ERROR: required command '$command_name' not found on PATH" >&2
    exit 2
  }
done

validate_sha7() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9a-f]{7}$ ]]; then
    echo "ERROR: $label must be exactly seven lowercase hexadecimal characters: '$value'" >&2
    exit 2
  fi
}

RESOLVED_SHA=""
RESOLVED_APP=""
RESOLVED_DIR=""
RESOLVED_ZIP=""
RESOLVED_MANIFEST=""
RESOLVED_FIRMWARE_NAME=""

resolve_bundle() {
  local label="$1"
  local output_dir="$2"
  local overlay_prefix="$3"
  local requested_sha="$4"
  local candidate suffix
  local -a candidates=()

  if [[ -n "$requested_sha" ]]; then
    validate_sha7 "$label SHA" "$requested_sha"
    candidates+=("$output_dir/${overlay_prefix}_${requested_sha}")
  else
    while IFS= read -r -d '' candidate; do
      suffix="$(basename -- "$candidate")"
      suffix="${suffix#"${overlay_prefix}_"}"
      if [[ "$suffix" =~ ^[0-9a-f]{7}$ && -s "${candidate}.zip" ]]; then
        candidates+=("$candidate")
      fi
    done < <(find "$output_dir" -maxdepth 1 -mindepth 1 -type d -name "${overlay_prefix}_*" -print0 | sort -z)
    if (( ${#candidates[@]} != 1 )); then
      echo "ERROR: $label output must contain exactly one completed ${overlay_prefix}_SHA7 bundle; found ${#candidates[@]}." >&2
      echo "Specify the exact build with --${label}-sha." >&2
      exit 2
    fi
  fi

  RESOLVED_DIR="${candidates[0]}"
  RESOLVED_APP="$(basename -- "$RESOLVED_DIR")"
  RESOLVED_SHA="${RESOLVED_APP#"${overlay_prefix}_"}"
  validate_sha7 "$label SHA" "$RESOLVED_SHA"
  RESOLVED_ZIP="$output_dir/${RESOLVED_APP}.zip"
  local bundle_manifest="$output_dir/${RESOLVED_APP}.SHA256SUMS"
  local root_manifest="$output_dir/SHA256SUMS"
  if [[ -e "$bundle_manifest" ]]; then
    RESOLVED_MANIFEST="$bundle_manifest"
  else
    RESOLVED_MANIFEST="$root_manifest"
  fi

  if [[ ! -d "$RESOLVED_DIR" ]]; then
    echo "ERROR: missing immutable $label app directory: $RESOLVED_DIR" >&2
    exit 2
  fi
  for candidate in \
    "$RESOLVED_DIR/${RESOLVED_APP}.bin" \
    "$RESOLVED_DIR/${RESOLVED_APP}.dtbo" \
    "$RESOLVED_DIR/shell.json" \
    "$RESOLVED_ZIP" \
    "$RESOLVED_MANIFEST"
  do
    if [[ ! -s "$candidate" ]]; then
      echo "ERROR: missing or empty $label release artifact: $candidate" >&2
      exit 2
    fi
  done

  unzip -tqq "$RESOLVED_ZIP" || {
    echo "ERROR: corrupt $label overlay archive: $RESOLVED_ZIP" >&2
    exit 2
  }

  local dtbo="$RESOLVED_DIR/${RESOLVED_APP}.dtbo"
  local firmware_name=""
  local node value
  for node in /amba_pl /fragment@0/__overlay__; do
    value="$(fdtget -t s "$dtbo" "$node" firmware-name 2>/dev/null || true)"
    if [[ -n "$value" ]]; then
      if [[ -n "$firmware_name" && "$firmware_name" != "$value" ]]; then
        echo "ERROR: $dtbo contains conflicting firmware-name values" >&2
        exit 2
      fi
      firmware_name="$value"
    fi
  done
  # The DTBO is consumed as an xmutil application. Keep firmware-name tied to
  # the immutable application payload that is installed beside the DTBO,
  # rather than to the Vivado build-artifact basename.
  RESOLVED_FIRMWARE_NAME="${RESOLVED_APP}.bin"
  if [[ "$firmware_name" != "$RESOLVED_FIRMWARE_NAME" ]]; then
    echo "ERROR: $label DTBO firmware-name is '$firmware_name'; expected '$RESOLVED_FIRMWARE_NAME'." >&2
    exit 2
  fi

  local relative_path expected_digest actual_digest match_count
  for relative_path in \
    "${RESOLVED_APP}.zip" \
    "${RESOLVED_APP}/${RESOLVED_APP}.bin" \
    "${RESOLVED_APP}/${RESOLVED_APP}.dtbo" \
    "${RESOLVED_APP}/shell.json"
  do
    match_count="$(awk -v path="$relative_path" '
      {
        name = $2
        sub(/^\*/, "", name)
        if (NF == 2 && name == path) count += 1
      }
      END { print count + 0 }
    ' "$RESOLVED_MANIFEST")"
    if [[ "$match_count" != "1" ]]; then
      echo "ERROR: $RESOLVED_MANIFEST must contain exactly one checksum for $relative_path" >&2
      exit 2
    fi
    expected_digest="$(awk -v path="$relative_path" '
      {
        name = $2
        sub(/^\*/, "", name)
        if (NF == 2 && name == path) print $1
      }
    ' "$RESOLVED_MANIFEST")"
    case "$relative_path" in
      "${RESOLVED_APP}.zip") candidate="$RESOLVED_ZIP" ;;
      *) candidate="$output_dir/$relative_path" ;;
    esac
    actual_digest="$(sha256sum "$candidate" | awk '{ print $1 }')"
    if [[ "$actual_digest" != "$expected_digest" ]]; then
      echo "ERROR: checksum mismatch for $candidate" >&2
      exit 2
    fi
  done
}

resolve_bundle self-trigger "$SELF_OUTPUT" daphne_selftrigger_ol "$SELF_SHA"
self_sha="$RESOLVED_SHA"
self_app="$RESOLVED_APP"
self_dir="$RESOLVED_DIR"
self_zip="$RESOLVED_ZIP"
self_manifest="$RESOLVED_MANIFEST"
self_firmware_name="$RESOLVED_FIRMWARE_NAME"

resolve_bundle full-stream "$FULL_OUTPUT" daphne_fullstream_ol "$FULL_SHA"
full_sha="$RESOLVED_SHA"
full_app="$RESOLVED_APP"
full_dir="$RESOLVED_DIR"
full_zip="$RESOLVED_ZIP"
full_manifest="$RESOLVED_MANIFEST"
full_firmware_name="$RESOLVED_FIRMWARE_NAME"

staged_parent="$(dirname -- "$STAGED_DIR")"
mkdir -p "$staged_parent"
temporary_staged="$(mktemp -d "$staged_parent/.staged.dual.XXXXXX")"
temporary_inc="$(mktemp "$(dirname -- "$VERSION_INC")/.daphne-overlay-version.XXXXXX")"
temporary_self_profile="$(mktemp "$(dirname -- "$SELF_PROFILE")/.daphne-gateware-self-trigger.XXXXXX")"
temporary_full_profile="$(mktemp "$(dirname -- "$FULL_PROFILE")/.daphne-gateware-full-stream.XXXXXX")"
backup_root=""
transaction_active=0
had_staged=0

cleanup() {
  if (( transaction_active == 1 )); then
    set +e
    rm -rf -- "$STAGED_DIR"
    rm -f -- "$VERSION_INC" "$SELF_PROFILE" "$FULL_PROFILE"
    if (( had_staged == 1 )) && [[ -e "$backup_root/staged" ]]; then
      mv -- "$backup_root/staged" "$STAGED_DIR"
    fi
    [[ ! -e "$backup_root/daphne-overlay-version.inc" ]] || mv -- "$backup_root/daphne-overlay-version.inc" "$VERSION_INC"
    [[ ! -e "$backup_root/daphne-gateware-self-trigger.conf" ]] || mv -- "$backup_root/daphne-gateware-self-trigger.conf" "$SELF_PROFILE"
    [[ ! -e "$backup_root/daphne-gateware-full-stream.conf" ]] || mv -- "$backup_root/daphne-gateware-full-stream.conf" "$FULL_PROFILE"
    set -e
  fi
  [[ -z "${temporary_staged:-}" || ! -e "$temporary_staged" ]] || rm -rf -- "$temporary_staged"
  [[ -z "${temporary_inc:-}" || ! -e "$temporary_inc" ]] || rm -f -- "$temporary_inc"
  [[ -z "${temporary_self_profile:-}" || ! -e "$temporary_self_profile" ]] || rm -f -- "$temporary_self_profile"
  [[ -z "${temporary_full_profile:-}" || ! -e "$temporary_full_profile" ]] || rm -f -- "$temporary_full_profile"
  [[ -z "${backup_root:-}" || ! -e "$backup_root" ]] || rm -rf -- "$backup_root"
}
trap cleanup EXIT

stage_one() {
  local mode="$1"
  local app="$2"
  local git_sha="$3"
  local firmware_name="$4"
  local source_dir="$5"
  local source_zip="$6"
  local source_manifest="$7"
  local variant="$8"
  local destination="$temporary_staged/$mode"

  mkdir -p "$destination"
  cp -f "$source_dir/${app}.bin" "$destination/${app}.bin"
  cp -f "$source_dir/${app}.dtbo" "$destination/${app}.dtbo"
  cp -f "$source_dir/shell.json" "$destination/shell.json"
  cat > "$destination/BUILD-METADATA.txt" <<EOF
gateware_mode=$mode
app=$app
git_sha=$git_sha
firmware_name=$firmware_name
identity_abi_major=2
identity_abi_minor=0
identity_variant=$variant
source_bundle=$(basename -- "$source_zip")
source_bundle_sha256=$(sha256sum "$source_zip" | awk '{ print $1 }')
source_manifest=$(basename -- "$source_manifest")
source_manifest_sha256=$(sha256sum "$source_manifest" | awk '{ print $1 }')
EOF
  (
    cd "$destination"
    sha256sum "${app}.bin" "${app}.dtbo" shell.json BUILD-METADATA.txt > SHA256SUMS
    sha256sum --check --strict SHA256SUMS >/dev/null
  )
}

stage_one self-trigger "$self_app" "$self_sha" "$self_firmware_name" "$self_dir" "$self_zip" "$self_manifest" 1
stage_one full-stream "$full_app" "$full_sha" "$full_firmware_name" "$full_dir" "$full_zip" "$full_manifest" 2

cat > "$temporary_inc" <<EOF
# Generated by scripts/petalinux/stage_overlay_into_project.sh.
DAPHNE_DUAL_OVERLAY_STAGED = "1"
DAPHNE_SELF_TRIGGER_APP = "$self_app"
DAPHNE_SELF_TRIGGER_FIRMWARE_NAME = "$self_firmware_name"
DAPHNE_FULL_STREAM_APP = "$full_app"
DAPHNE_FULL_STREAM_FIRMWARE_NAME = "$full_firmware_name"
EOF
chmod 0644 "$temporary_inc"

render_profile() {
  local source="$1"
  local destination="$2"
  local app="$3"
  local expected_mode="$4"
  local app_count profile_count mode_count

  app_count="$(grep -Ec '^APP=' "$source" || true)"
  profile_count="$(grep -Fxc "PROFILE=$expected_mode" "$source" || true)"
  mode_count="$(grep -Fxc "GATEWARE_MODE=$expected_mode" "$source" || true)"
  if [[ "$app_count" != "1" || "$profile_count" != "1" || "$mode_count" != "1" ]]; then
    echo "ERROR: $source is not a unique $expected_mode profile with one APP= assignment" >&2
    exit 2
  fi
  awk -v app="$app" '{ if ($0 ~ /^APP=/) print "APP=" app; else print }' \
    "$source" > "$destination"
  chmod 0644 "$destination"
}

render_profile "$SELF_PROFILE" "$temporary_self_profile" "$self_app" self-trigger
render_profile "$FULL_PROFILE" "$temporary_full_profile" "$full_app" full-stream

# Commit the payload, recipe variables, and runtime profile bindings as one
# rollback-capable transaction. Copy every prior target before changing any
# live target, so an interruption during backup cannot strand a partial set.
backup_root="$(mktemp -d "$META_LAYER_DIR/.dual-overlay-backup.XXXXXX")"
if [[ -e "$STAGED_DIR" ]]; then
  had_staged=1
  cp -a -- "$STAGED_DIR" "$backup_root/staged"
fi
cp -a -- "$VERSION_INC" "$backup_root/daphne-overlay-version.inc"
cp -a -- "$SELF_PROFILE" "$backup_root/daphne-gateware-self-trigger.conf"
cp -a -- "$FULL_PROFILE" "$backup_root/daphne-gateware-full-stream.conf"

transaction_active=1
rm -rf -- "$STAGED_DIR"
mv -- "$temporary_staged" "$STAGED_DIR"
mv -- "$temporary_inc" "$VERSION_INC"
mv -- "$temporary_self_profile" "$SELF_PROFILE"
mv -- "$temporary_full_profile" "$FULL_PROFILE"
temporary_staged=""
temporary_inc=""
temporary_self_profile=""
temporary_full_profile=""
transaction_active=0
rm -rf -- "$backup_root"
backup_root=""

cat <<EOF
Staged immutable dual-gateware apps:
  self-trigger: $self_app
  full-stream:  $full_app

Payload root:
  $STAGED_DIR
Version include:
  $VERSION_INC
Runtime profiles:
  $SELF_PROFILE
  $FULL_PROFILE
EOF
