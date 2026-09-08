#!/bin/sh
set -eu

APP="${APP:-daphne_selftrigger_ol_a389fcd}"
APP_DIR="${ACCEL_CONFIG_PATH:-/lib/firmware/xilinx}/${APP}"
APP_BIN="${APP_DIR}/${APP}.bin"
APP_DTBO="${APP_DIR}/${APP}.dtbo"

start_dfx_mgr() {
  for unit in dfx-mgr.service dfx-mgrd.service; do
    if systemctl list-unit-files "$unit" 2>/dev/null | awk '{print $1}' | grep -qx "$unit"; then
      systemctl is-active --quiet "$unit" || systemctl start "$unit"
      return 0
    fi
  done
  return 0
}

if command -v xmutil >/dev/null 2>&1; then
  start_dfx_mgr
  echo "Loading ${APP} via xmutil ..."
  xmutil loadapp "${APP}"
elif command -v dfx-mgr-client >/dev/null 2>&1; then
  start_dfx_mgr
  echo "Loading ${APP} via dfx-mgr-client ..."
  dfx-mgr-client -loadByName "${APP}"
elif command -v fpgautil >/dev/null 2>&1; then
  if [ ! -r "${APP_BIN}" ]; then
    echo "Missing bitstream: ${APP_BIN}" >&2
    exit 1
  fi
  if [ ! -r "${APP_DTBO}" ]; then
    echo "Missing dtbo: ${APP_DTBO}" >&2
    exit 1
  fi
  echo "Loading ${APP} via fpgautil ..."
  fpgautil -b "${APP_BIN}" -o "${APP_DTBO}" -f Full -n full
else
  echo "Neither fpgautil, dfx-mgr-client, nor xmutil is available." >&2
  exit 1
fi

st=unknown
for _ in $(seq 1 50); do
  st=$(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo unknown)
  [ "$st" = "operating" ] && break
  sleep 0.2
done
echo "FPGA state: ${st}"
if [ "$st" != "operating" ]; then
  echo "FPGA did not reach operating state after loading ${APP}." >&2
  exit 1
fi
