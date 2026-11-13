#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash scripts/led_intensity_scan.sh --output-folder DIR --channels '[0,1]'
    --bias-control VALUE (--vbias VALUE | --vbias-list LIST | --vbias-range RANGE)
    (--vgain VALUE | --vgain-list LIST | --vgain-range RANGE)
    (--pulse-bias-percent-range RANGE |
     --pulse-bias-percent-270nm-list LIST --pulse-bias-percent-367nm-list LIST)
    [options]

Ranges use [start,step,end] and include the end when it falls on a step.
A shared LED range sets both wavelengths to the same code at each step.
The two explicit lists are paired by index and must have equal length.
The SSP channel mask selects which outputs fire.
Output is a new directory with bias_*/vgain_*/led_270nm_*_367nm_* points.

DAPHNE options:
  --ip HOST --port PORT --route ROUTE       Defaults: 127.0.0.1, 9876, mezz/0
  --timeout-ms MS                           Default: 30000
  --trim VALUE|LIST                         TRIM DAC code per channel (default: 0)
  --bias-safe-window-mv MIN MAX             Required for nonzero TRIM
  --allow-unmonitored-bias                  Use nominal bias and DAC readback
  --set-as-dac                              Interpret bias and bias-control as DAC codes
                                            (default: volts)
  --pedestal ADC                            Recalibrate per bias and VGAIN (default: 8192)
  -N COUNT -L SAMPLES                       Defaults: 1000 waveforms of 1024 samples
  --trigger-source SOURCE                   external (default), timing, software, all

SSP options:
  --ssp_host HOST --ssp_port PORT           Defaults: 127.0.0.1, 55001
  --ssp_config FILE                         Default: configs/led_run_defaults.json
  --ssp_number-channels COUNT               Default: 12
  --ssp_channel-mask MASK                   Default: 1
  --ssp_pulse-mode MODE                     Default: single
  --ssp_pulse-width-ticks TICKS             Default: 1
EOF
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

set_axis() {
    local axis="$1" option="$2" value="$3"
    [[ -z "${axis_option[$axis]:-}" ]] || fail "choose only one selector for $axis"
    axis_option[$axis]="$option"
    axis_value[$axis]="$value"
}

