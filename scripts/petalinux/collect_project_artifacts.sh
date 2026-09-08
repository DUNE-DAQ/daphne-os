#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: collect_project_artifacts.sh PETALINUX_PROJECT_DIR [BUNDLE_DIR]

Collect the boot, DT, rootfs, and profile-qualified overlay artifacts used by
whole-eMMC provisioning and inactive-slot updates.

Default bundle directory:
  petalinux/output/<project-name>
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 || $# -gt 2 ]]; then
  usage
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi

ROOT_DIR="${DAPHNE_OS_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
PROJECT_DIR="$(CDPATH= cd -- "$1" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
BUNDLE_DIR_INPUT="${2:-$ROOT_DIR/petalinux/output/$PROJECT_NAME}"
BUNDLE_PARENT_INPUT="$(dirname -- "$BUNDLE_DIR_INPUT")"
mkdir -p "$BUNDLE_PARENT_INPUT"
BUNDLE_PARENT="$(CDPATH= cd -- "$BUNDLE_PARENT_INPUT" && pwd)"
FINAL_BUNDLE_DIR="$BUNDLE_PARENT/$(basename -- "$BUNDLE_DIR_INPUT")"
BUNDLE_DIR="$(mktemp -d "$BUNDLE_PARENT/.${PROJECT_NAME}.tmp.XXXXXX")"

cleanup_staging_bundle() {
  if [[ -n "${BUNDLE_DIR:-}" && -d "$BUNDLE_DIR" ]]; then
    rm -rf -- "$BUNDLE_DIR"
  fi
}
trap cleanup_staging_bundle EXIT

IMAGES_DIR="$PROJECT_DIR/images/linux"
STAGED_DIR="$PROJECT_DIR/project-spec/meta-daphne/recipes-firmware/daphne-overlay/files/staged"
SERVER_RECIPE_DIR="$PROJECT_DIR/project-spec/meta-daphne/recipes-apps/daphne-server"
SERVER_STAGED_DIR="$SERVER_RECIPE_DIR/files/staged"
LOCAL_CONF="$PROJECT_DIR/build/conf/local.conf"
BOOT_DIR="$BUNDLE_DIR/boot"
ROOTFS_DIR="$BUNDLE_DIR/rootfs"
OVERLAY_DIR="$BUNDLE_DIR/overlay"
META_DIR="$BUNDLE_DIR/meta"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command '$1' not found on PATH" >&2
    exit 2
  }
}

need_cmd find
need_cmd sort

if [[ ! -d "$PROJECT_DIR/project-spec" || ! -d "$PROJECT_DIR/build/conf" ]]; then
  echo "ERROR: $PROJECT_DIR does not look like an initialized PetaLinux project." >&2
  exit 2
fi

if [[ ! -d "$IMAGES_DIR" ]]; then
  echo "ERROR: missing images directory: $IMAGES_DIR" >&2
  echo "Run petalinux-build first." >&2
  exit 2
fi

IMAGE_PROFILE="unknown"
if [[ -f "$LOCAL_CONF" ]]; then
  detected_profile="$({
    sed -nE \
      's/^[[:space:]]*DAPHNE_IMAGE_PROFILE[[:space:]]*(\?=|=)[[:space:]]*"([^"]+)".*$/\2/p' \
      "$LOCAL_CONF" || true
  } | tail -n 1)"
  if [[ -n "$detected_profile" ]]; then
    IMAGE_PROFILE="$detected_profile"
  fi
fi

INCLUDE_STAGED_OVERLAY=0
DEPLOYMENT_SCOPE="unclassified"
OVERLAY_POLICY="excluded-unclassified-profile"
case "$IMAGE_PROFILE" in
  provisioning)
    DEPLOYMENT_SCOPE="virgin-som-whole-emmc"
    OVERLAY_POLICY="excluded-for-provisioning"
    ;;
  minimal|developer)
    INCLUDE_STAGED_OVERLAY=1
    DEPLOYMENT_SCOPE="whole-emmc-and-inactive-slot"
    OVERLAY_POLICY="included-from-staged-dual-artifacts"
    ;;
