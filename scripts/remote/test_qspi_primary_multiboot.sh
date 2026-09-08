#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: test_qspi_primary_multiboot.sh [BUNDLE_DIR]

From a live U-Boot prompt, set the temporary MultiBoot register for a selected
QSPI image bank and issue reset. This helper does not catch the next prompt for
you; it only performs the handoff using the repo-owned bank metadata.

Options:
  --bank a|b            Select the bank to test. Default: b
  --device PATH         Serial device path. Default: /dev/ttyUSB2
  --baudrate N          Serial baud rate. Default: 115200
  --timeout SEC         Per-command timeout. Default: 20
  --catch-timeout SEC   Timeout for the post-reset U-Boot catch. Default: 180
  --no-reset            Only program the MultiBoot register, do not reset/catch
  --log PATH            Serial transcript path
  --bank-map PATH       Override PRIMARY-BOOT-BANKS.txt location
  --dry-run             Print the resolved command sequence only
  -h, --help            Show this help.
EOF
}

bundle_dir=""
bank="b"
device="/dev/ttyUSB2"
baudrate="115200"
timeout_s="20"
catch_timeout_s="180"
log_path=""
bank_map=""
do_reset=1
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bank)
      bank="$2"
      shift 2
      ;;
    --device)
      device="$2"
      shift 2
      ;;
    --baudrate)
      baudrate="$2"
      shift 2
      ;;
    --timeout)
      timeout_s="$2"
      shift 2
      ;;
    --catch-timeout)
      catch_timeout_s="$2"
      shift 2
      ;;
    --no-reset)
      do_reset=0
      shift
      ;;
    --log)
      log_path="$2"
      shift 2
      ;;
    --bank-map)
      bank_map="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "ERROR: unknown option: $1" >&2
      exit 2
      ;;
    *)
      if [[ -z "$bundle_dir" ]]; then
        bundle_dir="$1"
      else
        echo "ERROR: unexpected positional argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

case "$bank" in
  a|b) ;;
  *)
    echo "ERROR: --bank must be 'a' or 'b'" >&2
    exit 2
    ;;
esac

ROOT_DIR="${DAPHNE_OS_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}"

if [[ -z "$bank_map" ]]; then
  if [[ -n "$bundle_dir" ]]; then
    bundle_dir="$(CDPATH= cd -- "$bundle_dir" && pwd)"
    bank_map="$bundle_dir/boot/qspi-primary/PRIMARY-BOOT-BANKS.txt"
  else
    echo "ERROR: provide BUNDLE_DIR or --bank-map PATH" >&2
    exit 2
  fi
fi

if [[ ! -f "$bank_map" ]]; then
  echo "ERROR: missing bank map metadata: $bank_map" >&2
  exit 2
fi

get_meta() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {print substr($0, index($0, "=") + 1)}' "$bank_map"
}

multiboot_hex="$(get_meta "bank_${bank}_multiboot_hex")"
offset_hex="$(get_meta "bank_${bank}_offset_hex")"
label="$(get_meta "bank_${bank}_label")"

if [[ -z "$multiboot_hex" || -z "$offset_hex" || -z "$label" ]]; then
  echo "ERROR: incomplete bank metadata for bank '$bank' in $bank_map" >&2
  exit 2
fi

program_commands=(
  "zynqmp mmio_read 0xFFCA0010"
  "zynqmp mmio_write 0xFFCA0010 0xfff $multiboot_hex"
  "zynqmp mmio_read 0xFFCA0010"
)

cat <<EOF
Bank:            $bank
Label:           $label
Offset:          $offset_hex
MultiBoot value: $multiboot_hex
Device:          $device
Baudrate:        $baudrate
Timeout:         $timeout_s
Catch timeout:   $catch_timeout_s
Bank map:        $bank_map
EOF

printf 'Program commands:\n'
printf '  %s\n' "${program_commands[@]}"
if (( do_reset )); then
  printf 'Reset/catch:\n'
  printf '  reset\n'
fi

if (( dry_run )); then
  exit 0
fi

cmd=(
  python3
  "$ROOT_DIR/scripts/remote/uboot_serial.py"
  --device "$device"
  --baudrate "$baudrate"
  --timeout "$timeout_s"
)

if [[ -n "$log_path" ]]; then
  cmd+=(--log "$log_path")
fi

cmd+=("${program_commands[@]}")

"${cmd[@]}"

if (( ! do_reset )); then
  exit 0
fi

catch_cmd=(
  python3
  "$ROOT_DIR/scripts/remote/serial_catch_uboot.py"
  --device "$device"
  --baudrate "$baudrate"
  --timeout "$catch_timeout_s"
  --initial-command "reset"
)

if [[ -n "$log_path" ]]; then
  catch_cmd+=(--log "$log_path")
fi

"${catch_cmd[@]}"
