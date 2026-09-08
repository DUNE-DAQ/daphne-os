#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap_kr260_project.sh PETALINUX_PROJECT_DIR [options]

Attach the repo-owned meta-daphne layer to an existing KR260-compatible
PetaLinux project.

This script:
  1. links or copies petalinux/meta-daphne into project-spec/meta-daphne
  2. appends the DAPHNE layer entry to build/conf/bblayers.conf
  3. appends the DAPHNE package set to build/conf/local.conf
  4. records the requested DAPHNE image profile in build/conf/local.conf

Options:
  --image-profile NAME   DAPHNE image profile: provisioning|minimal|developer
                         (default: minimal)
  -h, --help             Show this help

Environment:
  DAPHNE_META_LAYER_MODE=symlink|copy   default: symlink
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

ROOT_DIR="${DAPHNE_OS_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
PROJECT_DIR="$(CDPATH= cd -- "$PROJECT_ARG" && pwd)"
META_LAYER_SRC="$ROOT_DIR/petalinux/meta-daphne"
CONFIG_DIR="$ROOT_DIR/petalinux/config/kr260"
LAYER_MODE="${DAPHNE_META_LAYER_MODE:-symlink}"
IMAGE_PROFILE="minimal"

BUILD_CONF_DIR="$PROJECT_DIR/build/conf"
PROJECT_SPEC_DIR="$PROJECT_DIR/project-spec"
META_USER_DIR="$PROJECT_SPEC_DIR/meta-user"
META_LAYER_DST="$PROJECT_SPEC_DIR/meta-daphne"
BBLAYERS_FILE="$BUILD_CONF_DIR/bblayers.conf"
LOCAL_CONF_FILE="$BUILD_CONF_DIR/local.conf"
ROOTFS_CONFIG_FILE="$PROJECT_SPEC_DIR/configs/rootfs_config"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image-profile)
      IMAGE_PROFILE="$2"
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

case "$IMAGE_PROFILE" in
  provisioning|developer|minimal)
    ;;
  *)
    echo "ERROR: unsupported --image-profile: $IMAGE_PROFILE" >&2
    exit 2
    ;;
esac

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "ERROR: project directory does not exist: $PROJECT_ARG" >&2
  exit 2
fi

if [[ ! -d "$PROJECT_SPEC_DIR" || ! -d "$BUILD_CONF_DIR" ]]; then
  echo "ERROR: $PROJECT_DIR does not look like an initialized PetaLinux project." >&2
  echo "Expected: $PROJECT_SPEC_DIR and $BUILD_CONF_DIR" >&2
  echo "Run scripts/petalinux/init_kr260_project.sh with a hardware handoff, or run petalinux-config --get-hw-description first." >&2
  exit 2
fi

if [[ ! -d "$META_LAYER_SRC" ]]; then
  echo "ERROR: missing repo-owned meta layer: $META_LAYER_SRC" >&2
  exit 2
fi

install_meta_layer() {
  rm -rf "$META_LAYER_DST"
  case "$LAYER_MODE" in
    symlink)
      ln -s "$META_LAYER_SRC" "$META_LAYER_DST"
      ;;
    copy)
      cp -R "$META_LAYER_SRC" "$META_LAYER_DST"
      ;;
    *)
      echo "ERROR: unsupported DAPHNE_META_LAYER_MODE=$LAYER_MODE" >&2
      exit 2
      ;;
  esac
}

sync_project_spec_overlay() {
  local src="$1"
  local dst="$2"

  if [[ ! -d "$src" ]]; then
    return 0
  fi

  mkdir -p "$dst"
  cp -R "$src"/. "$dst"/
}

append_once() {
  local src="$1"
  local dst="$2"
  local marker_begin="$3"
  local marker_end="$4"

  python3 - "$src" "$dst" "$marker_begin" "$marker_end" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
begin = sys.argv[3]
end = sys.argv[4]
block = f"{begin}\n{src.read_text()}{end}\n"
text = dst.read_text()

if begin in text and end in text:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    if finish < len(text) and text[finish:finish + 1] == "\n":
        finish += 1
    text = text[:start] + block + text[finish:]
else:
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + block

dst.write_text(text)
PY
}

