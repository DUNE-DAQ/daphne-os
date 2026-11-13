#!/bin/bash

# Sweep DAPHNE V3 AFE bias (outer loop) and VGAIN (inner loop), calibrate the
# channel pedestal at every point, and acquire waveforms.

print_help() {
    cat <<'EOF'
Usage:
  source vgain_scan.sh -folder DIR -channel CH [CH ...] -ip IP -port PORT -L SAMPLES -N WAVEFORMS \
      (-vgain_list LIST | -vgain_range RANGE | -range RANGE | -vgain VALUE) \
      (-bias_list LIST | -bias_range RANGE | -bias VALUE) [options]

  source vgain_scan.sh -folder DIR --resume

At least one dimension must be a sweep (a list or range). If only one
dimension is swept, the other one is held fixed. Fixed defaults are bias=0.0
and vgain=1800.

Sweep syntax:
  -vgain_list "[1800, 2000, 2200]"    Explicit VGAIN DAC values
  -vgain_range "[1800, 100, 2200]"   Inclusive [start, step, end]
  -range RANGE                         Backward-compatible VGAIN range alias
  -bias_list "[30.0, 31.0, 32.0]"    Explicit bias values
  -bias_range "[30.0, 0.5, 32.0]"    Inclusive [start, step, end]
  -vgain VALUE                         Fixed VGAIN for a bias-only scan
  -bias VALUE                          Fixed bias for a VGAIN-only scan

Configuration options:
  --channels "0, 1, 3, 5"   Channel list, in the same order as the TRIM vector
  -trim VALUE|LIST         TRIM DAC code or positional list (default: 0)
  --bias-safe-window-mv MIN MAX
                           Validated effective SiPM voltage window in mV.
                           Required for nonzero TRIM, including the temporary
                           drop in bias before resetting TRIM.
  --allow-unmonitored-bias
                           Use nominal voltage and DAC setpoint readback instead
                           of the bias monitor. The safe window still applies.
  -bias_control VALUE      Global bias-control value (default: 0.0)
  -set_as_DAC              Interpret bias and bias-control as DAC codes;
                           without it they are interpreted as volts. TRIM and
                           VGAIN are always DAC codes.
  -pedestal VALUE          Target pedestal ADC code (default: 8192)
  --plateau-margin ADC     Signed ADC margin added to a confirmed pedestal
                           plateau when the scan target is unreachable
                           Tuning uses regula_falsi, --auto, and the current
                           OFFSET as its starting point.

Acquisition options:
  --dma                   Use DMA for pedestal tuning, data and restoration
                           (default: spybuffer). Pedestal always uses persistent
                           software acquisition with P=0.
  --force-acq              Allow DMA without approved alignment, for both
                           pedestal and data (requires --dma)
  --capture-mode MODE      DMA data: finite|triggered|persistent
                           (default with --dma: persistent)
  --pretrigger P           DMA data samples before trigger (default: 0)
  --trigger-timeout-ms MS  DMA data event timeout (default: 10000)
  --job-timeout-ms MS      DMA data total deadline (default: 0)
  --pressure-timeout-ms MS Persistent data credit timeout (default: 0)
  -trigger_source software|external|timing|all  (default: external)
                           DMA supports software, external and timing;
                           finite requires software and P=0.
  -route ROUTE             EnvelopeV2 route (default: mezz/0)
  --timeout-ms MS          Client timeout (default: 30000)
  --identity NAME          Identity base for all child clients, including restoration
  -multi_channel           Accepted for backward compatibility; channel count
                           is inferred automatically.

On success, failure, SIGINT, SIGTERM or SIGHUP, restoration first reduces
bias by the maximum active TRIM. It then clears TRIM for the entire AFE
before writing bias=0, VGAIN=1700, and pedestal=8192. Bias-control is preserved.
Bias zero is blocked if the transition or TRIM clear cannot be confirmed.

Data integrity:
  Every completed point contains a SHA256SUMS manifest for config.txt and the
  channel_*.dat files, plus DMA format/event metadata when selected.
  After the complete scan and default restoration, a
  second SHA256SUMS manifest is written at the scan root and verified.

Resume options:
  --resume                 Load the scan plan from DIR/scan_metadata.txt,
                           remove the last incomplete/potentially corrupt
                           point, and continue. If complete, no data is removed.
                           An older plan without a saved bias window can be
                           resumed with --bias-safe-window-mv MIN MAX.
  -y, --yes                Accept the configuration summary without prompting.

Examples:
  # VGAIN-only scan at a fixed bias. Set MIN_MV and MAX_MV for your hardware.
  source vgain_scan.sh -output_folder data -vgain_range "[1800,100,2200]" \
      -bias 31.5 --channels "16, 17" --trim "[100, 200]" --bias-safe-window-mv "$MIN_MV" "$MAX_MV" \
      -bias_control 55.0 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001

  # Bias-only scan at a fixed VGAIN, with bias values expressed as DAC codes
  source vgain_scan.sh -output_folder data -bias_list "[700,750,800]" \
      -vgain 2000 -set_as_DAC -bias_control 740 -channel 16 17 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001

  # Nested bias/VGAIN scan
  source vgain_scan.sh -output_folder data -bias_range "[30,0.5,31]" \
      -vgain_list "[1800,2000]" -channel 16 17 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001

  # DMA scan, with software triggers for both pedestal and data
  bash vgain_scan.sh -folder dma_scan -vgain_list "[1700,1800]" -bias 0 \
      -channel 0 1 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001 \
      --dma --force-acq -trigger_source software --yes
EOF
}

fail() {
    echo "ERROR: $*" >&2
    return 1
}

