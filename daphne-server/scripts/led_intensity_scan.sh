#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash scripts/led_intensity_scan.sh --output-folder DIR --channels '[0,1]'
    --bias-control VALUE (--vbias VALUE | --vbias-list LIST | --vbias-range RANGE |
                          --vbias-list-afeN LIST [--vbias-list-afeM LIST ...])
    (--vgain VALUE | --vgain-list LIST | --vgain-range RANGE)
    (--pulse-bias-percent-range RANGE |
     --pulse-bias-percent-270nm-list LIST --pulse-bias-percent-367nm-list LIST)
    [options]

Ranges use [start,step,end] and include the end when it falls on a step.
A shared LED range sets both wavelengths to the same code at each step.
The two explicit lists are paired by index and must have equal length.
The SSP channel mask selects which outputs fire.
With per-AFE selectors (--vbias-list-afeN or --vbias-range-afeN), supply
one selector for each AFE represented in --channels. AFE N owns channels
8*N through 8*N+7 (N=0..4). Each round captures the remaining AFEs together
and saves data under AFE_N/bias_*/vgain_*/led_270nm_*_367nm_*.
Global bias selectors select one AFE and keep the bias_*/vgain_*/led_*/ layout.
Completed points have verified SHA256SUMS. The scan-wide SHA256SUMS is
verified after SSP and bias/TRIM shutdown.

Scan options:
  -y, --yes                                 Confirm the scan for unattended execution
  -v, --verbose                             Show commands and client output live

DAPHNE options:
  --ip HOST --port PORT --route ROUTE       Defaults: 127.0.0.1, 9876, mezz/0
  --timeout-ms MS                           Default: 30000
  --trim VALUE|LIST                         TRIM DAC codes in --channels order (default: 0)
  --bias-safe-window-mv MIN MAX             Required for nonzero TRIM
  --allow-unmonitored-bias                  Use nominal bias and DAC readback
  --set-as-dac                              Interpret bias and bias-control as DAC codes
                                            (default: volts)
  --pedestal ADC                            Recalibrate per bias and VGAIN (default: 8192)
  --plateau-margin ADC                      Signed ADC margin added to a confirmed pedestal
                                            plateau when the scan target is unreachable
  --plateau-diff ADC                        Maximum difference between interior plateau probes
                                            (default: 10 ADC, used with --plateau-margin)
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

point_checksum_files() {
    local channel
    local -a channels_for_afe
    read -r -a channels_for_afe <<< "${afe_channels[$1]}"
    point_files=(config.txt ssp.log acquire.log)
    for channel in "${channels_for_afe[@]}"; do
        point_files+=("channel_$channel.dat")
    done
}

write_point_checksums() (
    local folder="$1" afe="$2"
    local -a point_files
    point_checksum_files "$afe"
    cd -- "$folder" &&
        sha256sum -- "${point_files[@]}" > .SHA256SUMS.tmp &&
        sha256sum --check --strict --quiet .SHA256SUMS.tmp &&
        mv -- .SHA256SUMS.tmp SHA256SUMS
)