# Use exact decimal arithmetic for bias ranges and normalize integer DAC codes.
expand_values() {
    "$python_bin" - "$@" <<'PY'
from decimal import Decimal
import re
import sys

option, raw, maximum = sys.argv[1:]
pattern = r"[+-]?\d{1,9}" if maximum else r"[+-]?\d{1,9}(?:\.\d{1,9})?"

try:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    fields = raw.split(",")
    if not all(re.fullmatch(pattern, field.strip(), re.ASCII) for field in fields):
        raise ValueError("expected numeric values separated by commas")
    values = [Decimal(field.strip()) for field in fields]
    limit = Decimal(maximum) if maximum else Decimal(4095)
    if option.endswith("-range"):
        if len(values) != 3:
            raise ValueError("expected [start,step,end]")
        start, step, end = values
        if not step or (end - start) * step < 0:
            raise ValueError("step must be nonzero and point toward the end")
        if not (0 <= start <= limit and 0 <= end <= limit):
            raise ValueError(f"range endpoints must be in 0..{limit}")
        count = int((end - start) // step) + 1
        if count > 10000:
            raise ValueError("range contains more than 10000 values")
        values = (start + step * index for index in range(count))
    elif option in ("--vbias", "--vgain") and len(values) != 1:
        raise ValueError("expected a single value")
    for value in values:
        if not 0 <= value <= limit:
            raise ValueError(f"values must be in 0..{limit}")
        print(int(value) if maximum else format(value.copy_abs() if value.is_zero() else value, "f"))
except ValueError as error:
    sys.exit(f"{option}: {error}")
PY
}

require_unique() {
    local label="$1" value
    shift
    local -A seen=()
    for value in "$@"; do
        [[ -z "${seen[$value]:-}" ]] || fail "duplicate $label value $value"
        seen[$value]=1
    done
}

run_logged() {
    local logfile="$1" label="$2" status=0
    shift 2
    {
        printf '\n===== %s =====\n' "$label"
        printf 'command:'
        printf ' %q' "$@"
        printf '\n'
    } >> "$logfile" || return 1
    "$@" >> "$logfile" 2>&1 &
    active_child=$!
    wait "$active_child" || status=$?
    active_child=''
    if (( status != 0 )); then
        printf 'ERROR: %s failed (exit %s), see %s\n' "$label" "$status" "$logfile" >&2
    fi
    return "$status"
}

run_shutdown_step() {
    local label="$1"
    shift
    printf '\n===== %s =====\n' "$label" >&2
    # Keep attempting shutdown if the output directory is no longer writable.
    if { : >> "$cleanup_log"; } 2>/dev/null; then
        "$@" >> "$cleanup_log" 2>&1
    else
        "$@"
    fi
}

cleanup() {
    local status="$1" cleanup_failed=0
    trap - EXIT
    trap '' INT TERM HUP
    if [[ -n "$active_child" ]]; then
        kill -TERM "$active_child" 2>/dev/null || true
        wait "$active_child" 2>/dev/null || true
    fi
    if (( ssp_stop_pending )); then
        run_shutdown_step 'stop SSP LED pulser' "${ssp_stop[@]}" || cleanup_failed=1
    fi
    if (( bias_shutdown_pending )); then
        run_shutdown_step 'shut down bias and TRIM' \
            "$python_bin" "$client_dir/protobuf_vgain_bias.py" shutdown "${bias_sequence_args[@]}" || cleanup_failed=1
    fi
    if (( cleanup_failed )); then
        printf 'ERROR: hardware shutdown could not be confirmed. See %s\n' "$cleanup_log" >&2
        (( status != 0 )) || status=1
    fi
    if (( status == 0 )); then
        printf 'LED intensity scan complete. Data in %s\n' "$output_folder"
    fi
    exit "$status"
}

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
client_dir="$root_dir/client"
python_bin="${PYTHON:-python3}"
output_folder='' channels='' bias_control='' trim=0 pedestal=8192
ip=127.0.0.1 port=9876 route=mezz/0 timeout_ms=30000
waveform_count=1000 waveform_length=1024 trigger_source=external
ssp_host=127.0.0.1 ssp_port=55001 ssp_config="$root_dir/configs/led_run_defaults.json"
ssp_channels=12 ssp_mask=1 ssp_mode=single ssp_width=1
led_range='' led_270_list='' led_367_list=''
declare -A axis_option=() axis_value=()
declare -a bias_window=() bias_units=() monitor_args=()

while (( $# )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --set-as-dac) bias_units=(--set-as-dac); shift; continue ;;
        --allow-unmonitored-bias) monitor_args=(--allow-unmonitored-bias); shift; continue ;;
        --bias-safe-window-mv)
            [[ $# -ge 3 && $2 =~ ^[0-9]+$ && $3 =~ ^[0-9]+$ ]] || fail "$1 requires MIN MAX"
            bias_window=("$1" "$2" "$3")
            shift 3
            continue ;;
    esac
    [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || fail "$1 requires a value"
    case "$1" in
        --output-folder) output_folder="$2" ;;
        --channels) channels="$2" ;;
        --vbias|--vbias-list|--vbias-range) set_axis vbias "$1" "$2" ;;
        --vgain|--vgain-list|--vgain-range) set_axis vgain "$1" "$2" ;;
        --bias-control) bias_control="$2" ;;
        --trim) trim="$2" ;;
        --pedestal) pedestal="$2" ;;
        --ip) ip="$2" ;;
        --port) port="$2" ;;
        --route) route="$2" ;;
        --timeout-ms) timeout_ms="$2" ;;
        -N) waveform_count="$2" ;;
        -L) waveform_length="$2" ;;
        --trigger-source) trigger_source="$2" ;;
        --ssp_host) ssp_host="$2" ;;
        --ssp_port) ssp_port="$2" ;;
        --ssp_config) ssp_config="$2" ;;
        --ssp_number-channels) ssp_channels="$2" ;;
        --ssp_channel-mask) ssp_mask="$2" ;;
        --ssp_pulse-mode) ssp_mode="$2" ;;
        --ssp_pulse-width-ticks) ssp_width="$2" ;;
        --pulse-bias-percent-range) led_range="$2" ;;
        --pulse-bias-percent-270nm-list) led_270_list="$2" ;;
        --pulse-bias-percent-367nm-list) led_367_list="$2" ;;
        *) fail "unknown option $1 (see --help)" ;;
    esac
    shift 2
done

