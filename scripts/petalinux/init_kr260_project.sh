#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: init_kr260_project.sh PETALINUX_PROJECT_DIR HW_HANDOFF_DIR [options]

Create or reuse a KR260-compatible PetaLinux project, apply the hardware
handoff, attach the repo-owned meta-daphne layer, and optionally stage the
generated overlay artifacts and userspace runtime bundle.

Options:
  --bsp BSP_PATH          Create the project from a BSP instead of the generic
                          zynqMP template
  --template NAME        PetaLinux template to use when --bsp is not given
                          (default: zynqMP)
  --image-profile NAME   DAPHNE image profile: provisioning|minimal|developer
                         (default: minimal)
  --output-dir DIR       Shared dual-gateware output with scoped manifests
  --self-trigger-output-dir DIR
                         Self-trigger firmware output directory
  --full-stream-output-dir DIR
                         Full-stream firmware output directory
  --self-trigger-sha SHA7
                         Select an exact self-trigger app build
  --full-stream-sha SHA7 Select an exact full-stream app build
  --runtime-bundle TGZ   Stage this qualified DAPHNE runtime bundle
  --skip-stage-overlay   Do not stage overlay artifacts
  --skip-stage-runtime   Do not stage the runtime bundle
  --copy-layer           Copy meta-daphne into the project instead of symlinking
  -h, --help             Show this help

Environment:
  DAPHNE_PETALINUX_CREATE_ARGS   extra args for petalinux-create project
  DAPHNE_PETALINUX_CONFIG_ARGS   extra args for petalinux-config
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage
  exit 2
fi

PROJECT_ARG="$1"
HW_HANDOFF_ARG="$2"
shift 2

BSP_PATH=""
TEMPLATE_NAME="zynqMP"
SELF_TRIGGER_OUTPUT_DIR=""
FULL_STREAM_OUTPUT_DIR=""
SELF_TRIGGER_SHA=""
FULL_STREAM_SHA=""
RUNTIME_BUNDLE=""
STAGE_OVERLAY=1
STAGE_RUNTIME=1
LAYER_MODE="symlink"
IMAGE_PROFILE="minimal"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bsp)
      BSP_PATH="$2"
      shift 2
      ;;
    --template)
      TEMPLATE_NAME="$2"
      shift 2
      ;;
    --output-dir)
      SELF_TRIGGER_OUTPUT_DIR="$2"
      FULL_STREAM_OUTPUT_DIR="$2"
      shift 2
      ;;
    --self-trigger-output-dir)
      SELF_TRIGGER_OUTPUT_DIR="$2"
      shift 2
      ;;
    --full-stream-output-dir)
      FULL_STREAM_OUTPUT_DIR="$2"
      shift 2
      ;;
    --self-trigger-sha)
      SELF_TRIGGER_SHA="$2"
      shift 2
      ;;
    --full-stream-sha)
      FULL_STREAM_SHA="$2"
      shift 2
      ;;
    --runtime-bundle)
      RUNTIME_BUNDLE="$2"
      shift 2
      ;;
    --image-profile)
      IMAGE_PROFILE="$2"
      shift 2
      ;;
    --skip-stage-overlay)
      STAGE_OVERLAY=0
      shift
      ;;
    --skip-stage-runtime)
      STAGE_RUNTIME=0
      shift
      ;;
    --copy-layer)
      LAYER_MODE="copy"
      shift
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

ROOT_DIR="${DAPHNE_OS_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
PROJECT_DIR="$PROJECT_ARG"
HW_HANDOFF_DIR="$(CDPATH= cd -- "$HW_HANDOFF_ARG" && pwd)"
CREATE_ARGS="${DAPHNE_PETALINUX_CREATE_ARGS:-}"
CONFIG_ARGS="${DAPHNE_PETALINUX_CONFIG_ARGS:-}"

case "$IMAGE_PROFILE" in
  provisioning|developer|minimal)
    ;;
  *)
    echo "ERROR: unsupported --image-profile: $IMAGE_PROFILE" >&2
    exit 2
    ;;
esac

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command '$1' not found on PATH" >&2
    exit 2
  }
}

need_cmd petalinux-create
need_cmd petalinux-config