require_value() {
    if [[ $# -lt 2 || -z "$2" ]]; then
        fail "option '$1' requires a value"
        return 1
    fi
}

parse_list() {
    local specification="$1"
    local -n destination="$2"
    local cleaned
    cleaned=$(printf '%s' "$specification" | tr '[],' '   ')
    read -r -a destination <<< "$cleaned"
    if (( ${#destination[@]} == 0 )); then
        fail "empty list: $specification"
        return 1
    fi
}

parse_dac_list() {
    local specification="$1"
    local list_pattern='^[[:blank:]]*[0-9]+(([[:blank:]]*,[[:blank:]]*|[[:blank:]]+)[0-9]+)*[[:blank:]]*$'
    if [[ "$specification" =~ ^[[:blank:]]*\[(.*)\][[:blank:]]*$ ]]; then
        specification="${BASH_REMATCH[1]}"
    fi
    if [[ ! "$specification" =~ $list_pattern ]]; then
        fail "invalid integer list '$1'"
        return 1
    fi
    parse_list "$specification" "$2"
}

parse_triplet() {
    local specification="$1"
    local -n start_ref="$2"
    local -n step_ref="$3"
    local -n end_ref="$4"
    local cleaned extra
    cleaned=$(printf '%s' "$specification" | tr '[],' '   ')
    read -r start_ref step_ref end_ref extra <<< "$cleaned"
    if [[ -z "$start_ref" || -z "$step_ref" || -z "$end_ref" || -n "$extra" ]]; then
        fail "range must contain exactly [start, step, end]: $specification"
        return 1
    fi
}

build_integer_range() {
    local specification="$1"
    local -n destination="$2"
    local start step end
    parse_triplet "$specification" start step end || return 1
    if [[ ! "$start" =~ ^[0-9]+$ || ! "$step" =~ ^-?[0-9]+$ || ! "$end" =~ ^[0-9]+$ ]]; then
        fail "VGAIN range values must be integers: $specification"
        return 1
    fi
    if (( step == 0 )); then
        fail "VGAIN range step cannot be zero"
        return 1
    fi
    if (( (end > start && step < 0) || (end < start && step > 0) )); then
        fail "VGAIN range step points away from the end value: $specification"
        return 1
    fi
    destination=()
    local value count=0
    if (( step > 0 )); then
        for ((value = start; value <= end; value += step)); do
            destination+=("$value")
            ((++count > 10000)) && { fail "VGAIN range has more than 10000 points"; return 1; }
        done
    else
        for ((value = start; value >= end; value += step)); do
            destination+=("$value")
            ((++count > 10000)) && { fail "VGAIN range has more than 10000 points"; return 1; }
        done
    fi
    return 0
}

build_decimal_range() {
    local specification="$1"
    local -n destination="$2"
    local start step end
    parse_triplet "$specification" start step end || return 1
    local generated
    if ! generated=$(awk -v start="$start" -v step="$step" -v end="$end" '
        BEGIN {
            number = "^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$"
            if (start !~ number || step !~ number || end !~ number) exit 2
            start += 0; step += 0; end += 0
            if (step == 0) exit 3
            if ((end > start && step < 0) || (end < start && step > 0)) exit 4
            tolerance = (step < 0 ? -step : step) * 1e-9 + 1e-12
            count = 0
            if (step > 0) {
                for (value = start; value <= end + tolerance; value += step) {
                    printf "%.12g\n", value
                    if (++count > 10000) exit 5
                }
            } else {
                for (value = start; value >= end - tolerance; value += step) {
                    printf "%.12g\n", value
                    if (++count > 10000) exit 5
                }
            }
        }
    '); then
        fail "invalid bias range (use numeric [start, step, end] with a nonzero step directed toward end): $specification"
        return 1
    fi
    mapfile -t destination <<< "$generated"
}

validate_dac() {
    local value="$1" label="$2"
    if [[ ! "$value" =~ ^0*[0-9]{1,4}$ ]] || (( 10#$value > 4095 )); then
        fail "$label must be an integer DAC code in 0..4095 (got '$value')"
        return 1
    fi
}

validate_positive_integer() {
    local value="$1" label="$2"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value <= 0 )); then
        fail "$label must be a positive integer (got '$value')"
        return 1
    fi
}

run_logged() {
    local log_file="$1" label="$2"
    shift 2
    {
        echo
        echo "===== $label ====="
        printf 'command:'
        printf ' %q' "$@"
        echo
    } >> "$log_file"
    if ! run_external_command "$@" >> "$log_file" 2>&1; then
        echo "ERROR: $label failed; see $log_file" >&2
        return 1
    fi
}

run_external_command() {
    local command_status
    "$@" &
    active_child_pid=$!
    wait "$active_child_pid"
    command_status=$?
    active_child_pid=""
    return "$command_status"
}

join_by_comma() {
    local IFS=,
    echo "$*"
}

verify_point_checksum_manifest() {
    local folder="$1"
    [[ -f "$folder/SHA256SUMS" ]] || return 1
    validate_point_checksum_manifest_inventory "$folder" || return 1
    (
        cd -- "$folder" || exit 1
        sha256sum --check --strict --quiet SHA256SUMS
    )
}

point_checksum_files() {
    local folder="$1" data_channel
    local -n files_ref="$2"
    files_ref=(config.txt)
    for data_channel in "${channel_list[@]}"; do
        files_ref+=("channel_${data_channel}.dat")
    done
    if [[ "$backend" == dma ]]; then
        local -a metadata_files=("$folder"/dma_metadata_*.jsonl)
        if [[ ! -s "$folder/dma_format.json" || ${#metadata_files[@]} -ne 1 || ! -s "${metadata_files[0]}" ]]; then
            fail "DMA point requires dma_format.json and exactly one nonempty dma_metadata_*.jsonl: $folder"
            return 1
        fi
        files_ref+=(dma_format.json "${metadata_files[0]##*/}")
    fi
}

validate_point_checksum_manifest_inventory() {
    local folder="$1"
    local manifest="$folder/SHA256SUMS"
    local line filename data_channel entry_count=0
    local checksum_pattern='^[0-9a-f]{64} [ *](.+)$'
    local -A expected_files=() seen_files=()
    local -a point_files=()

    [[ -f "$manifest" ]] || return 1
    point_checksum_files "$folder" point_files || return 1
    for filename in "${point_files[@]}"; do
        expected_files["$filename"]=1
    done

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        if [[ ! "$line" =~ $checksum_pattern ]]; then
            echo "ERROR: malformed SHA-256 entry in $manifest: $line" >&2
            return 1
        fi
        filename="${BASH_REMATCH[1]}"
        if [[ -z "${expected_files[$filename]+present}" ]]; then
            echo "ERROR: unexpected file '$filename' in $manifest" >&2
            return 1
        fi
        if [[ -n "${seen_files[$filename]+present}" ]]; then
            echo "ERROR: duplicate file '$filename' in $manifest" >&2
            return 1
        fi
        seen_files[$filename]=1
        ((entry_count += 1))
    done < "$manifest"

    if (( entry_count != ${#expected_files[@]} )); then
        echo "ERROR: $manifest contains $entry_count entries; expected ${#expected_files[@]}" >&2
        return 1
    fi
    for filename in "${!expected_files[@]}"; do
        if [[ -z "${seen_files[$filename]+present}" ]]; then
            echo "ERROR: missing file '$filename' in $manifest" >&2
            return 1
        fi
    done
    return 0
}

write_point_checksum_manifest() {
    local folder="$1" data_channel
    local manifest_tmp="${folder}/.SHA256SUMS.tmp.$$"
    local -a point_files=()
    point_checksum_files "$folder" point_files || return 1

    (
        cd -- "$folder" || exit 1
        sha256sum -- "${point_files[@]}"
    ) > "$manifest_tmp" || {
        rm -f -- "$manifest_tmp"
        return 1
    }
    mv -f -- "$manifest_tmp" "$folder/SHA256SUMS" || return 1
    return 0
}

verify_scan_checksum_manifest() {
    [[ -f "$output_folder/SHA256SUMS" ]] || return 1
    (
        cd -- "$output_folder" || exit 1
        sha256sum --check --strict --quiet SHA256SUMS
    )
}

write_scan_checksum_manifest() {
    local manifest_tmp="${output_folder}/.SHA256SUMS.tmp.$$"
    local checksum_bias checksum_vgain bias_dir point_dir

    # Older resumable scans may have valid-sized data but no point manifest.
    # Create the missing manifests before assembling the scan-wide one.
    for checksum_bias in "${bias_array[@]}"; do
        for checksum_vgain in "${vgain_array[@]}"; do
            point_dir="${output_folder}/vbias_${checksum_bias}/vgain_${checksum_vgain}"
            if [[ ! -f "$point_dir/SHA256SUMS" ]]; then
                write_point_checksum_manifest "$point_dir" || return 1
            fi
            validate_point_checksum_manifest_inventory "$point_dir" || return 1
        done
    done

    (
        cd -- "$output_folder" || exit 1
        for checksum_bias in "${bias_array[@]}"; do
            bias_dir="vbias_${checksum_bias}"
            sha256sum -- "$bias_dir/vbias_config.txt" || exit 1
            for checksum_vgain in "${vgain_array[@]}"; do
                point_dir="${bias_dir}/vgain_${checksum_vgain}"
                [[ -f "$point_dir/SHA256SUMS" && -f "$point_dir/.scan_point_complete" ]] || exit 1

                # Reuse the already-computed hashes of the large waveform files
                # and make their paths relative to the scan root.
                sed -E "s#^([0-9a-f]{64} [ *])#\1${point_dir}/#" "$point_dir/SHA256SUMS" || exit 1
                sha256sum -- "$point_dir/SHA256SUMS" "$point_dir/.scan_point_complete" || exit 1
            done
        done
    ) > "$manifest_tmp" || {
        rm -f -- "$manifest_tmp"
        return 1
    }
    if [[ ! -s "$manifest_tmp" ]]; then
        rm -f -- "$manifest_tmp"
        return 1
    fi
    mv -f -- "$manifest_tmp" "$output_folder/SHA256SUMS" || return 1
    verify_scan_checksum_manifest
}

write_scan_metadata() {
    local metadata_tmp="${metadata_file}.tmp.$$"
    local channel_csv bias_csv vgain_csv
    channel_csv=$(join_by_comma "${channel_list[@]}")
    bias_csv=$(join_by_comma "${bias_array[@]}")
    vgain_csv=$(join_by_comma "${vgain_array[@]}")
    {
        echo "format_version=2"
        echo "status=$scan_status_text"
        echo "created_utc=$scan_created_utc"
        echo "updated_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "channels=$channel_csv"
        echo "afe=$afe"
        echo "bias_values=$bias_csv"
        echo "bias_mode=$bias_mode"
        echo "vgain_values=$vgain_csv"
        echo "vgain_mode=$vgain_mode"
        echo "set_as_dac=$set_as_dac"
        echo "bias_control=$bias_control"
        echo "trim=$trim"
        echo "allow_unmonitored_bias=$allow_unmonitored_bias"
        if [[ -n "$bias_safe_min_mv" ]]; then
            echo "bias_safe_min_mv=$bias_safe_min_mv"
            echo "bias_safe_max_mv=$bias_safe_max_mv"
        fi
        echo "pedestal=$pedestal"
        if [[ -n "$plateau_margin" ]]; then
            echo "plateau_margin=$plateau_margin"
        fi
        echo "ip_addr=$ip_addr"
        echo "port=$port"
        echo "waveform_count=$N"
        echo "waveform_length=$L"
        echo "trigger_source=$trigger_source"
        echo "route=$route"
        echo "timeout_ms=$timeout_ms"
        echo "backend=$backend"
        echo "capture_mode=$capture_mode"
        echo "force_acq=$force_acq"
        echo "pretrigger=$pretrigger"
        echo "trigger_timeout_ms=$trigger_timeout_ms"
        echo "job_timeout_ms=$job_timeout_ms"
        echo "pressure_timeout_ms=$pressure_timeout_ms"
        echo "completed_points=$completed_points"
        echo "total_points=$total_points"
        echo "default_bias=0"
        echo "default_trim=0"
        echo "default_vgain=1700"
        echo "default_pedestal=8192"
        if [[ "$checksums_required" == true ]]; then
            echo "checksum_algorithm=sha256"
            echo "checksum_manifest=SHA256SUMS"
        fi
    } > "$metadata_tmp" || return 1
    mv -f -- "$metadata_tmp" "$metadata_file"
}

load_scan_metadata() {
    local key value format_version="" channel_csv="" bias_csv="" vgain_csv=""
    local saved_afe="" saved_checksum_algorithm="" saved_bias_min_mv="" saved_bias_max_mv=""
    local -A capture_settings=()
    [[ -f "$metadata_file" ]] || {
        fail "resume metadata not found: $metadata_file"
        return 1
    }
    while IFS='=' read -r key value; do
        value="${value%$'\r'}"
        case "$key" in
            format_version) format_version="$value" ;;
            status) scan_status_text="$value" ;;
            created_utc) scan_created_utc="$value" ;;
            channels) channel_csv="$value" ;;
            afe) saved_afe="$value" ;;
            bias_values) bias_csv="$value" ;;
            bias_mode) bias_mode="$value" ;;
            vgain_values) vgain_csv="$value" ;;
            vgain_mode) vgain_mode="$value" ;;
            set_as_dac) set_as_dac="$value" ;;
            bias_control) bias_control="$value" ;;
            trim) trim="$value" ;;
            allow_unmonitored_bias)
                case "$value" in
                    true) allow_unmonitored_bias=true ;;
                    false) ;;
                    *) fail "invalid allow_unmonitored_bias in $metadata_file"; return 1 ;;
                esac
                ;;
            bias_safe_min_mv) saved_bias_min_mv="$value" ;;
            bias_safe_max_mv) saved_bias_max_mv="$value" ;;
            pedestal) pedestal="$value" ;;
            plateau_margin) plateau_margin="$value" ;;
            ip_addr) ip_addr="$value" ;;
            port) port="$value" ;;
            waveform_count) N="$value" ;;
            waveform_length) L="$value" ;;
            trigger_source) trigger_source_arg="$value" ;;
            route) route="$value" ;;
            timeout_ms) timeout_ms="$value" ;;
            checksum_algorithm) saved_checksum_algorithm="$value" ;;
            backend|capture_mode|force_acq|pretrigger|trigger_timeout_ms|job_timeout_ms|pressure_timeout_ms)
                capture_settings["$key"]="$value" ;;
        esac
    done < "$metadata_file"

    if [[ ( "$format_version" != "1" && "$format_version" != "2" ) || -z "$channel_csv" || -z "$bias_csv" || -z "$vgain_csv" || -z "$scan_created_utc" ]]; then
        fail "invalid or incomplete resume metadata: $metadata_file"
        return 1
    fi
    if [[ "$format_version" == 2 ]]; then
        for key in backend capture_mode force_acq pretrigger trigger_timeout_ms job_timeout_ms pressure_timeout_ms; do
            if [[ -z "${capture_settings[$key]+present}" ]]; then
                fail "missing $key in resume metadata: $metadata_file"
                return 1
            fi
        done
        backend="${capture_settings[backend]}"
        capture_mode="${capture_settings[capture_mode]}"
        force_acq="${capture_settings[force_acq]}"
        pretrigger="${capture_settings[pretrigger]}"
        trigger_timeout_ms="${capture_settings[trigger_timeout_ms]}"
        job_timeout_ms="${capture_settings[job_timeout_ms]}"
        pressure_timeout_ms="${capture_settings[pressure_timeout_ms]}"
    elif (( ${#capture_settings[@]} )); then
        fail "version 1 metadata cannot contain DMA settings: $metadata_file"
        return 1
    fi
    if [[ "$set_as_dac" != true && "$set_as_dac" != false ]]; then
        fail "invalid set_as_dac value in $metadata_file"
        return 1
    fi
    case "$saved_checksum_algorithm" in
        "") checksums_required=false ;;
        sha256) checksums_required=true ;;
        *) fail "unsupported checksum algorithm '$saved_checksum_algorithm' in $metadata_file"; return 1 ;;
    esac
    if [[ -n "$saved_bias_min_mv" || -n "$saved_bias_max_mv" ]]; then
        if [[ -n "$bias_safe_min_mv" || -n "$bias_safe_max_mv" ]]; then
            fail "--resume loads the bias window from metadata"
            return 1
        fi
        bias_safe_min_mv="$saved_bias_min_mv"
        bias_safe_max_mv="$saved_bias_max_mv"
    fi
    IFS=',' read -r -a channel_list <<< "$channel_csv"
    IFS=',' read -r -a bias_array <<< "$bias_csv"
    IFS=',' read -r -a vgain_array <<< "$vgain_csv"
    metadata_afe="$saved_afe"
}