write_scan_checksum_entries() {
    local afe prefix bias vgain led bias_dir vgain_dir point_dir file line
    local hash_line='^([0-9a-f]{64})  (.+)$'
    local -a biases point_files
    sha256sum -- shutdown.log || return 1
    for afe in "${afes[@]}"; do
        prefix=''
        if [[ "${afe_folder[$afe]}" != "$output_folder" ]]; then prefix="AFE_$afe/"; fi
        read -r -a biases <<< "${afe_bias_values[$afe]}"
        point_checksum_files "$afe"
        for bias in "${biases[@]}"; do
            bias_dir="${prefix}bias_$bias"
            sha256sum -- "$bias_dir/bias_config.txt" || return 1
            for vgain in "${vgain_list[@]}"; do
                vgain_dir="$bias_dir/vgain_$vgain"
                sha256sum -- "$vgain_dir/config.txt" || return 1
                for led in "${led_folders[@]}"; do
                    point_dir="$vgain_dir/$led"
                    sha256sum -- "$point_dir/SHA256SUMS" "$point_dir/.scan_point_complete" || return 1
                    # Reuse each point's hashes and require exactly the expected inventory.
                    {
                        for file in "${point_files[@]}"; do
                            if ! IFS= read -r line || [[ ! "$line" =~ $hash_line || "${BASH_REMATCH[2]}" != "$file" ]]; then
                                printf 'ERROR: invalid SHA-256 inventory in %s/SHA256SUMS (expected %s)\n' "$point_dir" "$file" >&2
                                return 1
                            fi
                            printf '%s  %s/%s\n' "${BASH_REMATCH[1]}" "$point_dir" "$file" || return 1
                        done
                        if IFS= read -r line || [[ -n "$line" ]]; then
                            printf 'ERROR: extra SHA-256 entries in %s/SHA256SUMS\n' "$point_dir" >&2
                            return 1
                        fi
                    } < "$point_dir/SHA256SUMS" || return 1
                done
            done
        done
    done
}

write_scan_checksums() (
    cd -- "$output_folder" &&
        write_scan_checksum_entries > .SHA256SUMS.tmp &&
        sha256sum --check --strict --quiet .SHA256SUMS.tmp &&
        mv -- .SHA256SUMS.tmp SHA256SUMS
)