upsert_profile_setting() {
  local dst="$1"
  local marker_begin="# >>> DAPHNE image profile >>>"
  local marker_end="# <<< DAPHNE image profile <<<"

  python3 - "$dst" "$marker_begin" "$marker_end" "$IMAGE_PROFILE" <<'PY'
from pathlib import Path
import sys

dst = Path(sys.argv[1])
begin = sys.argv[2]
end = sys.argv[3]
profile = sys.argv[4]
block = f"{begin}\nDAPHNE_IMAGE_PROFILE = \"{profile}\"\n{end}\n"
text = dst.read_text()

if begin in text and end in text:
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    if finish < len(text) and text[finish:finish + 1] == "\n":
        finish += 1
    text = text[:start] + block + text[finish:]
else:
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + block

dst.write_text(text)
PY
}

upsert_project_machine_settings() {
  local dst="$1"

  python3 - "$dst" <<'PY'
from pathlib import Path
import re
import sys

dst = Path(sys.argv[1])
text = dst.read_text()

replacements = {
    r'^CONFIG_SUBSYSTEM_MACHINE_NAME=.*$':
        'CONFIG_SUBSYSTEM_MACHINE_NAME="AUTO"',
    r'^CONFIG_SUBSYSTEM_INITRAMFS_IMAGE_NAME=.*$':
        'CONFIG_SUBSYSTEM_INITRAMFS_IMAGE_NAME="petalinux-initramfs-image"',
    r'^CONFIG_YOCTO_MACHINE_NAME=.*$':
        'CONFIG_YOCTO_MACHINE_NAME="xilinx-k26-kr"',
    r'^CONFIG_YOCTO_INCLUDE_MACHINE_NAME=.*$':
        'CONFIG_YOCTO_INCLUDE_MACHINE_NAME="daphne-k26c-xsa"',
    r'^(# )?CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL is not set',
    r'^(# )?CONFIG_SUBSYSTEM_UBOOT_EXT_DTB(=.*| is not set)?$':
        'CONFIG_SUBSYSTEM_UBOOT_EXT_DTB=y',
    r'^CONFIG_UBOOT_DTB_PACKAGE_NAME=.*$':
        'CONFIG_UBOOT_DTB_PACKAGE_NAME="u-boot.dtb"',
    r'^(# )?CONFIG_SUBSYSTEM_PMUFW_SERIAL_PSU_UART_1_SELECT(=.*| is not set)?$':
        'CONFIG_SUBSYSTEM_PMUFW_SERIAL_PSU_UART_1_SELECT=y',
    r'^(# )?CONFIG_SUBSYSTEM_PMUFW_SERIAL_MANUAL_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_PMUFW_SERIAL_MANUAL_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_FSBL_SERIAL_PSU_UART_1_SELECT(=.*| is not set)?$':
        'CONFIG_SUBSYSTEM_FSBL_SERIAL_PSU_UART_1_SELECT=y',
    r'^(# )?CONFIG_SUBSYSTEM_FSBL_SERIAL_PSU_CORESIGHT_0_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_FSBL_SERIAL_PSU_CORESIGHT_0_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_FSBL_SERIAL_MANUAL_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_FSBL_SERIAL_MANUAL_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_TF-A_SERIAL_PSU_UART_1_SELECT(=.*| is not set)?$':
        'CONFIG_SUBSYSTEM_TF-A_SERIAL_PSU_UART_1_SELECT=y',
    r'^(# )?CONFIG_SUBSYSTEM_TF-A_SERIAL_PSU_CORESIGHT_0_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_TF-A_SERIAL_PSU_CORESIGHT_0_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_TF-A_SERIAL_MANUAL_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_TF-A_SERIAL_MANUAL_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_SERIAL_PSU_UART_1_SELECT(=.*| is not set)?$':
        'CONFIG_SUBSYSTEM_SERIAL_PSU_UART_1_SELECT=y',
    r'^(# )?CONFIG_SUBSYSTEM_SERIAL_PSU_CORESIGHT_0_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_SERIAL_PSU_CORESIGHT_0_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_SERIAL_MANUAL_SELECT(=.*| is not set)?$':
        '# CONFIG_SUBSYSTEM_SERIAL_MANUAL_SELECT is not set',
    r'^(# )?CONFIG_SUBSYSTEM_SERIAL_PSU_UART_1_BAUDRATE_115200(=.*| is not set)?$':
        'CONFIG_SUBSYSTEM_SERIAL_PSU_UART_1_BAUDRATE_115200=y',
}

for pattern, replacement in replacements.items():
    text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        if text and not text.endswith("\n"):
            text += "\n"
        text += replacement + "\n"

dedupe_symbols = (
    "CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL",
    "CONFIG_SUBSYSTEM_UBOOT_EXT_DTB",
    "CONFIG_UBOOT_DTB_PACKAGE_NAME",
)

lines = text.splitlines()
seen = set()
filtered = []
for line in reversed(lines):
    symbol = next((
        candidate for candidate in dedupe_symbols
        if line.startswith(candidate + "=")
        or line == f"# {candidate} is not set"
    ), None)
    if symbol:
        if symbol in seen:
            continue
        seen.add(symbol)
    filtered.append(line)
text = "\n".join(reversed(filtered)) + "\n"

dst.write_text(text)
PY
}