point_data_files_have_expected_size() {
    local folder="$1" expected_size actual_size data_channel
    [[ -f "$folder/config.txt" ]] || return 1
    expected_size=$((N * L * 2))
    for data_channel in "${channel_list[@]}"; do
        [[ -f "$folder/channel_${data_channel}.dat" ]] || return 1
        actual_size=$(stat -c '%s' "$folder/channel_${data_channel}.dat" 2>/dev/null) || return 1
        [[ "$actual_size" == "$expected_size" ]] || return 1
    done
    local -a point_files=()
    point_checksum_files "$folder" point_files || return 1
    return 0
}

point_data_is_complete() {
    local folder="$1"
    point_data_files_have_expected_size "$folder" || return 1
    if [[ "$checksums_required" == true ]]; then
        verify_point_checksum_manifest "$folder" || return 1
    elif [[ -f "$folder/SHA256SUMS" ]]; then
        verify_point_checksum_manifest "$folder" || return 1
    fi
    return 0
}

prepare_resume() {
    local point_index=0 seen_gap=false folder resume_bias resume_vgain
    local last_existing=-1 all_complete=true

    resume_delete_folder=""
    for resume_bias in "${bias_array[@]}"; do
        for resume_vgain in "${vgain_array[@]}"; do
            folder="${output_folder}/vbias_${resume_bias}/vgain_${resume_vgain}"
            if [[ -d "$folder" ]]; then
                if [[ "$seen_gap" == true ]]; then
                    fail "resume structure is not a contiguous scan: found data after a missing/incomplete point at $folder"
                    return 1
                fi
                last_existing=$point_index
                if ! point_data_is_complete "$folder"; then
                    seen_gap=true
                    all_complete=false
                fi
            else
                seen_gap=true
                all_complete=false
            fi
            ((point_index += 1))
        done
    done

    if [[ "$all_complete" == true ]]; then
        completed_points=$total_points
        resume_start_index=$total_points
        if [[ "$scan_status_text" == "complete" ]]; then
            scan_already_complete=true
        else
            restore_only_mode=true
        fi
        return 0
    fi

    if (( last_existing >= 0 )); then
        point_index=0
        for resume_bias in "${bias_array[@]}"; do
            for resume_vgain in "${vgain_array[@]}"; do
                if (( point_index == last_existing )); then
                    resume_delete_folder="${output_folder}/vbias_${resume_bias}/vgain_${resume_vgain}"
                    break 2
                fi
                ((point_index += 1))
            done
        done
        resume_start_index=$last_existing
    else
        resume_start_index=0
    fi
    completed_points=$resume_start_index
    return 0
}