confirm_scan() {
    local units='V' answer afe
    if (( ${#bias_units[@]} )); then units='DAC'; fi
    printf '\nLED intensity scan\n'
    printf '  Output folder       %s\n' "$output_folder"
    printf '  DAPHNE              %s:%s, route %s, timeout %s ms\n' "$ip" "$port" "$route" "$timeout_ms"
    printf '  Bias control        %s %s\n' "$bias_control" "$units"
    for afe in "${afes[@]}"; do
        printf '  AFE %s               channels %s\n' "$afe" "${afe_channels[$afe]}"
        printf '    Bias (%s)          %s\n' "$units" "${afe_bias_values[$afe]}"
        printf '    TRIM (ch:DAC)     %s\n' "${afe_trim_map[$afe]}"
    done
    if (( ${#bias_window[@]} )); then
        printf '  Safe bias window    %s to %s mV\n' "${bias_window[1]}" "${bias_window[2]}"
    fi
    if (( ${#monitor_args[@]} )); then
        printf '  Bias verification   nominal voltage and DAC readback\n'
    fi
    printf '  VGAIN (DAC)         %s\n' "${vgain_list[*]}"
    printf '  Pedestal            %s ADC per bias and VGAIN\n' "$pedestal"
    if [[ -n "$plateau_margin" ]]; then
        printf '  Plateau margin      %s ADC\n' "$plateau_margin"
        printf '  Plateau difference  %s ADC max\n' "${plateau_diff:-10}"
    fi
    printf '  Acquisition         %s waveforms/channel, %s samples, trigger %s\n' \
        "$waveform_count" "$waveform_length" "$trigger_source"
    printf '  Integrity           File size and SHA-256 per point, then scan-wide SHA-256\n'
    printf '  SSP                 %s:%s, config %s\n' "$ssp_host" "$ssp_port" "$ssp_config"
    printf '  SSP outputs         %s channels, mask %s, mode %s, width %s ticks\n' \
        "$ssp_channels" "$ssp_mask" "$ssp_mode" "$ssp_width"
    if [[ -n "$led_range" ]]; then
        printf '  LED range (both)    %s\n' "$led_range"
    else
        printf '  LED 270 nm / 367 nm %s / %s\n' "$led_270_list" "$led_367_list"
    fi
    printf '  Captures            %s (%s bias rounds × %s VGAIN × %s LED)\n\n' \
        "$total_points" "$bias_rounds" "${#vgain_list[@]}" "${#led_folders[@]}"

    if (( assume_yes )); then
        printf 'Confirmation accepted by --yes.\n'
        return
    fi
    [[ -t 0 ]] || fail 'interactive confirmation requires a terminal; use --yes for unattended execution'
    if read -r -p 'Continue with this scan? [y/N] ' answer; then
        case "${answer,,}" in
            y|yes) return ;;
        esac
    fi
    printf 'Scan cancelled.\n'
    exit 1
}

show_progress() {
    local width=24 filled remaining elapsed eta='--:--:--' bar gap
    filled=$((completed_points * width / total_points))
    printf -v bar '%*s' "$filled" ''
    printf -v gap '%*s' "$((width - filled))" ''
    if (( completed_points > 0 )); then
        elapsed=$((SECONDS - scan_started))
        remaining=$(((elapsed * (total_points - completed_points) + completed_points - 1) / completed_points))
        printf -v eta '%02d:%02d:%02d' "$((remaining / 3600))" "$((remaining / 60 % 60))" "$((remaining % 60))"
    fi
    if (( progress_inline )); then printf '\r' >&2; fi
    printf '[%s%s] %3d%%  %d/%d points  ETA %s' "${bar// /#}" "${gap// /-}" \
        "$((completed_points * 100 / total_points))" "$completed_points" "$total_points" "$eta" >&2
    if (( progress_inline )); then
        progress_open=1
    else
        printf '\n' >&2
    fi
}

end_progress_line() {
    if (( progress_open )); then
        printf '\n' >&2
        progress_open=0
    fi
}

run_logged() {
    local logfile="$1" label="$2" status=0 log_fd log_pid=''
    shift 2
    {
        printf '\n===== %s =====\n' "$label"
        printf 'command:'
        printf ' %q' "$@"
        printf '\n'
    } >> "$logfile" || return 1
    if (( verbose )); then
        printf '\n===== %s =====\n' "$label" >&2
        printf 'command:' >&2
        printf ' %q' "$@" >&2
        printf '\n' >&2
        exec {log_fd}> >(tee -a -- "$logfile" >&2)
        log_pid=$!
    else
        exec {log_fd}>> "$logfile" || return 1
    fi
    "$@" >&"$log_fd" 2>&1 &
    active_child=$!
    exec {log_fd}>&-
    wait "$active_child" || status=$?
    active_child=''
    if [[ -n "$log_pid" ]] && ! wait "$log_pid"; then
        (( status != 0 )) || status=1
    fi
    if (( status != 0 )); then
        end_progress_line
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
        if (( verbose )); then
            printf 'command:' >&2
            printf ' %q' "$@" >&2
            printf '\n' >&2
            "$@" 2>&1 | tee -a -- "$cleanup_log" >&2
        else
            "$@" >> "$cleanup_log" 2>&1
        fi
    else
        "$@"
    fi
}

set_bias_sequence_args() {
    local afe="$1"
    bias_sequence_args=("${common_args[@]}" --afe "$afe" --state-file "${afe_folder[$afe]}/.bias_trim_state.json"
                        "${bias_window[@]}" "${monitor_args[@]}")
}

cleanup() {
    local status="$1" cleanup_failed=0 afe
    trap - EXIT
    trap '' INT TERM HUP
    end_progress_line
    if [[ -n "$active_child" ]]; then
        kill -TERM "$active_child" 2>/dev/null || true
        wait "$active_child" 2>/dev/null || true
    fi
    run_shutdown_step 'stop SSP LED pulser' "${ssp_stop[@]}" || cleanup_failed=1
    for afe in "${afes[@]}"; do
        if [[ "${bias_shutdown_pending[$afe]:-0}" == 1 ]]; then
            set_bias_sequence_args "$afe"
            run_shutdown_step "shut down AFE $afe bias and TRIM" \
                "$python_bin" "$client_dir/protobuf_vgain_bias.py" shutdown "${bias_sequence_args[@]}" || cleanup_failed=1
        fi
    done
    if (( cleanup_failed )); then
        printf 'ERROR: hardware shutdown could not be confirmed. See %s\n' "$cleanup_log" >&2
        (( status != 0 )) || status=1
    fi
    if (( status == 0 )); then
        trap - INT TERM HUP
        printf 'Verifying scan-wide SHA-256 checksums.\n' >&2
        if write_scan_checksums; then
            printf 'LED intensity scan complete. Data in %s\n' "$output_folder"
        else
            printf 'ERROR: scan-wide SHA-256 verification failed in %s\n' "$output_folder" >&2
            status=1
        fi
    fi
    exit "$status"
}

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
client_dir="$root_dir/client"
python_bin="${PYTHON:-python3}"
output_folder='' channels='' bias_control='' trim=0 pedestal=8192 plateau_margin='' plateau_diff=''
ip=127.0.0.1 port=9876 route=mezz/0 timeout_ms=30000
waveform_count=1000 waveform_length=1024 trigger_source=external
ssp_host=127.0.0.1 ssp_port=55001 ssp_config="$root_dir/configs/led_run_defaults.json"
ssp_channels=12 ssp_mask=1 ssp_mode=single ssp_width=1
led_range='' led_270_list='' led_367_list=''
assume_yes=0 verbose=0 progress_inline=0 progress_open=0
declare -A axis_option=() axis_value=()
declare -a bias_window=() bias_units=() monitor_args=()
declare -a pedestal_plateau_args=()

while (( $# )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        -y|--yes) assume_yes=1; shift; continue ;;
        -v|--verbose) verbose=1; shift; continue ;;
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
        --vbias-list-afe[0-4]|--vbias-range-afe[0-4]) set_axis "afe${1##*afe}" "${1%-afe[0-4]}" "$2" ;;
        --vgain|--vgain-list|--vgain-range) set_axis vgain "$1" "$2" ;;
        --bias-control) bias_control="$2" ;;
        --trim) trim="$2" ;;
        --pedestal) pedestal="$2" ;;
        --plateau-margin) plateau_margin="$2" ;;
        --plateau-diff) plateau_diff="$2" ;;
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
[[ -n "${axis_option[vgain]:-}" ]] || fail 'provide one VGAIN selector (see --help)'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required for scan file integrity verification'
for value in "$port" "$ssp_port" "$timeout_ms" "$waveform_count" "$waveform_length"; do
    [[ "$value" =~ ^[1-9][0-9]{0,8}$ ]] || fail "expected a positive integer, got '$value'"
done
(( port <= 65535 && ssp_port <= 65535 )) || fail 'ports must be in 1..65535'
[[ "$pedestal" =~ ^[0-9]{1,5}$ ]] && (( 10#$pedestal <= 16383 )) || fail 'pedestal must be in 0..16383'
if [[ -n "$plateau_margin" ]]; then
    margin_magnitude="${plateau_margin#[+-]}"
    [[ "$margin_magnitude" =~ ^[0-9]{1,5}$ ]] && (( 10#$margin_magnitude <= 16383 )) ||
        fail "plateau margin must be an integer in -16383..16383 (got '$plateau_margin')"
    pedestal_plateau_args+=(--plateau-margin "$plateau_margin")
fi
if [[ -n "$plateau_diff" ]]; then
    [[ "$plateau_diff" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] ||
        fail "plateau difference must be a nonnegative decimal (got '$plateau_diff')"
    pedestal_plateau_args+=(--plateau-diff "$plateau_diff")
fi
case "$trigger_source" in
    external|timing|software|all) ;;
    *) fail 'trigger source must be external, timing, software or all' ;;
esac

values=$(expand_values --channels "$channels" 39) || exit 1
mapfile -t channel_list <<< "$values"
require_unique channel "${channel_list[@]}"

values=$(expand_values --trim "$trim" 4095) || exit 1
mapfile -t trim_list <<< "$values"
if (( ${#trim_list[@]} != 1 && ${#trim_list[@]} != ${#channel_list[@]} )); then
    fail 'provide a single TRIM value or one value per channel'
fi
declare -a afes=() afe_channels=() afe_trim_map=() afe_folder=() afe_bias_values=() afe_bias_count=()
for index in "${!channel_list[@]}"; do
    channel=${channel_list[index]}
    afe=$((channel / 8))
    afe_channels[$afe]+="$channel "
    afe_trim_map[$afe]+="$channel:${trim_list[index]:-${trim_list[0]}} "
done
afes=("${!afe_channels[@]}")

bias_limit=''
if (( ${#bias_units[@]} )); then bias_limit=4095; fi
bias_rounds=0
if [[ -n "${axis_option[vbias]:-}" ]]; then
    (( ${#afes[@]} == 1 )) || fail 'use per-AFE bias selectors when selecting channels from multiple AFEs'
fi
for afe in {0..4}; do
    if [[ -n "${axis_option[afe$afe]:-}" ]]; then
        [[ -n "${afe_channels[$afe]:-}" ]] || fail "bias specified for AFE $afe without selected channels"
        [[ -z "${axis_option[vbias]:-}" ]] || fail 'choose a global bias selector or per-AFE selectors'
    fi
done
for afe in "${afes[@]}"; do
    axis="afe$afe"
    afe_folder[$afe]="$output_folder/AFE_$afe"
    if [[ -n "${axis_option[vbias]:-}" ]]; then
        axis=vbias
        afe_folder[$afe]="$output_folder"
    fi
    [[ -n "${axis_option[$axis]:-}" ]] || fail "missing bias selector for AFE $afe"
    values=$(expand_values "${axis_option[$axis]}" "${axis_value[$axis]}" "$bias_limit") || exit 1
    mapfile -t bias_list <<< "$values"
    require_unique "AFE $afe bias" "${bias_list[@]}"
    afe_bias_values[$afe]="${bias_list[*]}"
    afe_bias_count[$afe]=${#bias_list[@]}
    if (( afe_bias_count[afe] > bias_rounds )); then bias_rounds=${afe_bias_count[afe]}; fi
done
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
ssp_connection=(--host "$ssp_host" --port "$ssp_port")
ssp_run=(bash "$client_dir/ssp_led_run")
ssp_run_args=("${ssp_connection[@]}" --config "$ssp_config" --number-channels "$ssp_channels"
              --pulse-mode "$ssp_mode" --pulse-width-ticks "$ssp_width")
ssp_stop=(bash "$client_dir/ssp_led_stop" "${ssp_connection[@]}")

# Validate the effective SSP config with the same parser used by ssp_led_run.
"$python_bin" -B - "$client_dir" "${ssp_run_args[@]}" --channel-mask "$ssp_mask" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
from ssp_led_control import build_parser, merge_config, validate_config

try:
    validate_config(merge_config(build_parser().parse_args(["run", *sys.argv[2:]])))
except (OSError, TypeError, ValueError) as error:
    sys.exit(f"SSP configuration: {error}")
PY
for afe in "${afes[@]}"; do
    set_bias_sequence_args "$afe"
    read -r -a trim_map <<< "${afe_trim_map[$afe]}"
    read -r -a bias_list <<< "${afe_bias_values[$afe]}"
    "$python_bin" "$client_dir/protobuf_vgain_bias.py" validate "${bias_sequence_args[@]}" \
        --bias-control "$bias_control" --trim-map "${trim_map[@]}" "${bias_units[@]}" --bias "${bias_list[@]}"
done

[[ ! -e "$output_folder" && ! -L "$output_folder" ]] || fail "output folder already exists: $output_folder"
total_points=$((bias_rounds * ${#vgain_list[@]} * ${#led_folders[@]}))
confirm_scan
if (( verbose )); then export PYTHONUNBUFFERED=1; fi
mkdir -p -- "$(dirname -- "$output_folder")"
mkdir -- "$output_folder"

active_child=''
declare -a bias_shutdown_pending=()
cleanup_log="$output_folder/shutdown.log"
trap 'cleanup "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if [[ -t 2 ]] && (( ! verbose )); then progress_inline=1; fi
completed_points=0
scan_started=$SECONDS
show_progress

run_logged "$cleanup_log" 'stop SSP before configuring DAPHNE' "${ssp_stop[@]}"

declare -a round_afes=() active_channels=() bias_folder=() vgain_folder=() point_folder=()
capture_folder="$output_folder/.capture"

for (( round = 0; round < bias_rounds; round += 1 )); do
    round_afes=()
    active_channels=()
    for afe in "${afes[@]}"; do
        if (( round >= afe_bias_count[afe] )); then continue; fi
        round_afes+=("$afe")
        read -r -a afe_channel_list <<< "${afe_channels[$afe]}"
        active_channels+=("${afe_channel_list[@]}")
        read -r -a bias_list <<< "${afe_bias_values[$afe]}"
        read -r -a trim_map <<< "${afe_trim_map[$afe]}"
        bias=${bias_list[round]}
        bias_folder[$afe]="${afe_folder[$afe]}/bias_$bias"
        mkdir -p -- "${bias_folder[$afe]}"
        bias_log="${bias_folder[$afe]}/bias_config.txt"
        printf 'afe=%s\nround=%s\nbias=%s\nbias_control=%s\ntrim_map=%s\n' \
            "$afe" "$((round + 1))" "$bias" "$bias_control" "${trim_map[*]}" > "$bias_log"
        set_bias_sequence_args "$afe"
        bias_shutdown_pending[$afe]=1
        run_logged "$bias_log" "apply AFE $afe bias and TRIM" \
            "$python_bin" "$client_dir/protobuf_vgain_bias.py" apply "${bias_sequence_args[@]}" \
            --bias-control "$bias_control" --trim-map "${trim_map[@]}" "${bias_units[@]}" --bias "$bias"
        run_logged "$bias_log" "read back AFE $afe bias and TRIM" \
            "$python_bin" "$client_dir/protobuf_read_configuration.py" "${common_args[@]}" \
            -channel "${afe_channel_list[@]}" -afe "$afe" --trim --bias --bias-control --compact
    done

    for vgain in "${vgain_list[@]}"; do
        for afe in "${round_afes[@]}"; do
            vgain_folder[$afe]="${bias_folder[$afe]}/vgain_$vgain"
            mkdir -- "${vgain_folder[$afe]}"
            config_log="${vgain_folder[$afe]}/config.txt"
            printf 'vgain=%s\npedestal_target=%s\n' "$vgain" "$pedestal" > "$config_log"
            if [[ -n "$plateau_margin" ]]; then
                printf 'pedestal_plateau_margin=%s\n' "$plateau_margin" >> "$config_log"
                printf 'pedestal_plateau_diff=%s\n' "${plateau_diff:-10}" >> "$config_log"
            fi
            run_logged "$config_log" "configure AFE $afe VGAIN" \
                "$python_bin" "$client_dir/protobuf_configure_vgain.py" "${common_args[@]}" -afe "$afe" -vgain_value "$vgain"
            read -r -a afe_channel_list <<< "${afe_channels[$afe]}"
            run_logged "$config_log" "calibrate AFE $afe pedestal" \
                "$python_bin" "$client_dir/protobuf_configure_pedestal_level.py" "${common_args[@]}" \
                -channel "${afe_channel_list[@]}" --use-current-offset -target_pedestal "$pedestal" \
                -method regula_falsi --auto -L "$waveform_length" "${pedestal_plateau_args[@]}"
        done
        for afe in "${round_afes[@]}"; do
            read -r -a afe_channel_list <<< "${afe_channels[$afe]}"
            run_logged "${vgain_folder[$afe]}/config.txt" "read back AFE $afe configuration after pedestal calibration" \
                "$python_bin" "$client_dir/protobuf_read_configuration.py" "${common_args[@]}" \
                -channel "${afe_channel_list[@]}" -afe "$afe" --offset --trim --bias --vgain --bias-control --compact
        done

        for index in "${!led_folders[@]}"; do
            if (( verbose )); then
                printf 'Acquiring bias round %s, AFEs %s, VGAIN=%s LED 270nm=%s 367nm=%s\n' \
                    "$((round + 1))" "${round_afes[*]}" "$vgain" "${led_270[index]}" "${led_367[index]}" >&2
            fi
            for afe in "${round_afes[@]}"; do
                point_folder[$afe]="${vgain_folder[$afe]}/${led_folders[index]}"
                mkdir -- "${point_folder[$afe]}"
            done

            # The client writes one file per channel. Stage the shared capture
            # until every channel has the expected number of samples.
            first_afe=${round_afes[0]}
            acquisition_folder=${point_folder[$first_afe]}
            if (( ${#round_afes[@]} > 1 )); then
                mkdir -- "$capture_folder"
                acquisition_folder=$capture_folder
            fi
            run_logged "$acquisition_folder/ssp.log" 'configure SSP LED intensity' \
                "${ssp_run[@]}" "${ssp_run_args[@]}" --channel-mask "$ssp_mask" \
                --pulse-bias-percent-270nm "${led_270[index]}" --pulse-bias-percent-367nm "${led_367[index]}"
            run_logged "$acquisition_folder/acquire.log" 'acquire waveforms' \
                "$python_bin" "$client_dir/protobuf_acquire_list_channels.py" \
                -ip "$ip" -port "$port" --route "$route" --timeout_ms "$timeout_ms" \
                -foldername "$acquisition_folder" -channel_list "${active_channels[@]}" \
                -N "$waveform_count" -L "$waveform_length" --trigger-source "$trigger_source"
            for channel in "${active_channels[@]}"; do
                data_file="$acquisition_folder/channel_$channel.dat"
                [[ -f "$data_file" ]] && (( $(wc -c < "$data_file") == 2 * waveform_count * waveform_length )) \
                    || fail "incomplete waveform data: $data_file"
            done
            if [[ "$acquisition_folder" == "$capture_folder" ]]; then
                for channel in "${active_channels[@]}"; do
                    mv -- "$capture_folder/channel_$channel.dat" "${point_folder[channel / 8]}/"
                done
                for afe in "${round_afes[@]}"; do
                    cp -- "$capture_folder/ssp.log" "$capture_folder/acquire.log" "${point_folder[$afe]}/"
                done
                rm -- "$capture_folder/ssp.log" "$capture_folder/acquire.log"
                rmdir -- "$capture_folder"
            fi
            for afe in "${round_afes[@]}"; do
                cp -- "${vgain_folder[$afe]}/config.txt" "${point_folder[$afe]}/config.txt"
                write_point_checksums "${point_folder[$afe]}" "$afe" \
                    || fail "SHA-256 verification failed: ${point_folder[$afe]}"
            done
            complete_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
            for afe in "${round_afes[@]}"; do
                printf 'complete_utc=%s\n' "$complete_utc" > "${point_folder[$afe]}/.scan_point_complete"
            done
            (( completed_points += 1 ))
            show_progress
        done

        # Keep the next bias/VGAIN transition and pedestal calibration in the dark.
        if (( completed_points < total_points )); then
            run_logged "$cleanup_log" 'disable SSP outputs before the next pedestal' \
                "${ssp_run[@]}" "${ssp_run_args[@]}" --channel-mask 0 \
                --pulse-bias-percent-270nm 0 --pulse-bias-percent-367nm 0
        fi
    done

    if (( round + 1 < bias_rounds )); then
        for afe in "${round_afes[@]}"; do
            if (( round + 1 == afe_bias_count[afe] )); then
                set_bias_sequence_args "$afe"
                run_logged "$cleanup_log" "shut down completed AFE $afe bias and TRIM" \
                    "$python_bin" "$client_dir/protobuf_vgain_bias.py" shutdown "${bias_sequence_args[@]}"
                bias_shutdown_pending[$afe]=0
            fi
        done
    fi
done
