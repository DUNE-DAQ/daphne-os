#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash generate_protos.sh [--python EXECUTABLE] [--output-dir DIRECTORY]

Generate Python bindings from the DAPHNE client schemas using grpcio-tools.
Defaults: python3 from PATH; ../srcs/protobuf relative to this script.
Relative output directories are resolved from the current working directory.
EOF
}

python=python3
output_dir=
while (( $# > 0 )); do
    case "$1" in
        --python|--output-dir)
            if (( $# < 2 )) || [[ -z "$2" ]]; then
                printf 'Missing value for %s\n' "$1" >&2
                exit 1
            fi
            if [[ "$1" == --python ]]; then
                python=$2
            else
                output_dir=$2
            fi
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
proto_dir=$(cd -- "$script_dir/../srcs/protobuf" && pwd)
output_dir=${output_dir:-$proto_dir}
proto_files=(
    "$proto_dir/daphneV3_high_level_confs.proto"
    "$proto_dir/daphneV3_low_level_confs.proto"
)
for proto_file in "${proto_files[@]}"; do
    if [[ ! -f "$proto_file" ]]; then
        printf 'Proto schema not found: %s\n' "$proto_file" >&2
        exit 1
    fi
done

if ! "$python" -c 'import grpc_tools.protoc; import google.protobuf'; then
    printf 'Install client dependencies with the selected Python: python -m pip install -r client/requirements.txt\n' >&2
    exit 1
fi

mkdir -p -- "$output_dir"
"$python" -m grpc_tools.protoc \
    "--proto_path=$proto_dir" \
    "--python_out=$output_dir" \
    "${proto_files[@]}"
printf 'Python protobuf bindings generated in: %s\n' "$output_dir"