confirm_scan_parameters() {
    echo
    echo "================ SCAN CONFIRMATION ================"
    echo "Mode:                 $([[ "$resume_mode" == true ]] && echo RESUME || echo NEW)"
    echo "Output folder:        $output_folder"
    echo "Channels:             ${channel_list[*]}"
    echo "AFE:                  $afe"
    echo "Bias values ($units): ${bias_array[*]}"
    echo "Bias control:         $bias_control $units"
    if [[ "$allow_unmonitored_bias" == true ]]; then
        echo "Bias verification:    nominal voltage and DAC readback (monitor bypassed)"
    fi
    echo "TRIM (channel:DAC):   ${trim_map[*]}"
    if [[ -n "$bias_safe_min_mv" ]]; then
        echo "Safe bias window:     $bias_safe_min_mv..$bias_safe_max_mv mV effective"
    fi
    echo "VGAIN values (DAC):   ${vgain_array[*]}"
    echo "Pedestal:             $pedestal ADC (regula_falsi, auto)"
    if [[ -n "$plateau_margin" ]]; then
        echo "Plateau margin:       $plateau_margin ADC"
    fi
    echo "Waveforms / length:   $N / $L"
    echo "Connection:           $ip_addr:$port, route=$route, timeout=${timeout_ms}ms"
    echo "Trigger source:       $trigger_source"
    echo "Backend:              $backend"
    if [[ "$backend" == dma ]]; then
        echo "DMA data:             $capture_mode, P=$pretrigger, force_acq=$force_acq"
        echo "DMA deadlines (ms):   trigger=$trigger_timeout_ms, total=$job_timeout_ms, pressure=$pressure_timeout_ms"
        echo "Pedestal acquisition: persistent, software, P=0, force_acq=$force_acq"
    fi
    echo "Integrity check:      SHA-256 per point and for the complete scan"
    echo "Points:               $total_points total, $completed_points retained, $((total_points - completed_points)) to acquire"
    if [[ "$restore_only_mode" == true ]]; then
        echo "Resume action:        data complete; restore default hardware only"
    fi
    if [[ -n "$resume_delete_folder" ]]; then
        echo "Point to replace:     $resume_delete_folder"
    fi
    echo "Final restoration:    bias=0, TRIM=0, VGAIN=1700, pedestal=8192"
    echo "Bias control:         remains $bias_control $units"
    echo "==================================================="

    if [[ "$assume_yes" == true ]]; then
        echo "Confirmation accepted by --yes."
        return 0
    fi
    if [[ ! -t 0 ]]; then
        fail "interactive confirmation requires a terminal; use --yes for unattended execution"
        return 1
    fi
    local answer
    read -r -p "Continue with this scan? [y/N] " answer
    case "$answer" in
        y|Y|yes|YES) return 0 ;;
        *) echo "Scan cancelled; no hardware was configured."; return 1 ;;
    esac
}

restore_default_configuration() {
    local reason="$1"
    local restore_log="${output_folder}/default_restore.log"
    local restore_readback
    local restore_failed=false
    local -a restore_vgain_args restore_pedestal_args restore_read_args

    echo "Restoring defaults after $reason: bias=0, TRIM=0, VGAIN=1700, pedestal=8192; preserving bias_control=$bias_control."
    : > "$restore_log"
    if ! run_logged "$restore_log" "clear AFE TRIM before restoring bias to zero" \
        "$python_bin" "$client_dir/protobuf_vgain_bias.py" shutdown "${bias_sequence_args[@]}"; then
        return 1
    fi

    restore_vgain_args=("${common_connection_args[@]}" -afe "$afe" -vgain_value 1700)
    if ! run_logged "$restore_log" "restore VGAIN to 1700" \
        "$python_bin" "$client_dir/protobuf_configure_vgain.py" "${restore_vgain_args[@]}"; then
        restore_failed=true
    fi

    restore_pedestal_args=("${common_connection_args[@]}" "${pedestal_backend_args[@]}" -channel "${channel_list[@]}" --use-current-offset -target_pedestal 8192 -method regula_falsi --auto -L "$L")
    if ! run_logged "$restore_log" "restore pedestal to 8192" \
        "$python_bin" "$client_dir/protobuf_configure_pedestal_level.py" "${restore_pedestal_args[@]}"; then
        restore_failed=true
    fi

    restore_read_args=("${common_connection_args[@]}" -channel "${channel_list[@]}" -afe "$afe" --offset --trim --bias --vgain --bias-control --compact)
    if restore_readback=$("$python_bin" "$client_dir/protobuf_read_configuration.py" "${restore_read_args[@]}" 2>&1); then
        {
            echo
            echo "===== default configuration readback ====="
            echo "$restore_readback"
        } >> "$restore_log"
    else
        {
            echo
            echo "===== default configuration readback failed ====="
            echo "$restore_readback"
        } >> "$restore_log"
        restore_failed=true
    fi

    if [[ "$restore_failed" == true ]]; then
        echo "ERROR: default restoration could not be fully verified; see $restore_log" >&2
        return 1
    fi
    echo "Default restoration verified. Details: $restore_log"
    return 0
}

