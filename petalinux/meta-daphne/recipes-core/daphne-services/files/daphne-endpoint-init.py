#!/bin/sh
set -eu

ENDPOINT_BASE=$((0x84000000))
REG_CLOCK_CONTROL=$((ENDPOINT_BASE + 0x0))
REG_CLOCK_STATUS=$((ENDPOINT_BASE + 0x4))
REG_ENDPOINT_CONTROL=$((ENDPOINT_BASE + 0x8))
REG_ENDPOINT_STATUS=$((ENDPOINT_BASE + 0xC))

BIT_MMCM_RESET=1
BIT_CLOCK_SOURCE=2
BIT_MMCM0_LOCKED=0
BIT_MMCM1_LOCKED=1
BIT_ENDPOINT_RESET=16
BIT_TIMESTAMP_OK=4
MASK_ENDPOINT_ADDR=0xFFFF
MASK_FSM_STATUS=0xF

[ -f /etc/default/firmware ] && . /etc/default/firmware
[ -f /etc/daphne-board.env ] && . /etc/daphne-board.env

TIMING_PROFILE="${TIMING_PROFILE:-}"
[ -n "$TIMING_PROFILE" ] || {
  echo "TIMING_PROFILE not set; skipping endpoint init."
  exit 0
}
[ "$TIMING_PROFILE" = "endpoint-sync-v14" ] || {
  echo "Unknown TIMING_PROFILE=$TIMING_PROFILE" >&2
  exit 1
}

command -v devmem >/dev/null 2>&1 || {
  echo "Missing devmem" >&2
  exit 1
}

ENDPOINT_ADDR=$(( ${ENDPOINT_ADDR_HEX:-0x20} ))
ENDPOINT_WAIT_MS="${ENDPOINT_WAIT_MS:-1000}"
ENDPOINT_SUCCESS_STATES="${ENDPOINT_SUCCESS_STATES:-0x8}"
CLOCK_SOURCE="${ENDPOINT_CLOCK_SOURCE:-1}"

if [ "$ENDPOINT_WAIT_MS" -lt 1000 ]; then
  ENDPOINT_WAIT_MS=1000
fi

pause_us() {
  delay="$1"
  if busybox usleep "$delay" 2>/dev/null; then
    return 0
  fi
  sleep 0.1
}

read_reg() {
  devmem "$1" 32
}

write_reg() {
  devmem "$1" 32 "$2" >/dev/null
}

read_reg_dec() {
  value="$(read_reg "$1")"
  printf '%u\n' "$((value))"
}

set_bit() {
  reg="$1"
  bit="$2"
  enabled="$3"
  value="$(read_reg_dec "$reg")"
  if [ "$enabled" = "1" ]; then
    value=$(( value | (1 << bit) ))
  else
    value=$(( value & ~(1 << bit) ))
  fi
  write_reg "$reg" "$value"
}

pulse_bit() {
  reg="$1"
  bit="$2"
  set_bit "$reg" "$bit" 1
  pause_us 10000
  set_bit "$reg" "$bit" 0
}

set_endpoint_address() {
  value="$(read_reg_dec "$REG_ENDPOINT_CONTROL")"
  value=$(( (value & ~MASK_ENDPOINT_ADDR) | (ENDPOINT_ADDR & MASK_ENDPOINT_ADDR) ))
  write_reg "$REG_ENDPOINT_CONTROL" "$value"
}

status_matches_success() {
  status="$1"
  fsm=$(( status & MASK_FSM_STATUS ))
  timestamp_ok=$(( (status >> BIT_TIMESTAMP_OK) & 0x1 ))

  old_ifs="$IFS"
  IFS=','
  set -- $ENDPOINT_SUCCESS_STATES
  IFS="$old_ifs"

  for state in "$@"; do
    [ -n "$state" ] || continue
    want=$((state))
    if [ "$fsm" -eq "$want" ]; then
      if [ "$fsm" -eq 8 ] && [ "$timestamp_ok" -ne 1 ]; then
        return 1
      fi
      return 0
    fi
  done
  return 1
}

wait_loops=$(( (ENDPOINT_WAIT_MS + 49) / 50 ))
mmcm_loops="$wait_loops"
endpoint_loops="$wait_loops"

set_bit "$REG_CLOCK_CONTROL" "$BIT_CLOCK_SOURCE" "$CLOCK_SOURCE"
pulse_bit "$REG_CLOCK_CONTROL" "$BIT_MMCM_RESET"

while [ "$mmcm_loops" -gt 0 ]; do
  status="$(read_reg_dec "$REG_CLOCK_STATUS")"
  mmcm0_locked=$(( (status >> BIT_MMCM0_LOCKED) & 0x1 ))
  mmcm1_locked=$(( (status >> BIT_MMCM1_LOCKED) & 0x1 ))
  if [ "$mmcm0_locked" -eq 1 ] && [ "$mmcm1_locked" -eq 1 ]; then
    break
  fi
  pause_us 50000
  mmcm_loops=$(( mmcm_loops - 1 ))
done

[ "$mmcm_loops" -gt 0 ] || {
  echo "Endpoint MMCMs did not lock in time." >&2
  exit 1
}

set_endpoint_address
pulse_bit "$REG_ENDPOINT_CONTROL" "$BIT_ENDPOINT_RESET"

while [ "$endpoint_loops" -gt 0 ]; do
  endpoint_status="$(read_reg_dec "$REG_ENDPOINT_STATUS")"
  if status_matches_success "$endpoint_status"; then
    timestamp_ok=$(( (endpoint_status >> BIT_TIMESTAMP_OK) & 0x1 ))
    fsm_status=$(( endpoint_status & MASK_FSM_STATUS ))
    printf 'Endpoint ready: address=0x%04x timestamp_ok=%s fsm_status=0x%x\n' \
      "$ENDPOINT_ADDR" "$timestamp_ok" "$fsm_status"
    exit 0
  fi
  pause_us 50000
  endpoint_loops=$(( endpoint_loops - 1 ))
done

echo "Endpoint status did not reach an expected ready state." >&2
exit 1