upsert_rootfs_settings() {
  local dst="$1"

  if [[ ! -f "$dst" ]]; then
    echo "INFO: rootfs config not found yet, skipping DAPHNE rootfs package overrides: $dst"
    return 0
  fi

  python3 - "$dst" <<'PY'
from pathlib import Path
import re
import sys

dst = Path(sys.argv[1])
text = dst.read_text()

replacements = {
    r'^(# )?CONFIG_nfs-utils(=.*| is not set)?$':
        '# CONFIG_nfs-utils is not set',
    r'^(# )?CONFIG_nfs-utils-client(=.*| is not set)?$':
        '# CONFIG_nfs-utils-client is not set',
    r'^(# )?CONFIG_rpcbind(=.*| is not set)?$':
        '# CONFIG_rpcbind is not set',
    r'^(# )?CONFIG_e2fsprogs-resize2fs(=.*| is not set)?$':
        'CONFIG_e2fsprogs-resize2fs=y',
}

for pattern, replacement in replacements.items():
    text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        if text and not text.endswith("\n"):
            text += "\n"
        text += replacement + "\n"

dst.write_text(text)
PY
}

install_meta_layer
sync_project_spec_overlay \
  "$CONFIG_DIR/project-spec/meta-user" \
  "$META_USER_DIR"

append_once \
  "$CONFIG_DIR/bblayers.conf.append" \
  "$BBLAYERS_FILE" \
  "# >>> DAPHNE meta-daphne >>>" \
  "# <<< DAPHNE meta-daphne <<<"

append_once \
  "$CONFIG_DIR/local.conf.append" \
  "$LOCAL_CONF_FILE" \
  "# >>> DAPHNE image packages >>>" \
  "# <<< DAPHNE image packages <<<"

upsert_profile_setting "$LOCAL_CONF_FILE"
upsert_project_machine_settings "$PROJECT_SPEC_DIR/configs/config"
upsert_rootfs_settings "$ROOTFS_CONFIG_FILE"

cat <<EOF
Attached meta-daphne to:
  $META_LAYER_DST

Updated:
  $BBLAYERS_FILE
  $LOCAL_CONF_FILE
  $PROJECT_SPEC_DIR/configs/config

Selected DAPHNE image profile:
  $IMAGE_PROFILE

Pinned KR260 machine settings:
  CONFIG_SUBSYSTEM_MACHINE_NAME="AUTO"
  CONFIG_SUBSYSTEM_INITRAMFS_IMAGE_NAME="petalinux-initramfs-image"
  CONFIG_YOCTO_MACHINE_NAME="xilinx-k26-kr"
  CONFIG_YOCTO_INCLUDE_MACHINE_NAME="daphne-k26c-xsa"
  # CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL is not set
  CONFIG_SUBSYSTEM_UBOOT_EXT_DTB=y
  CONFIG_UBOOT_DTB_PACKAGE_NAME="u-boot.dtb"

Pinned DAPHNE console settings:
  PMUFW, FSBL, TF-A, U-Boot, and Linux use psu_uart_1
  UART1 baud rate is 115200

DAPHNE rootfs package overrides:
  CONFIG_nfs-utils is not set
  CONFIG_nfs-utils-client is not set
  CONFIG_rpcbind is not set
  CONFIG_e2fsprogs-resize2fs=y

Next manual steps:
  1. Run petalinux-config --silentconfig to regenerate build/conf/ with the KR260 machine if you are not using init_kr260_project.sh.
  2. Review device-tree integration under project-spec/meta-daphne/recipes-bsp/device-tree/files/.
  3. Stage overlay assets from xilinx/output/ once the firmware build is qualified.
  4. Stage a qualified daphne-server runtime bundle with scripts/petalinux/stage_runtime_into_project.sh.
  5. Build and validate the image on a KR260/PetaLinux host.
EOF
