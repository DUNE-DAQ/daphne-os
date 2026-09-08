#!/bin/sh
# Repo-owned version of the clock-chip bring-up currently used on
# NP04-DAPHNE-014 from daphne-server branch
# marroyav/server_bringup_thresholds at
# aa2942a58d62e19a49cdfbf0b382ed118fcef9a5.

set -eu

[ -f /etc/default/firmware ] && . /etc/default/firmware
[ -f /etc/daphne-board.env ] && . /etc/daphne-board.env

BUS="${CLOCKCHIP_BUS:-auto}"
CHIP="${CLOCKCHIP_ADDR:-0x70}"
VERIFY="${CLOCKCHIP_VERIFY:-0}"
DRYRUN="${CLOCKCHIP_DRYRUN:-0}"
DO_RESET="${CLOCKCHIP_DO_RESET:-1}"
ONLY_FILTER="${CLOCKCHIP_ONLY:-}"
VERBOSE="${CLOCKCHIP_VERBOSE:-0}"
LOGDIR="${CLOCKCHIP_LOGDIR:-/var/log/daphne-clockchip}"
DISCOVERY_ADDRS="${CLOCKCHIP_DISCOVERY_ADDRS:-${CHIP} 0x71 0x72}"

usage() {
  cat <<EOF
Usage: $0 [--bus N|auto] [--chip 0x70] [--verify] [--dry-run] [--no-reset]
          [--only <ranges>] [--verbose] [--logdir DIR]
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --bus) BUS="$2"; shift 2 ;;
    --chip) CHIP="$2"; shift 2 ;;
    --verify) VERIFY=1; shift ;;
    --dry-run) DRYRUN=1; shift ;;
    --no-reset) DO_RESET=0; shift ;;
    --only) ONLY_FILTER="${2:-}"; shift 2 ;;
    --verbose) VERBOSE=1; shift ;;
    --logdir) LOGDIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

for cmd in i2cset i2cget i2cdetect; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing $cmd" >&2; exit 2; }
done

mkdir -p "$LOGDIR"
TS="$(date +%Y%m%d_%H%M%S)"
chip_tag="$(printf '%s' "$CHIP" | tr -d '0x')"
verify_suffix=""
[ "$VERIFY" = "1" ] && verify_suffix="_ver"
LOGFILE="${LOGDIR}/clk_conf_${TS}_bus${BUS}_chip${chip_tag}${verify_suffix}.log"

hex() { printf "0x%02X" "$1"; }
log() { echo "$*" >> "$LOGFILE"; }
out() { [ "$VERBOSE" = "1" ] && echo "$*" >&2; log "$*"; }

probe_addr_on_bus() {
  bus="$1"
  addr="$2"
  token="$(i2cdetect -y "$bus" "$addr" "$addr" 2>/dev/null | awk 'END{print $2}')"
  want="$(printf '%02x' "$((addr))")"
  [ "$token" = "$want" ] || [ "$token" = "UU" ]
}

bus_exists() {
  [ -c "/dev/i2c-$1" ]
}

score_bus() {
  bus="$1"
  score=0
  for addr in $DISCOVERY_ADDRS; do
    if probe_addr_on_bus "$bus" "$addr"; then
      score=$((score + 1))
    fi
  done
  printf '%s\n' "$score"
}

discover_bus() {
  best_bus=""
  best_score=0

  if [ "$BUS" != "auto" ] && bus_exists "$BUS"; then
    preferred_score="$(score_bus "$BUS")"
    out "Preferred bus ${BUS} score=${preferred_score}"
    if [ "$preferred_score" -gt 0 ]; then
      printf '%s\n' "$BUS"
      return 0
    fi
  fi

  for node in /dev/i2c-*; do
    [ -e "$node" ] || continue
    bus="${node##*/i2c-}"
    score="$(score_bus "$bus")"
    out "Candidate bus ${bus} score=${score}"
    if [ "$score" -gt "$best_score" ]; then
      best_bus="$bus"
      best_score="$score"
    fi
  done

  if [ -n "$best_bus" ] && [ "$best_score" -gt 0 ]; then
    printf '%s\n' "$best_bus"
    return 0
  fi

  return 1
}