if [[ ! -d "$HW_HANDOFF_DIR" ]]; then
  echo "ERROR: hardware handoff directory does not exist: $HW_HANDOFF_ARG" >&2
  exit 2
fi

project_is_initialized() {
  [[ -d "$1/project-spec" && ( -d "$1/.petalinux" || -d "$1/build/conf" ) ]]
}

create_project() {
  local target_dir="$1"
  local parent_dir project_name
  parent_dir="$(dirname "$target_dir")"
  project_name="$(basename "$target_dir")"
  mkdir -p "$parent_dir"

  if [[ -n "$BSP_PATH" ]]; then
    if [[ ! -f "$BSP_PATH" ]]; then
      echo "ERROR: BSP file not found: $BSP_PATH" >&2
      exit 2
    fi
    (
      cd "$parent_dir"
      # shellcheck disable=SC2086
      petalinux-create project --source "$BSP_PATH" -n "$project_name" $CREATE_ARGS
    )
  else
    (
      cd "$parent_dir"
      # shellcheck disable=SC2086
      petalinux-create project --template "$TEMPLATE_NAME" -n "$project_name" $CREATE_ARGS
    )
  fi
}

if [[ -e "$PROJECT_DIR" ]]; then
  PROJECT_DIR="$(CDPATH= cd -- "$PROJECT_DIR" && pwd)"
else
  create_project "$PROJECT_DIR"
  PROJECT_DIR="$(CDPATH= cd -- "$PROJECT_DIR" && pwd)"
fi

if ! project_is_initialized "$PROJECT_DIR"; then
  echo "ERROR: $PROJECT_DIR exists but is not an initialized PetaLinux project." >&2
  exit 2
fi

(
  cd "$PROJECT_DIR"
  # shellcheck disable=SC2086
  petalinux-config --get-hw-description "$HW_HANDOFF_DIR" --silentconfig $CONFIG_ARGS
)

DAPHNE_META_LAYER_MODE="$LAYER_MODE" \
  "$ROOT_DIR/scripts/petalinux/bootstrap_kr260_project.sh" \
    "$PROJECT_DIR" \
    --image-profile "$IMAGE_PROFILE"

(
  cd "$PROJECT_DIR"
  # Regenerate build/conf with the repo-owned KR260 machine overrides applied.
  # shellcheck disable=SC2086
  petalinux-config --silentconfig $CONFIG_ARGS
)

if (( STAGE_OVERLAY )); then
  if [[ -n "$SELF_TRIGGER_OUTPUT_DIR" || -n "$FULL_STREAM_OUTPUT_DIR" ]]; then
    STAGE_ARGS=("$PROJECT_DIR")
    [[ -z "$SELF_TRIGGER_OUTPUT_DIR" ]] || STAGE_ARGS+=(--self-trigger-output "$SELF_TRIGGER_OUTPUT_DIR")
    [[ -z "$FULL_STREAM_OUTPUT_DIR" ]] || STAGE_ARGS+=(--full-stream-output "$FULL_STREAM_OUTPUT_DIR")
    [[ -z "$SELF_TRIGGER_SHA" ]] || STAGE_ARGS+=(--self-trigger-sha "$SELF_TRIGGER_SHA")
    [[ -z "$FULL_STREAM_SHA" ]] || STAGE_ARGS+=(--full-stream-sha "$FULL_STREAM_SHA")
    "$ROOT_DIR/scripts/petalinux/stage_overlay_into_project.sh" "${STAGE_ARGS[@]}"
  else
    echo "INFO: dual-overlay staging skipped because no gateware output directories were provided."
  fi
fi

if (( STAGE_RUNTIME )); then
  if [[ -n "$RUNTIME_BUNDLE" ]]; then
    "$ROOT_DIR/scripts/petalinux/stage_runtime_into_project.sh" "$PROJECT_DIR" "$RUNTIME_BUNDLE"
  else
    echo "INFO: runtime staging skipped because --runtime-bundle was not provided."
  fi
fi

cat <<EOF
Project ready at:
  $PROJECT_DIR

Hardware handoff applied from:
  $HW_HANDOFF_DIR

Next step:
  cd "$PROJECT_DIR" && petalinux-build
EOF
