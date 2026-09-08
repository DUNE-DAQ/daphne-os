#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: generate_qspi_boot_candidates.sh IMAGES_DIR [OUT_DIR]

Generate explicit QSPI-primary boot-image candidates from an images/linux
directory using local bootgen. This preserves the stock PetaLinux BOOT.BIN
alongside narrower KR260-oriented variants for recovery and comparison work.

Outputs:
  BOOT.stock.BIN
  BOOT.no-system-dtb.BIN
  BOOT.u-boot-dtb.BIN
  BOOT.primary.BIN
  bootgen.stock.bif
  bootgen.no-system-dtb.bif
  bootgen.u-boot-dtb.bif
  bootgen.primary.bif
  PRIMARY-BOOT-BANKS.txt
  PRIMARY-BOOT-METADATA.txt
  *.read.txt
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 || $# -gt 2 ]]; then
  usage
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi

IMAGES_DIR="$(CDPATH= cd -- "$1" && pwd)"
OUT_DIR_INPUT="${2:-$IMAGES_DIR/qspi-primary}"
OUT_DIR="$(mkdir -p "$OUT_DIR_INPUT" && CDPATH= cd -- "$OUT_DIR_INPUT" && pwd)"
ROOT_DIR="${DAPHNE_OS_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"
TEMPLATE_DIR="$ROOT_DIR/scripts/petalinux/bifs"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command '$1' not found on PATH" >&2
    exit 2
  }
}

need_cmd bootgen
need_cmd grep
need_cmd sed

required=(
  "$IMAGES_DIR/zynqmp_fsbl.elf"
  "$IMAGES_DIR/pmufw.elf"
  "$IMAGES_DIR/bl31.elf"
  "$IMAGES_DIR/u-boot.elf"
  "$IMAGES_DIR/u-boot-dtb.elf"
)

for path in "${required[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "ERROR: missing required boot component: $path" >&2
    exit 2
  fi
done

write_bif_from_template() {
  local bif_path="$1"
  local template_name="$2"

  sed "s#@IMAGES_DIR@#$IMAGES_DIR#g" "$TEMPLATE_DIR/$template_name" > "$bif_path"
}

build_candidate() {
  local stem="$1"
  local template_name="$2"
  local bif_path="$OUT_DIR/$stem.bif"
  local bin_path="$OUT_DIR/$stem.BIN"
  local read_path="$OUT_DIR/$stem.read.txt"

  write_bif_from_template "$bif_path" "$template_name"
  bootgen -arch zynqmp -image "$bif_path" -w on -o "$bin_path" >/dev/null 2>&1
  bootgen -arch zynqmp -read "$bin_path" > "$read_path"
}

assert_contains() {
  local path="$1"
  local pattern="$2"
  if ! grep -Fq -- "$pattern" "$path"; then
    echo "ERROR: expected pattern not found in $(basename "$path"): $pattern" >&2
    exit 3
  fi
}

assert_not_contains() {
  local path="$1"
  local pattern="$2"
  if grep -Fq -- "$pattern" "$path"; then
    echo "ERROR: unexpected pattern found in $(basename "$path"): $pattern" >&2
    exit 3
  fi
}

if [[ -f "$IMAGES_DIR/BOOT.BIN" ]]; then
  cp -f "$IMAGES_DIR/BOOT.BIN" "$OUT_DIR/BOOT.stock.BIN"
  bootgen -arch zynqmp -read "$IMAGES_DIR/BOOT.BIN" > "$OUT_DIR/BOOT.stock.read.txt"
fi

if [[ -f "$IMAGES_DIR/bootgen.bif" ]]; then
  cp -f "$IMAGES_DIR/bootgen.bif" "$OUT_DIR/bootgen.stock.bif"
fi

build_candidate "BOOT.no-system-dtb" "qspi-primary-no-system-dtb.bif.in"
build_candidate "BOOT.u-boot-dtb" "qspi-primary-u-boot-dtb.bif.in"

cp -f "$OUT_DIR/BOOT.u-boot-dtb.BIN" "$OUT_DIR/BOOT.primary.BIN"
cp -f "$OUT_DIR/BOOT.u-boot-dtb.read.txt" "$OUT_DIR/BOOT.primary.read.txt"
cp -f "$OUT_DIR/BOOT.u-boot-dtb.bif" "$OUT_DIR/bootgen.primary.bif"

assert_contains "$OUT_DIR/BOOT.primary.read.txt" "IMAGE HEADER (zynqmp_fsbl.elf)"
assert_contains "$OUT_DIR/BOOT.primary.read.txt" "IMAGE HEADER (bl31.elf)"
assert_contains "$OUT_DIR/BOOT.primary.read.txt" "IMAGE HEADER (u-boot-dtb.elf)"
assert_not_contains "$OUT_DIR/BOOT.primary.read.txt" "IMAGE HEADER (system.dtb)"
assert_not_contains "$OUT_DIR/BOOT.primary.read.txt" "IMAGE HEADER (u-boot.elf)"

cat > "$OUT_DIR/PRIMARY-BOOT-VALIDATION.txt" <<EOF
validated_image=BOOT.primary.BIN
expected_image_headers=zynqmp_fsbl.elf,bl31.elf,u-boot-dtb.elf
unexpected_image_headers=system.dtb,u-boot.elf
validation_method=bootgen-read-grep
validated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

cat > "$OUT_DIR/PRIMARY-BOOT-BANKS.txt" <<EOF
bank_a_label=Image A (FSBL, PMU, ATF, U-Boot)
bank_a_mtd_default=mtd5
bank_a_offset_hex=0x00200000
bank_a_multiboot_hex=0x40
bank_b_label=Image B (FSBL, PMU, ATF, U-Boot)
bank_b_mtd_default=mtd7
bank_b_offset_hex=0x00f80000
bank_b_multiboot_hex=0x1f0
EOF

cat > "$OUT_DIR/PRIMARY-BOOT-METADATA.txt" <<EOF
intended_primary_boot_image=BOOT.primary.BIN
selected_source_image=BOOT.u-boot-dtb.BIN
selected_source_bif=bootgen.u-boot-dtb.bif
selection_rationale=Prefer FSBL+PMUFW+BL31+U-Boot primary boot image without separate runtime system.dtb partition
stock_reference_image=BOOT.stock.BIN
fallback_candidate_image=BOOT.no-system-dtb.BIN
generated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
images_dir=$IMAGES_DIR
EOF

cat <<EOF
Generated QSPI-primary boot candidates in:
  $OUT_DIR
EOF
