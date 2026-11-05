# Python clients

Use Python 3.10 or newer. The requirements include the transport, protobuf
compiler/runtime, analysis tools, and the Qt oscilloscope dependencies.
Run the following commands from `daphne-server/`.

## Client identities

ZeroMQ clients accept `--identity NAME` and the alias `-identity NAME`, including
both acquisition backends. Existing defaults are preserved when the option is
omitted. Choose different identities for simultaneous clients of the same server.
An identity contains 1 to 255 UTF-8 bytes and cannot start with NUL.

```bash
python client/osc.py -ip 127.0.0.1 -port 40001 -L 1024 \
  --channels 0,1 --trigger-source timing --identity scope-alice
python client/protobuf_acquire_list_channels.py -ip 127.0.0.1 -port 40001 \
  -foldername output/run1 -channel_list 0,1 -L 1024 -N 100 \
  --trigger-source timing --identity acquire-bob
```

Bash scan runners accept the same flags. The PowerShell VGAIN runner accepts
`-Identity NAME`. Runners propagate the base through `DAPHNE_IDENTITY`; each
Python child appends its process ID. Python LED scans derive a unique identity
for each child invocation. This includes configuration, readback, acquisition
and restoration. An explicit client flag overrides the inherited value.
On resume, supply the desired identity again; it is a connection option and is
independent of the saved acquisition plan.

Tools with several connections derive role suffixes from the supplied name.
For example, `osc.py` uses `NAME-trigger-config` for setup and `NAME` for
acquisition. Leave room within the 255-byte limit for these suffixes.

Identities select the destination of replies. The hardware and trigger source
remain shared between clients; identities do not reserve an acquisition.

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

DMA clients check the generated descriptor before importing bindings. Copies
without the force acquisition and ramp verification fields are skipped, including
older paths selected by environment variables. If no compatible copy exists,
the client reports a local schema error before contacting the server. To select
the refreshed default bindings explicitly in an existing PowerShell session:

```powershell
$env:DAPHNE_PROTO_PYTHON_DIR = (Resolve-Path .\srcs\protobuf).Path
```

The PDS detail/seed configuration helpers additionally require the separate
PDS source checkout expected by `pds_configure_utils.py`; it is not a PyPI
dependency in this requirements file.