[[ -n "$output_folder" && -n "$channels" && -n "$bias_control" ]] || fail 'provide --output-folder, --channels and --bias-control (see --help)'
[[ -n "${axis_option[vbias]:-}" && -n "${axis_option[vgain]:-}" ]] || fail 'provide one bias and one VGAIN selector (see --help)'
for value in "$port" "$ssp_port" "$timeout_ms" "$waveform_count" "$waveform_length"; do
    [[ "$value" =~ ^[1-9][0-9]{0,8}$ ]] || fail "expected a positive integer, got '$value'"
done
(( port <= 65535 && ssp_port <= 65535 )) || fail 'ports must be in 1..65535'
[[ "$pedestal" =~ ^[0-9]{1,5}$ ]] && (( 10#$pedestal <= 16383 )) || fail 'pedestal must be in 0..16383'
case "$trigger_source" in
    external|timing|software|all) ;;
    *) fail 'trigger source must be external, timing, software or all' ;;
esac

values=$(expand_values --channels "$channels" 39) || exit 1
mapfile -t channel_list <<< "$values"
require_unique channel "${channel_list[@]}"
afe=$((channel_list[0] / 8))
for channel in "${channel_list[@]}"; do
    (( channel / 8 == afe )) || fail 'select channels from a single AFE'
done

