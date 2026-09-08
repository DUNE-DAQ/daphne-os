#!/bin/sh

set -eu

FW_ENV_CONFIG=/etc/fw_env.config
FW_PRINTENV=/usr/bin/fw_printenv
FW_SETENV=/usr/bin/fw_setenv

get_var() {
    env LD_LIBRARY_PATH=/usr/lib "$FW_PRINTENV" -n -c "$FW_ENV_CONFIG" "$1" 2>/dev/null || true
}

active_slot="$(get_var active_slot)"
[ -n "$active_slot" ] || exit 0

last_good_slot="$(get_var last_good_slot)"
upgrade_available="$(get_var upgrade_available)"
bootcount="$(get_var bootcount)"

needs_write=0
[ "$last_good_slot" = "$active_slot" ] || needs_write=1
[ "${upgrade_available:-0}" = "0" ] || needs_write=1
[ "${bootcount:-0}" = "0" ] || needs_write=1
[ "$needs_write" -eq 1 ] || exit 0

env LD_LIBRARY_PATH=/usr/lib "$FW_SETENV" -c "$FW_ENV_CONFIG" last_good_slot "$active_slot"
env LD_LIBRARY_PATH=/usr/lib "$FW_SETENV" -c "$FW_ENV_CONFIG" upgrade_available 0
env LD_LIBRARY_PATH=/usr/lib "$FW_SETENV" -c "$FW_ENV_CONFIG" bootcount 0