handle_scan_signal() {
    local signal_name="$1" signal_status="$2"
    local normalized_signal="${signal_name,,}"

    # Prevent a second signal from recursively starting another restoration.
    trap - INT TERM HUP
    echo >&2
    echo "EMERGENCY STOP: received $signal_name; aborting the scan and restoring defaults." >&2
    if [[ -n "${active_child_pid:-}" ]]; then
        kill -TERM "$active_child_pid" 2>/dev/null || true
        wait "$active_child_pid" 2>/dev/null || true
        active_child_pid=""
    fi
    scan_status_text="interrupted_${normalized_signal}"
    write_scan_metadata || true
    if restore_default_configuration "signal $signal_name"; then
        scan_status_text="interrupted_${normalized_signal}_restored"
    else
        scan_status_text="interrupted_${normalized_signal}_restore_failed"
    fi
    write_scan_metadata || true
    exit "$signal_status"
}

scan_main() {
    local output_folder="" vgain_list="" vgain_range="" fixed_vgain=""
    local bias_list="" bias_range="" fixed_bias=""
    local trim="0" bias_control="0" ip_addr="" port="" N="" L=""
    local bias_safe_min_mv="" bias_safe_max_mv=""
    local allow_unmonitored_bias=false
    local trigger_source_arg="" route="mezz/0" timeout_ms="30000"
    local backend=spybuffer capture_mode=persistent force_acq=false pretrigger=0
    local trigger_timeout_ms=10000 job_timeout_ms=0 pressure_timeout_ms=0 dma_option_seen=false
    local pedestal="8192" plateau_margin="" set_as_dac=false legacy_software_trigger=false
    local resume_mode=false assume_yes=false config_option_seen=false
    local metadata_file="" metadata_afe="" scan_created_utc=""
    local scan_status_text="in_progress" scan_already_complete=false restore_only_mode=false
    local checksums_required=true
    local resume_delete_folder="" resume_start_index=0 completed_points=0 total_points=0
    local vgain_mode="" bias_mode="" units="" trigger_source="" afe=-1
    local active_child_pid=""
    local python_bin="${DAPHNE_PYTHON:-python3}"
    local script_dir client_dir
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    client_dir="${script_dir}/../client"
    local -a channel_list=() vgain_array=() bias_array=() trim_map=() trim_values=()
    local -a pedestal_backend_args=() acquisition_backend_args=()

    source "$script_dir/../utils/identity_cli.sh" || return 1
    parse_daphne_identity "$@" || return $?
    set -- "${DAPHNE_CLIENT_ARGS[@]}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -output_folder|--output-folder|-folder|--folder)
                require_value "$@" || return 1; output_folder="$2"; shift 2 ;;
            -vgain_list|--vgain-list)
                require_value "$@" || return 1; vgain_list="$2"; config_option_seen=true; shift 2 ;;
            -vgain_range|--vgain-range|-range)
                require_value "$@" || return 1; vgain_range="$2"; config_option_seen=true; shift 2 ;;
            -vgain|--vgain)
                require_value "$@" || return 1; fixed_vgain="$2"; config_option_seen=true; shift 2 ;;
            -bias_list|--bias-list|-vbias_list|--vbias-list)
                require_value "$@" || return 1; bias_list="$2"; config_option_seen=true; shift 2 ;;
            -bias_range|--bias-range|-vbias_range|--vbias-range)
                require_value "$@" || return 1; bias_range="$2"; config_option_seen=true; shift 2 ;;
            -bias|--bias|-vbias|--vbias)
                require_value "$@" || return 1; fixed_bias="$2"; config_option_seen=true; shift 2 ;;
            -channel|--channel|--channels)
                config_option_seen=true
                shift
                local -a channel_tokens=() parsed_channels=()
                while [[ $# -gt 0 && "$1" != -* ]]; do
                    channel_tokens+=("$1")
                    shift
                done
                parse_dac_list "${channel_tokens[*]}" parsed_channels || return 1
                channel_list+=("${parsed_channels[@]}")
                ;;
            -trim|--trim)
                require_value "$@" || return 1; trim="$2"; config_option_seen=true; shift 2 ;;
            --allow-unmonitored-bias)
                allow_unmonitored_bias=true; shift ;;
            --bias-safe-window-mv)
                if (( $# < 3 )); then
                    fail "$1 requires MIN and MAX in millivolts"; return 1
                fi
                bias_safe_min_mv="$2"; bias_safe_max_mv="$3"; shift 3 ;;
            -bias_control|--bias-control)
                require_value "$@" || return 1; bias_control="$2"; config_option_seen=true; shift 2 ;;
            -set_as_DAC|--set-as-dac)
                set_as_dac=true; config_option_seen=true; shift ;;
            -pedestal|--pedestal|-target_pedestal|--target-pedestal)
                require_value "$@" || return 1; pedestal="$2"; config_option_seen=true; shift 2 ;;
            --plateau-margin)
                require_value "$@" || return 1; plateau_margin="$2"; config_option_seen=true; shift 2 ;;
            -ip|--ip)
                require_value "$@" || return 1; ip_addr="$2"; config_option_seen=true; shift 2 ;;
            -port|--port)
                require_value "$@" || return 1; port="$2"; config_option_seen=true; shift 2 ;;
            -N)
                require_value "$@" || return 1; N="$2"; config_option_seen=true; shift 2 ;;
            -L)
                require_value "$@" || return 1; L="$2"; config_option_seen=true; shift 2 ;;
            -trigger_source|--trigger-source)
                require_value "$@" || return 1; trigger_source_arg="$2"; config_option_seen=true; shift 2 ;;
            -software_trigger|--software-trigger)
                legacy_software_trigger=true; config_option_seen=true; shift ;;
            -route|--route|-r)
                require_value "$@" || return 1; route="$2"; config_option_seen=true; shift 2 ;;
            --timeout-ms|--timeout_ms)
                require_value "$@" || return 1; timeout_ms="$2"; config_option_seen=true; shift 2 ;;
            --dma)
                backend=dma; config_option_seen=true; shift ;;
            --force-acq|--force_acq)
                force_acq=true; dma_option_seen=true; config_option_seen=true; shift ;;
            --capture-mode)
                require_value "$@" || return 1; capture_mode="$2"; dma_option_seen=true; config_option_seen=true; shift 2 ;;
            --pretrigger)
                require_value "$@" || return 1; pretrigger="$2"; dma_option_seen=true; config_option_seen=true; shift 2 ;;
            --trigger-timeout-ms)
                require_value "$@" || return 1; trigger_timeout_ms="$2"; dma_option_seen=true; config_option_seen=true; shift 2 ;;
            --job-timeout-ms)
                require_value "$@" || return 1; job_timeout_ms="$2"; dma_option_seen=true; config_option_seen=true; shift 2 ;;
            --pressure-timeout-ms)
                require_value "$@" || return 1; pressure_timeout_ms="$2"; dma_option_seen=true; config_option_seen=true; shift 2 ;;
            -multi_channel|--multi-channel)
                echo "WARNING: -multi_channel is no longer needed; selected channels are handled automatically." >&2
                config_option_seen=true; shift ;;
            --resume)
                resume_mode=true; shift ;;
            -y|--yes)
                assume_yes=true; shift ;;
            -h|--help)
                print_help; return 0 ;;
            *)
                fail "unknown option: $1"
                print_help
                return 1 ;;
        esac
    done

    if [[ -z "$output_folder" ]]; then
        fail "an output folder is required (-folder or -output_folder)"
        return 1
    fi
    metadata_file="${output_folder}/scan_metadata.txt"
    if [[ "$resume_mode" == true ]]; then
        if [[ "$config_option_seen" == true ]]; then
            fail "--resume loads scan parameters from metadata; use -folder DIR --resume [--yes]"
            return 1
        fi
        load_scan_metadata || return 1
    fi

    if [[ -z "$output_folder" || -z "$ip_addr" || -z "$port" || -z "$N" || -z "$L" || ${#channel_list[@]} -eq 0 ]]; then
        fail "missing required arguments: output folder, channel(s), IP, port, N and L are required"
        print_help
        return 1
    fi
    if ! command -v sha256sum >/dev/null 2>&1; then
        fail "sha256sum is required for scan file integrity verification"
        return 1
    fi
    validate_positive_integer "$port" "port" || return 1
    validate_positive_integer "$N" "N" || return 1
    validate_positive_integer "$L" "L" || return 1
    validate_positive_integer "$timeout_ms" "timeout" || return 1
    if [[ ! "$pedestal" =~ ^[0-9]+$ ]] || (( pedestal < 0 || pedestal > 16383 )); then
        fail "pedestal must be an integer ADC code in 0..16383 (got '$pedestal')"
        return 1
    fi
    local margin_magnitude="${plateau_margin#[+-]}"
    if [[ -n "$plateau_margin" ]] &&
        { [[ ! "$margin_magnitude" =~ ^[0-9]{1,5}$ ]] || (( 10#$margin_magnitude > 16383 )); }; then
        fail "plateau margin must be an integer in -16383..16383 (got '$plateau_margin')"
        return 1
    fi

    local channel channel_afe index trim_value
    local -A seen_channels=()
    afe=-1
    for index in "${!channel_list[@]}"; do
        channel="${channel_list[index]}"
        if [[ ! "$channel" =~ ^0*[0-9]{1,2}$ ]] || (( 10#$channel > 39 )); then
            fail "channel must be an integer in 0..39 (got '$channel')"
            return 1
        fi
        channel=$((10#$channel))
        channel_list[index]="$channel"
        if [[ -n "${seen_channels[$channel]:-}" ]]; then
            fail "channel $channel was specified more than once"
            return 1
        fi
        seen_channels[$channel]=1
        channel_afe=$((channel / 8))
        if (( afe < 0 )); then
            afe=$channel_afe
        elif (( channel_afe != afe )); then
            fail "all channels must belong to one AFE because bias and VGAIN are AFE-wide; channel ${channel_list[0]} is in AFE $afe but channel $channel is in AFE $channel_afe"
            return 1
        fi
    done
    if [[ "$trim" =~ ^[0-9]+$ ]]; then
        validate_dac "$trim" "trim" || return 1
        for channel in "${channel_list[@]}"; do
            trim_values+=("$trim")
        done
    else
        parse_dac_list "$trim" trim_values || return 1
        if (( ${#trim_values[@]} != ${#channel_list[@]} )); then
            fail "TRIM list must have exactly one value per selected channel"
            return 1
        fi
    fi
    local has_nonzero_trim=false
    for index in "${!trim_values[@]}"; do
        trim_value="${trim_values[index]}"
        validate_dac "$trim_value" "trim" || return 1
        trim_value=$((10#$trim_value))
        trim_values[index]="$trim_value"
        trim_map+=("${channel_list[index]}:$trim_value")
        if (( trim_value > 0 )); then
            has_nonzero_trim=true
        fi
    done
    if [[ ! "$trim" =~ ^[0-9]+$ ]]; then
        trim=$(join_by_comma "${trim_values[@]}")
    fi
    if [[ -n "$bias_safe_min_mv" || -n "$bias_safe_max_mv" ]]; then
        if [[ ! "$bias_safe_min_mv" =~ ^[0-9]{1,9}$ || ! "$bias_safe_max_mv" =~ ^[0-9]{1,9}$ ]] ||
            (( 10#$bias_safe_min_mv >= 10#$bias_safe_max_mv )); then
            fail "--bias-safe-window-mv requires integers with 0 <= MIN < MAX"
            return 1
        fi
    fi
    if [[ "$resume_mode" == true && "$metadata_afe" != "$afe" ]]; then
        fail "metadata AFE $metadata_afe does not match channels ${channel_list[*]} (AFE $afe)"
        return 1
    fi

    if [[ "$legacy_software_trigger" == true ]]; then
        if [[ -n "$trigger_source_arg" && "$trigger_source_arg" != "software" ]]; then
            fail "-software_trigger conflicts with -trigger_source $trigger_source_arg"
            return 1
        fi
        echo "WARNING: -software_trigger is deprecated; use -trigger_source software" >&2
        trigger_source_arg="software"
    fi
    trigger_source="${trigger_source_arg:-external}"
    case "$trigger_source" in
        software|external|timing|all) ;;
        *) fail "invalid trigger source '$trigger_source' (expected software, external, timing, or all)"; return 1 ;;
    esac

    case "$backend" in
        dma|spybuffer) ;;
        *) fail "invalid backend in scan metadata: $backend"; return 1 ;;
    esac
    if [[ "$force_acq" != true && "$force_acq" != false ]]; then
        fail "invalid force_acq in scan metadata: $force_acq"; return 1
    fi
    case "$capture_mode" in
        finite|triggered|persistent) ;;
        *) fail "invalid DMA capture mode: $capture_mode"; return 1 ;;
    esac
    local numeric_value
    for numeric_value in "$pretrigger" "$trigger_timeout_ms" "$job_timeout_ms" "$pressure_timeout_ms"; do
        if [[ ! "$numeric_value" =~ ^[0-9]+$ || ${#numeric_value} -gt 12 ]]; then
            fail "DMA pretrigger/deadlines must be nonnegative integers of at most 12 digits"; return 1
        fi
    done
    # Normalize decimal values so Bash never interprets leading zeros as octal.
    pretrigger=$((10#$pretrigger))
    trigger_timeout_ms=$((10#$trigger_timeout_ms))
    job_timeout_ms=$((10#$job_timeout_ms))
    pressure_timeout_ms=$((10#$pressure_timeout_ms))
    if [[ "$backend" == spybuffer ]]; then
        if [[ "$dma_option_seen" == true || "$force_acq" == true || "$capture_mode" != persistent ]] ||
                (( pretrigger || trigger_timeout_ms != 10000 || job_timeout_ms || pressure_timeout_ms )); then
            fail "DMA capture options require --dma"; return 1
        fi
    else
        if [[ "$trigger_source" == all ]]; then
            fail "DMA supports software, external and timing; trigger source all is unavailable"; return 1
        fi
        if (( pretrigger >= L || trigger_timeout_ms < 10 || trigger_timeout_ms > 600000 ||
                (job_timeout_ms > 0 && job_timeout_ms < 10) )); then
            fail "DMA requires 0 <= P < L, trigger timeout 10..600000 ms and total deadline 0 or >=10 ms"; return 1
        fi
        if [[ "$capture_mode" == finite && ( "$trigger_source" != software || "$pretrigger" != 0 ) ]]; then
            fail "Finite DMA requires software trigger and P=0"; return 1
        fi
        if (( pressure_timeout_ms )) && { [[ "$capture_mode" != persistent ]] ||
                (( pressure_timeout_ms < 10 || pressure_timeout_ms > 600000 )); }; then
            fail "Pressure timeout requires persistent DMA and 10..600000 ms"; return 1
        fi
        if [[ "$capture_mode" == persistent ]] && (( job_timeout_ms > 604800000 )); then
            fail "Persistent DMA total deadline cannot exceed 7 days"; return 1
        fi
        pedestal_backend_args=(--dma)
        acquisition_backend_args=(--dma --capture-mode "$capture_mode" --pretrigger "$pretrigger"
            --trigger-timeout-ms "$trigger_timeout_ms" --job-timeout-ms "$job_timeout_ms"
            --pressure-timeout-ms "$pressure_timeout_ms")
        if [[ "$force_acq" == true ]]; then
            pedestal_backend_args+=(--force-acq)
            acquisition_backend_args+=(--force-acq)
        fi
    fi

    if [[ "$resume_mode" != true ]]; then
        local vgain_selectors=0 bias_selectors=0
        [[ -n "$vgain_list" ]] && ((++vgain_selectors))
        [[ -n "$vgain_range" ]] && ((++vgain_selectors))
        [[ -n "$fixed_vgain" ]] && ((++vgain_selectors))
        [[ -n "$bias_list" ]] && ((++bias_selectors))
        [[ -n "$bias_range" ]] && ((++bias_selectors))
        [[ -n "$fixed_bias" ]] && ((++bias_selectors))
        if (( vgain_selectors > 1 )); then
            fail "choose only one of -vgain_list, -vgain_range/-range, or -vgain"
            return 1
        fi
        if (( bias_selectors > 1 )); then
            fail "choose only one of -bias_list, -bias_range, or -bias"
            return 1
        fi
        if [[ -z "$vgain_list" && -z "$vgain_range" && -z "$bias_list" && -z "$bias_range" ]]; then
            fail "at least one scan is required: use a VGAIN or bias list/range"
            return 1
        fi

        if [[ -n "$vgain_list" ]]; then
            parse_list "$vgain_list" vgain_array || return 1
            vgain_mode="scan-list"
        elif [[ -n "$vgain_range" ]]; then
            build_integer_range "$vgain_range" vgain_array || return 1
            vgain_mode="scan-range"
        else
            vgain_array=("${fixed_vgain:-1800}")
            vgain_mode="fixed"
        fi
        if [[ -n "$bias_list" ]]; then
            parse_list "$bias_list" bias_array || return 1
            bias_mode="scan-list"
        elif [[ -n "$bias_range" ]]; then
            build_decimal_range "$bias_range" bias_array || return 1
            bias_mode="scan-range"
        else
            if [[ "$set_as_dac" == true ]]; then
                bias_array=("${fixed_bias:-0}")
            else
                bias_array=("${fixed_bias:-0.0}")
            fi
            bias_mode="fixed"
        fi
    fi

    local vgain bias
    for vgain in "${vgain_array[@]}"; do
        validate_dac "$vgain" "VGAIN" || return 1
    done
    if [[ "$set_as_dac" == true ]]; then
        validate_dac "$bias_control" "bias control" || return 1
        for bias in "${bias_array[@]}"; do
            validate_dac "$bias" "bias" || return 1
        done
    else
        local number_regex='^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$'
        if [[ ! "$bias_control" =~ $number_regex ]]; then
            fail "bias control must be numeric (got '$bias_control')"
            return 1
        fi
        for bias in "${bias_array[@]}"; do
            if [[ ! "$bias" =~ $number_regex ]]; then
                fail "bias must be numeric (got '$bias')"
                return 1
            fi
        done
    fi

    units="volts"
    [[ "$set_as_dac" == true ]] && units="DAC"
    total_points=$((${#bias_array[@]} * ${#vgain_array[@]}))

    if [[ "$resume_mode" == true ]]; then
        prepare_resume || return 1
        if [[ "$scan_already_complete" == true ]]; then
            if [[ "$checksums_required" != true ]]; then
                echo "Completed legacy scan has no SHA-256 manifest; creating and verifying it now..."
                if ! write_scan_checksum_manifest; then
                    fail "could not create or verify SHA-256 checksums for the completed legacy scan"
                    return 1
                fi
                checksums_required=true
                write_scan_metadata || {
                    fail "checksums succeeded, but scan metadata could not be updated: $metadata_file"
                    return 1
                }
            elif ! verify_scan_checksum_manifest; then
                fail "scan metadata says complete, but $output_folder/SHA256SUMS is missing or its verification failed"
                return 1
            fi
            echo "Scan already complete: all $total_points points and their SHA-256 checksums were verified successfully."
            return 0
        fi
    else
        if [[ -e "$metadata_file" ]]; then
            fail "scan metadata already exists at $metadata_file; use --resume or choose a new folder"
            return 1
        fi
        if [[ -d "$output_folder" ]] && compgen -G "${output_folder}/vbias_*" >/dev/null; then
            fail "output folder already contains vbias_* data but has no resumable metadata: $output_folder"
            return 1
        fi
        scan_created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        completed_points=0
        resume_start_index=0
    fi

    if [[ "$has_nonzero_trim" == true && -z "$bias_safe_min_mv" ]]; then
        fail "nonzero TRIM requires --bias-safe-window-mv MIN MAX"
        return 1
    fi
    confirm_scan_parameters || return 1

    local -a common_connection_args bias_sequence_args bias_apply_args
    common_connection_args=(-ip "$ip_addr" -port "$port" -route "$route" --timeout-ms "$timeout_ms")
    bias_sequence_args=("${common_connection_args[@]}" --afe "$afe" --state-file "${output_folder}/.bias_trim_state.json")
    if [[ -n "$bias_safe_min_mv" ]]; then
        bias_sequence_args+=(--bias-safe-window-mv "$bias_safe_min_mv" "$bias_safe_max_mv")
    fi
    [[ "$allow_unmonitored_bias" == true ]] && bias_sequence_args+=(--allow-unmonitored-bias)
    bias_apply_args=("${bias_sequence_args[@]}" --bias-control "$bias_control" --trim-map "${trim_map[@]}")
    [[ "$set_as_dac" == true ]] && bias_apply_args+=(--set-as-dac)
    if [[ "$restore_only_mode" != true ]]; then
        "$python_bin" "$client_dir/protobuf_vgain_bias.py" validate "${bias_apply_args[@]}" --bias "${bias_array[@]}" || return 1
    fi
    mkdir -p "$output_folder" || { fail "could not create output folder '$output_folder'"; return 1; }
    if [[ "$resume_mode" == true && -n "$resume_delete_folder" ]]; then
        case "$resume_delete_folder" in
            "$output_folder"/vbias_*/vgain_*)
                echo "Removing last potentially corrupt scan point: $resume_delete_folder"
                rm -rf -- "$resume_delete_folder" || {
                    fail "could not remove the last scan point: $resume_delete_folder"
                    return 1
                }
                ;;
            *)
                fail "refusing to remove unsafe resume path: $resume_delete_folder"
                return 1
                ;;
        esac
    fi
    if [[ "$restore_only_mode" == true ]]; then
        scan_status_text="restoring_defaults"
    else
        scan_status_text="in_progress"
    fi
    write_scan_metadata || {
        fail "could not write scan metadata: $metadata_file"
        return 1
    }

    local bias_folder bias_log bias_readback
    local -a read_bias_args vgain_args pedestal_args read_all_args
    trap 'handle_scan_signal INT 130' INT
    trap 'handle_scan_signal TERM 143' TERM
    trap 'handle_scan_signal HUP 129' HUP

    _run_scan_points() {
    local point_index=0
    local points_per_bias=${#vgain_array[@]}
    for bias in "${bias_array[@]}"; do
        if (( point_index + points_per_bias <= resume_start_index )); then
            ((point_index += points_per_bias))
            continue
        fi
        bias_folder="${output_folder}/vbias_${bias}"
        mkdir -p "$bias_folder" || { fail "could not create '$bias_folder'"; return 1; }
        bias_log="${bias_folder}/vbias_config.txt"
        : > "$bias_log"
        echo "Configuring AFE $afe bias=$bias $units and TRIM (channel:DAC) ${trim_map[*]}"
        run_logged "$bias_log" "configure AFE bias and channel TRIM" \
            "$python_bin" "$client_dir/protobuf_vgain_bias.py" apply "${bias_apply_args[@]}" --bias "$bias" || return 1

        read_bias_args=("${common_connection_args[@]}" -channel "${channel_list[@]}" -afe "$afe" --trim --bias --bias-control --compact)
        if ! bias_readback=$("$python_bin" "$client_dir/protobuf_read_configuration.py" "${read_bias_args[@]}" 2>&1); then
            {
                echo
                echo "===== verify bias/trim ====="
                echo "$bias_readback"
            } >> "$bias_log"
            fail "bias/TRIM verification failed for bias $bias; see $bias_log"
            return 1
        fi
        {
            echo
            echo "===== verified bias/trim readback ====="
            echo "$bias_readback"
        } >> "$bias_log"

        for vgain in "${vgain_array[@]}"; do
            local point_folder config_file final_readback
            if (( point_index < resume_start_index )); then
                ((point_index += 1))
                continue
            fi
            point_folder="${bias_folder}/vgain_${vgain}"
            mkdir -p "$point_folder" || { fail "could not create '$point_folder'"; return 1; }
            config_file="${point_folder}/config.txt"
            {
                echo "scan_configuration"
                echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
                echo "channels=${channel_list[*]}"
                echo "afe=$afe"
                echo "number_of_waveforms=$N"
                echo "waveform_length=$L"
                echo "bias_requested=$bias"
                echo "bias_units=$units"
                echo "bias_control_requested=$bias_control"
                echo "trim_requested=$trim"
                echo "trim_by_channel=${trim_map[*]}"
                echo "allow_unmonitored_bias=$allow_unmonitored_bias"
                echo "trim_units=DAC"
                echo "vgain_requested=$vgain"
                echo "vgain_units=DAC"
                echo "pedestal_target=$pedestal"
                if [[ -n "$plateau_margin" ]]; then
                    echo "pedestal_plateau_margin=$plateau_margin"
                fi
                echo "pedestal_method=regula_falsi"
                echo "pedestal_mode=auto"
                echo "pedestal_initial_offset=current"
                echo "trigger_source=$trigger_source"
                echo "backend=$backend"
                if [[ "$backend" == dma ]]; then
                    echo "capture_mode=$capture_mode"
                    echo "pretrigger=$pretrigger"
                    echo "force_acq=$force_acq"
                    echo "trigger_timeout_ms=$trigger_timeout_ms"
                    echo "job_timeout_ms=$job_timeout_ms"
                    echo "pressure_timeout_ms=$pressure_timeout_ms"
                    echo "pedestal_capture_mode=persistent"
                    echo "pedestal_trigger_source=software"
                    echo "pedestal_pretrigger=0"
                fi
                echo "route=$route"
                echo "bias_mode=$bias_mode"
                echo "vgain_mode=$vgain_mode"
                echo
                echo "===== verified bias/trim readback ====="
                echo "$bias_readback"
            } > "$config_file"

            echo "Configuring point bias=$bias $units, VGAIN=$vgain DAC"
            vgain_args=("${common_connection_args[@]}" -afe "$afe" -vgain_value "$vgain")
            run_logged "$config_file" "configure VGAIN" \
                "$python_bin" "$client_dir/protobuf_configure_vgain.py" "${vgain_args[@]}" || return 1

            pedestal_args=("${common_connection_args[@]}" "${pedestal_backend_args[@]}" -channel "${channel_list[@]}" --use-current-offset -target_pedestal "$pedestal" -method regula_falsi --auto -L "$L")
            if [[ -n "$plateau_margin" ]]; then
                pedestal_args+=(--plateau-margin "$plateau_margin")
            fi
            run_logged "$config_file" "configure pedestal OFFSETs" \
                "$python_bin" "$client_dir/protobuf_configure_pedestal_level.py" "${pedestal_args[@]}" || return 1

            read_all_args=("${common_connection_args[@]}" -channel "${channel_list[@]}" -afe "$afe" --offset --trim --bias --vgain --bias-control --compact)
            if ! final_readback=$("$python_bin" "$client_dir/protobuf_read_configuration.py" "${read_all_args[@]}" 2>&1); then
                {
                    echo
                    echo "===== final configuration verification ====="
                    echo "$final_readback"
                } >> "$config_file"
                fail "final configuration verification failed for bias $bias, VGAIN $vgain; see $config_file"
                return 1
            fi
            {
                echo
                echo "===== verified final hardware configuration ====="
                echo "$final_readback"
            } >> "$config_file"

            if ! run_external_command "$python_bin" "$client_dir/protobuf_acquire_list_channels.py" \
                "${acquisition_backend_args[@]}" \
                -ip "$ip_addr" \
                -port "$port" \
                -route "$route" \
                --timeout_ms "$timeout_ms" \
                -foldername "$point_folder" \
                -channel_list "${channel_list[@]}" \
                -L "$L" \
                -N "$N" \
                -chunk 10 \
                -debug \
                -compression_format 7z \
                -trigger_source "$trigger_source"; then
                fail "acquisition failed for bias $bias, VGAIN $vgain"
                return 1
            fi
            if ! point_data_files_have_expected_size "$point_folder"; then
                fail "acquisition for bias $bias, VGAIN $vgain did not produce config.txt and exactly $((N * L * 2)) bytes for every selected channel"
                return 1
            fi
            if ! write_point_checksum_manifest "$point_folder"; then
                fail "could not create SHA-256 checksums for bias $bias, VGAIN $vgain"
                return 1
            fi
            if ! verify_point_checksum_manifest "$point_folder"; then
                fail "SHA-256 verification failed for bias $bias, VGAIN $vgain"
                return 1
            fi
            printf 'complete_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${point_folder}/.scan_point_complete"
            completed_points=$((point_index + 1))
            scan_status_text="in_progress"
            write_scan_metadata || {
                fail "could not update scan metadata after bias $bias, VGAIN $vgain"
                return 1
            }
            ((point_index += 1))
        done
    done

    completed_points=$total_points
    scan_status_text="acquisition_complete"
    write_scan_metadata || {
        fail "could not mark scan acquisition complete: $metadata_file"
        return 1
    }
    }

    if [[ "$restore_only_mode" != true ]] && ! _run_scan_points; then
        scan_status_text="failed"
        write_scan_metadata || true
        if restore_default_configuration "scan failure"; then
            scan_status_text="failed_restored"
        else
            scan_status_text="failed_restore_failed"
        fi
        write_scan_metadata || true
        return 1
    fi

    scan_status_text="restoring_defaults"
    write_scan_metadata || true
    if ! restore_default_configuration "$([[ "$restore_only_mode" == true ]] && echo 'interrupted completed scan' || echo 'successful scan')"; then
        scan_status_text="complete_restore_failed"
        write_scan_metadata || true
        return 1
    fi
    scan_status_text="verifying_checksums"
    write_scan_metadata || {
        fail "default restoration succeeded, but checksum verification state could not be recorded: $metadata_file"
        return 1
    }
    echo "Creating and verifying SHA-256 manifest for the complete scan..."
    if ! write_scan_checksum_manifest; then
        scan_status_text="checksum_failed_restored"
        write_scan_metadata || true
        fail "scan acquisition and default restoration succeeded, but SHA-256 verification failed"
        return 1
    fi
    checksums_required=true
    scan_status_text="complete"
    write_scan_metadata || {
        fail "data and default restoration succeeded, but final metadata could not be written: $metadata_file"
        return 1
    }
    echo "Bias/VGAIN scan completed, SHA-256 checksums verified, and default hardware configuration restored. All output files are stored in: $output_folder"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    scan_main "$@"
    exit $?
fi

# A sourced script runs the scan in a subshell so emergency-handler `exit`
# terminates only the scan, never the user's interactive shell.
(scan_main "$@")
scan_status=$?
return "$scan_status"
