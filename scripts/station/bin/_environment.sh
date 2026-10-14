R=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PATH="$R/.venv/bin:$PATH"
export PYTHONPATH="$R/kit/python${PYTHONPATH:+:$PYTHONPATH}"
eval "$(python3 "$R/bin/station_config.py")"