ONLY_HAS=0
RANGE_LO=""
RANGE_HI=""
SINGLES=""
if [ -n "$ONLY_FILTER" ]; then
  ONLY_HAS=1
  old_ifs="$IFS"
  IFS=','
  set -- $ONLY_FILTER
  IFS="$old_ifs"
  for token in "$@"; do
    case "$token" in
      0x*-0x*)
        lo="${token%-*}"
        hi="${token#*-}"
        RANGE_LO="${RANGE_LO} $((lo))"
        RANGE_HI="${RANGE_HI} $((hi))"
        ;;
      0x*)
        SINGLES="${SINGLES} $((token))"
        ;;
      *)
        echo "Bad --only token: $token" >&2
        exit 2
        ;;
    esac
  done
fi

allowed() {
  addr="$1"
  [ "$ONLY_HAS" = "0" ] && return 0
  for single in $SINGLES; do
    [ "$addr" -eq "$single" ] && return 0
  done
  set -- $RANGE_LO
  lows="$*"
  set -- $RANGE_HI
  highs="$*"
  i=1
  for lo in $lows; do
    hi=$(printf '%s\n' $highs | sed -n "${i}p")
    [ -n "$hi" ] && [ "$addr" -ge "$lo" ] && [ "$addr" -le "$hi" ] && return 0
    i=$((i + 1))
  done
  return 1
}

write_reg() {
  reg="$1"
  val="$2"
  if [ "$DRYRUN" = "1" ]; then
    out "i2cset -y ${BUS} ${CHIP} $(hex "$reg") $(hex "$val") (dry-run)"
    return 0
  fi
  if ! i2cset -y "$BUS" "$CHIP" "$(hex "$reg")" "$(hex "$val")" >/dev/null 2>&1; then
    out "WRITE ERROR $(hex "$reg") <- $(hex "$val")"
    return 1
  fi
  out "WRITE OK    $(hex "$reg") <- $(hex "$val")"
  return 0
}

read_reg() {
  i2cget -y "$BUS" "$CHIP" "$(hex "$1")"
}

verify_reg() {
  reg="$1"
  want="$2"
  if ! got_hex="$(read_reg "$reg" 2>/dev/null)"; then
    out "READ ERROR  $(hex "$reg") (wanted $(hex "$want"))"
    return 2
  fi
  got=$((got_hex))
  if [ "$got" -ne "$want" ]; then
    out "MISMATCH    $(hex "$reg") want=$(hex "$want") got=${got_hex}"
    return 1
  fi
  out "VERIFY OK   $(hex "$reg") == $(hex "$want")"
  return 0
}

REGVALS='
0x06 0x08
0x1C 0x0B 0x1D 0x08 0x1E 0xB0 0x1F 0xC0
0x20 0xE3 0x21 0xE3 0x22 0xC0 0x23 0x41
0x24 0x06 0x25 0x00 0x26 0x00 0x27 0x06
0x28 0x64 0x29 0x0C 0x2A 0x24 0x2D 0x00
0x2E 0x00 0x2F 0x14 0x30 0x3A 0x31 0x00
0x32 0xC4 0x33 0x07 0x34 0x10 0x35 0x00
0x36 0x06 0x37 0x00 0x38 0x00 0x39 0x00
0x3A 0x00 0x3B 0x01 0x3C 0x00 0x3D 0x00
0x3E 0x00 0x3F 0x10 0x40 0x00 0x41 0x00
0x42 0x00 0x43 0x00 0x44 0x00 0x45 0x00
0x46 0x00 0x47 0x00 0x48 0x00 0x49 0x00
0x4A 0x10 0x4B 0x00 0x4C 0x00 0x4D 0x00
0x4E 0x00 0x4F 0x00 0x50 0x00 0x51 0x00
0x52 0x00 0x53 0x00 0x54 0x00 0x55 0x10
0x56 0x80 0x57 0x0A 0x58 0x00 0x59 0x00
0x5A 0x00 0x5B 0x00 0x5C 0x01 0x5D 0x00
0x5E 0x00 0x5F 0x00 0x61 0x00 0x62 0x30
0x63 0x00 0x64 0x00 0x65 0x00 0x66 0x00
0x67 0x01 0x68 0x00 0x69 0x00 0x6A 0x80
0x6B 0x00 0x6C 0x00 0x6D 0x00 0x6E 0x40
0x6F 0x00 0x70 0x00 0x71 0x00 0x72 0x40
0x73 0x00 0x74 0x80 0x75 0x00 0x76 0x40
0x77 0x00 0x78 0x00 0x79 0x00 0x7A 0x40
0x7B 0x00 0x7C 0x00 0x7D 0x00 0x7E 0x00
0x7F 0x00 0x80 0x00 0x81 0x00 0x82 0x00
0x83 0x00 0x84 0x00 0x85 0x00 0x86 0x00
0x87 0x00 0x88 0x00 0x89 0x00 0x8A 0x00
0x8B 0x00 0x8C 0x00 0x8D 0x00 0x8E 0x00
0x8F 0x00 0x90 0x00 0x98 0x00 0x99 0x00
0x9A 0x00 0x9B 0x00 0x9C 0x00 0x9D 0x00
0x9E 0x00 0x9F 0x00 0xA0 0x00 0xA1 0x00
0xA2 0x00 0xA3 0x00 0xA4 0x00 0xA5 0x00
0xA6 0x00 0xA7 0x00 0xA8 0x00 0xA9 0x00
0xAA 0x00 0xAB 0x00 0xAC 0x00 0xAD 0x00
0xAE 0x00 0xAF 0x00 0xB0 0x00 0xB1 0x00
0xB2 0x00 0xB3 0x00 0xB4 0x00 0xB5 0x00
0xB6 0x00 0xB7 0x00 0xB8 0x00 0xB9 0x00
0xBA 0x00 0xBB 0x00 0xBC 0x00 0xBD 0x00
0xBE 0x00 0xBF 0x00 0xC0 0x00 0xC1 0x00
0xC2 0x00 0xC3 0x00 0xC4 0x00 0xC5 0x00
0xC6 0x00 0xC7 0x00 0xC8 0x00 0xC9 0x00
0xCA 0x00 0xCB 0x00 0xCC 0x00 0xCD 0x00
0xCE 0x00 0xCF 0x00 0xD0 0x00 0xD1 0x00
0xD2 0x00 0xD3 0x00 0xD4 0x00 0xD5 0x00
0xD6 0x00 0xD7 0x00 0xD8 0x00 0xD9 0x00
0xE6 0x06
'