esac

mkdir -p "$BOOT_DIR" "$ROOTFS_DIR" "$OVERLAY_DIR" "$META_DIR"

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" || -L "$src" ]]; then
    cp -fL "$src" "$dst"
  fi
}

copy_glob_matches() {
  local src_dir="$1"
  local pattern="$2"
  local dst_dir="$3"
  find "$src_dir" -maxdepth 1 \( -type f -o -type l \) -name "$pattern" -print | sort | while read -r path; do
    cp -fL "$path" "$dst_dir/$(basename "$path")"
  done
}

copy_if_exists "$IMAGES_DIR/BOOT.BIN" "$BOOT_DIR/BOOT.BIN"
copy_if_exists "$IMAGES_DIR/zynqmp_fsbl.elf" "$BOOT_DIR/zynqmp_fsbl.elf"
copy_if_exists "$IMAGES_DIR/pmufw.elf" "$BOOT_DIR/pmufw.elf"
copy_if_exists "$IMAGES_DIR/bl31.elf" "$BOOT_DIR/bl31.elf"
copy_if_exists "$IMAGES_DIR/u-boot.elf" "$BOOT_DIR/u-boot.elf"
copy_if_exists "$IMAGES_DIR/u-boot-dtb.elf" "$BOOT_DIR/u-boot-dtb.elf"
copy_if_exists "$IMAGES_DIR/Image" "$BOOT_DIR/Image"
copy_if_exists "$IMAGES_DIR/boot.scr" "$BOOT_DIR/boot.scr"
copy_if_exists "$IMAGES_DIR/imgsel.elf" "$BOOT_DIR/imgsel.elf"
copy_if_exists "$IMAGES_DIR/system.dtb" "$BOOT_DIR/system.dtb"
copy_if_exists "$IMAGES_DIR/image.ub" "$BOOT_DIR/image.ub"
copy_if_exists "$IMAGES_DIR/ramdisk.cpio.gz.u-boot" "$BOOT_DIR/ramdisk.cpio.gz.u-boot"
copy_if_exists "$IMAGES_DIR/rootfs.cpio.gz.u-boot" "$BOOT_DIR/rootfs.cpio.gz.u-boot"

copy_glob_matches "$IMAGES_DIR" "*.dtb" "$BOOT_DIR"
copy_glob_matches "$IMAGES_DIR" "*.dtbo" "$BOOT_DIR"

copy_if_exists "$IMAGES_DIR/rootfs.ext4" "$ROOTFS_DIR/rootfs.ext4"
copy_if_exists "$IMAGES_DIR/rootfs.ext4.gz" "$ROOTFS_DIR/rootfs.ext4.gz"
copy_if_exists "$IMAGES_DIR/rootfs.tar.gz" "$ROOTFS_DIR/rootfs.tar.gz"
copy_if_exists "$IMAGES_DIR/rootfs.wic" "$ROOTFS_DIR/rootfs.wic"
copy_if_exists "$IMAGES_DIR/rootfs.wic.gz" "$ROOTFS_DIR/rootfs.wic.gz"
copy_if_exists "$IMAGES_DIR/rootfs.cpio.gz" "$ROOTFS_DIR/rootfs.cpio.gz"
copy_if_exists "$IMAGES_DIR/rootfs.manifest" "$ROOTFS_DIR/rootfs.manifest"