values=$(expand_values --trim "$trim" 4095) || exit 1
mapfile -t trim_list <<< "$values"
if (( ${#trim_list[@]} != 1 && ${#trim_list[@]} != ${#channel_list[@]} )); then
    fail 'provide a single TRIM value or one value per channel'
fi
trim_map=()
for index in "${!channel_list[@]}"; do
    trim_map+=("${channel_list[index]}:${trim_list[index]:-${trim_list[0]}}")
done

bias_limit=''
if (( ${#bias_units[@]} )); then bias_limit=4095; fi
values=$(expand_values "${axis_option[vbias]}" "${axis_value[vbias]}" "$bias_limit") || exit 1
mapfile -t bias_list <<< "$values"
require_unique bias "${bias_list[@]}"
values=$(expand_values "${axis_option[vgain]}" "${axis_value[vgain]}" 4095) || exit 1
mapfile -t vgain_list <<< "$values"
require_unique VGAIN "${vgain_list[@]}"

if [[ -n "$led_range" ]]; then
    [[ -z "$led_270_list" && -z "$led_367_list" ]] || fail 'choose the shared LED range or the two LED lists'
    values=$(expand_values --pulse-bias-percent-range "$led_range" 4095) || exit 1
    mapfile -t led_270 <<< "$values"
    led_367=("${led_270[@]}")
else
    [[ -n "$led_270_list" && -n "$led_367_list" ]] || fail 'provide the shared LED range or both LED lists'
    values=$(expand_values --pulse-bias-percent-270nm-list "$led_270_list" 4095) || exit 1
    mapfile -t led_270 <<< "$values"
    values=$(expand_values --pulse-bias-percent-367nm-list "$led_367_list" 4095) || exit 1
    mapfile -t led_367 <<< "$values"
    (( ${#led_270[@]} == ${#led_367[@]} )) || fail 'both LED lists must have equal length'
fi
led_folders=()
for index in "${!led_270[@]}"; do
    printf -v folder 'led_270nm_%04d_367nm_%04d' "${led_270[index]}" "${led_367[index]}"
    led_folders+=("$folder")
done
require_unique 'LED pair' "${led_folders[@]}"

common_args=(-ip "$ip" -port "$port" --route "$route" --timeout-ms "$timeout_ms")
bias_sequence_args=("${common_args[@]}" --afe "$afe" --state-file "$output_folder/.bias_trim_state.json"
                    "${bias_window[@]}" "${monitor_args[@]}")
bias_apply_args=("${bias_sequence_args[@]}" --bias-control "$bias_control" --trim-map "${trim_map[@]}" "${bias_units[@]}")
ssp_connection=(--host "$ssp_host" --port "$ssp_port")
ssp_run_args=("${ssp_connection[@]}" --config "$ssp_config" --number-channels "$ssp_channels"
              --channel-mask "$ssp_mask" --pulse-mode "$ssp_mode" --pulse-width-ticks "$ssp_width")
ssp_stop=(bash "$client_dir/ssp_led_stop" "${ssp_connection[@]}")

# Validate the effective SSP config with the same parser used by ssp_led_run.
"$python_bin" -B - "$client_dir" "${ssp_run_args[@]}" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
from ssp_led_control import build_parser, merge_config, validate_config

try:
    validate_config(merge_config(build_parser().parse_args(["run", *sys.argv[2:]])))
except (OSError, TypeError, ValueError) as error:
    sys.exit(f"SSP configuration: {error}")
PY
"$python_bin" "$client_dir/protobuf_vgain_bias.py" validate "${bias_apply_args[@]}" --bias "${bias_list[@]}"

[[ ! -e "$output_folder" && ! -L "$output_folder" ]] || fail "output folder already exists: $output_folder"
mkdir -p -- "$(dirname -- "$output_folder")"
mkdir -- "$output_folder"

active_child=''
ssp_stop_pending=1
bias_shutdown_pending=0
cleanup_log="$output_folder/shutdown.log"
trap 'cleanup "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

run_logged "$cleanup_log" 'stop SSP before configuring DAPHNE' "${ssp_stop[@]}"
ssp_stop_pending=0

for bias in "${bias_list[@]}"; do
    bias_folder="$output_folder/bias_$bias"
    mkdir -- "$bias_folder"
    bias_log="$bias_folder/bias_config.txt"
    printf 'bias=%s\nbias_control=%s\ntrim_map=%s\n' "$bias" "$bias_control" "${trim_map[*]}" > "$bias_log"
    bias_shutdown_pending=1
    run_logged "$bias_log" 'apply bias and TRIM' \
        "$python_bin" "$client_dir/protobuf_vgain_bias.py" apply "${bias_apply_args[@]}" --bias "$bias"
    run_logged "$bias_log" 'read back bias and TRIM' \
        "$python_bin" "$client_dir/protobuf_read_configuration.py" "${common_args[@]}" \
        -channel "${channel_list[@]}" -afe "$afe" --trim --bias --bias-control --compact

    for vgain in "${vgain_list[@]}"; do
        vgain_folder="$bias_folder/vgain_$vgain"
        mkdir -- "$vgain_folder"
        config_log="$vgain_folder/config.txt"
        printf 'vgain=%s\npedestal_target=%s\n' "$vgain" "$pedestal" > "$config_log"
        run_logged "$config_log" 'configure VGAIN' \
            "$python_bin" "$client_dir/protobuf_configure_vgain.py" "${common_args[@]}" -afe "$afe" -vgain_value "$vgain"
        run_logged "$config_log" 'calibrate pedestal' \
            "$python_bin" "$client_dir/protobuf_configure_pedestal_level.py" "${common_args[@]}" \
            -channel "${channel_list[@]}" --use-current-offset -target_pedestal "$pedestal" \
            -method regula_falsi --auto -L "$waveform_length"

        for index in "${!led_folders[@]}"; do
            point_folder="$vgain_folder/${led_folders[index]}"
            mkdir -- "$point_folder"
            printf 'Acquiring bias=%s VGAIN=%s LED 270nm=%s 367nm=%s\n' \
                "$bias" "$vgain" "${led_270[index]}" "${led_367[index]}"
            ssp_stop_pending=1
            run_logged "$point_folder/ssp.log" 'start SSP LED pulser' \
                bash "$client_dir/ssp_led_run" "${ssp_run_args[@]}" \
                --pulse-bias-percent-270nm "${led_270[index]}" --pulse-bias-percent-367nm "${led_367[index]}"
            run_logged "$point_folder/acquire.log" 'acquire waveforms' \
                "$python_bin" "$client_dir/protobuf_acquire_list_channels.py" \
                -ip "$ip" -port "$port" --route "$route" --timeout_ms "$timeout_ms" \
                -foldername "$point_folder" -channel_list "${channel_list[@]}" \
                -N "$waveform_count" -L "$waveform_length" --trigger-source "$trigger_source"
            run_logged "$point_folder/ssp.log" 'stop SSP LED pulser' "${ssp_stop[@]}"
            ssp_stop_pending=0
            for channel in "${channel_list[@]}"; do
                data_file="$point_folder/channel_$channel.dat"
                [[ -f "$data_file" ]] && (( $(wc -c < "$data_file") == 2 * waveform_count * waveform_length )) \
                    || fail "incomplete waveform data: $data_file"
            done
            touch -- "$point_folder/.scan_point_complete"
        done
    done
done