RESET_REG=0xF6

if ! BUS="$(discover_bus)"; then
  echo "Could not discover a clockchip bus for ${CHIP}. Candidates scanned from /dev/i2c-*." >&2
  echo "Discovery addresses: ${DISCOVERY_ADDRS}" >&2
  exit 1
fi

echo "Starting clock-chip programming (bus=${BUS}, chip=${CHIP})"
log "Clock chip programming bus=${BUS} chip=${CHIP}"
log "Discovery addresses: ${DISCOVERY_ADDRS}"
log "Log file: ${LOGFILE}"

errors=0
total=0

set -- $REGVALS
while [ $# -gt 1 ]; do
  reg="$1"
  val="$2"
  shift 2
  reg_d=$((reg))
  val_d=$((val))
  if ! allowed "$reg_d"; then
    continue
  fi
  if ! write_reg "$reg_d" "$val_d"; then
    errors=$((errors + 1))
    continue
  fi
  total=$((total + 1))
  if [ "$VERIFY" = "1" ]; then
    if ! verify_reg "$reg_d" "$val_d"; then
      errors=$((errors + 1))
    fi
  fi
done

if allowed $((0xE6)); then
  if got_hex="$(read_reg $((0xE6)) 2>/dev/null)"; then
    out "READ 0xE6 -> ${got_hex}"
  else
    out "READ ERROR 0xE6"
    errors=$((errors + 1))
  fi
fi

if [ "$DO_RESET" = "1" ]; then
  echo "Resetting clock chip"
  for v in 0x02 0x00; do
    if [ "$DRYRUN" = "1" ]; then
      out "i2cset -y ${BUS} ${CHIP} $(hex $((RESET_REG))) $(hex $((v))) (dry-run)"
    else
      if ! i2cset -y "$BUS" "$CHIP" "$(hex $((RESET_REG)))" "$(hex $((v)))" >/dev/null 2>&1; then
        out "RESET WRITE ERROR $(hex $((RESET_REG))) <- $(hex $((v)))"
        errors=$((errors + 1))
      fi
      sleep 0.02
    fi
  done
else
  out "Skipping reset (--no-reset)"
fi

echo "Done configuring the clock chip"
echo "Programmed ${total} register(s) on bus ${BUS}, chip ${CHIP}."
if [ "$VERIFY" = "1" ]; then
  echo "Verification enabled."
fi

if [ "$errors" -gt 0 ]; then
  echo "Completed with ${errors} error(s). See ${LOGFILE}" >&2
  exit 1
fi

echo "Completed with no detected errors. Full log: ${LOGFILE}"