if (( INCLUDE_STAGED_OVERLAY == 1 )) && [[ -d "$STAGED_DIR" ]]; then
  for mode in self-trigger full-stream; do
    if [[ -d "$STAGED_DIR/$mode" ]]; then
      mkdir -p "$OVERLAY_DIR/$mode"
      find "$STAGED_DIR/$mode" -maxdepth 1 -type f -print0 | sort -z | while IFS= read -r -d '' path; do
        cp -f "$path" "$OVERLAY_DIR/$mode/$(basename -- "$path")"
      done
    fi
  done
  copy_if_exists \
    "$PROJECT_DIR/project-spec/meta-daphne/recipes-firmware/daphne-overlay/daphne-overlay-version.inc" \
    "$OVERLAY_DIR/daphne-overlay-version.inc"

  # Keep the exact userspace/gateware agreement beside the collected image.
  # These files are small, immutable provenance inputs; the runtime tarball
  # itself is already installed in the root filesystem and is not duplicated.
  copy_if_exists \
    "$SERVER_STAGED_DIR/BUILD-METADATA.txt" \
    "$META_DIR/DAPHNE-SERVER-BUILD-METADATA.txt"
  copy_if_exists \
    "$SERVER_STAGED_DIR/SHA256SUMS" \
    "$META_DIR/DAPHNE-SERVER-STAGED-SHA256SUMS"
  copy_if_exists \
    "$SERVER_RECIPE_DIR/daphne-server-contract.inc" \
    "$META_DIR/daphne-server-contract.inc"
  copy_if_exists \
    "$SERVER_RECIPE_DIR/daphne-server-version.inc" \
    "$META_DIR/daphne-server-version.inc"
fi

# This checkout owns image tooling, not the input gateware source. Preserve
# each gateware's source identity in its copied overlay BUILD-METADATA.txt.
OS_GIT_COMMIT="unknown"
OS_GIT_DIRTY="unknown"
if command -v git >/dev/null 2>&1 && git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  OS_GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
    OS_GIT_DIRTY="true"
  else
    OS_GIT_DIRTY="false"
  fi
fi

cat > "$META_DIR/COLLECT-METADATA.txt" <<EOF
project_name=$PROJECT_NAME
machine=xilinx-k26-kr
machine_include=daphne-k26c-xsa
image_profile=$IMAGE_PROFILE
deployment_scope=$DEPLOYMENT_SCOPE
overlay_policy=$OVERLAY_POLICY
os_git_commit=$OS_GIT_COMMIT
os_git_dirty=$OS_GIT_DIRTY
EOF

(
  cd "$BUNDLE_DIR"
  find . -type f | sort > MANIFEST.txt
)

checksum_cmd=()
if command -v sha256sum >/dev/null 2>&1; then
  checksum_cmd=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  checksum_cmd=(shasum -a 256)
else
  checksum_cmd=()
fi

if (( ${#checksum_cmd[@]} > 0 )); then
  (
    cd "$BUNDLE_DIR"
    while IFS= read -r -d '' path; do
      "${checksum_cmd[@]}" "$path"
    done < <(find . -type f ! -path ./SHA256SUMS -print0 | sort -z)
  ) > "$BUNDLE_DIR/SHA256SUMS"
fi

if [[ -e "$FINAL_BUNDLE_DIR" ]]; then
  if [[ ! -f "$FINAL_BUNDLE_DIR/meta/COLLECT-METADATA.txt" ]]; then
    echo "ERROR: refusing to replace an output directory not created by this collector: $FINAL_BUNDLE_DIR" >&2
    exit 2
  fi
  rm -rf -- "$FINAL_BUNDLE_DIR"
fi
mv -- "$BUNDLE_DIR" "$FINAL_BUNDLE_DIR"
BUNDLE_DIR=""
trap - EXIT

BOOT_DIR="$FINAL_BUNDLE_DIR/boot"
ROOTFS_DIR="$FINAL_BUNDLE_DIR/rootfs"
OVERLAY_DIR="$FINAL_BUNDLE_DIR/overlay"
META_DIR="$FINAL_BUNDLE_DIR/meta"

cat <<EOF
Collected PetaLinux artifacts into:
  $FINAL_BUNDLE_DIR

Boot dir:
  $BOOT_DIR
Rootfs dir:
  $ROOTFS_DIR
Overlay dir:
  $OVERLAY_DIR
Meta dir:
  $META_DIR
EOF
