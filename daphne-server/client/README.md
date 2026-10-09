# Python clients

Use Python 3.10 or newer. The requirements include the transport, protobuf
compiler/runtime, analysis tools, and the Qt oscilloscope dependencies.
Run the following commands from `daphne-server/`.

## Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r client/requirements.txt
.\client\generate_protos.ps1 -Python .\.venv\Scripts\python.exe
.\.venv\Scripts\python.exe client/synthetic_sipm.py --help
```

## Linux / macOS / Bash

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r client/requirements.txt
bash client/generate_protos.sh --python .venv/bin/python
.venv/bin/python client/synthetic_sipm.py --help
```

The generation scripts use `python -m grpc_tools.protoc`; a separate `protoc`
installation or C++ server build is unnecessary. The default output is
`srcs/protobuf/`, supporting both `from srcs.protobuf import ...` and
`protobuf_loader.py`. Generated files are ignored by Git. Regenerate after
schema changes, using the same Python environment that runs the clients.
Both scripts locate the schemas relative to their own location and can be
invoked from any working directory.

For clients using `protobuf_loader.py`, a custom output directory can be used:

```powershell
.\client\generate_protos.ps1 -Python .\.venv\Scripts\python.exe -OutputDir .\build-client\srcs\protobuf
$env:DAPHNE_PROTO_PYTHON_DIR = (Resolve-Path .\build-client\srcs\protobuf).Path
```

```bash
bash client/generate_protos.sh --python .venv/bin/python --output-dir build-client/srcs/protobuf
export DAPHNE_PROTO_PYTHON_DIR="$PWD/build-client/srcs/protobuf"
```

Clients that import directly from `srcs.protobuf` require the default output.
If existing server build bindings are found first by `protobuf_loader.py`, set
`DAPHNE_PROTO_PYTHON_DIR` to the desired output directory to select it explicitly.
Relative custom output paths are resolved from the working directory.

The PDS detail/seed configuration helpers additionally require the separate
PDS source checkout expected by `pds_configure_utils.py`; it is not a PyPI
dependency in this requirements file.
