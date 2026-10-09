<#
.SYNOPSIS
Generate Python protobuf bindings for the DAPHNE clients.
.EXAMPLE
.\generate_protos.ps1 -Python .\.venv\Scripts\python.exe
.EXAMPLE
.\generate_protos.ps1 -OutputDir .\build-client\srcs\protobuf
#>
[CmdletBinding()]
param(
    [string] $Python = 'python',
    [string] $OutputDir
)

$ErrorActionPreference = 'Stop'

try {
    $protoDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../srcs/protobuf'))
    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        $OutputDir = $protoDir
    }
    $OutputDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)
    $protoFiles = @(
        (Join-Path $protoDir 'daphneV3_high_level_confs.proto'),
        (Join-Path $protoDir 'daphneV3_low_level_confs.proto')
    )
    foreach ($protoFile in $protoFiles) {
        if (-not (Test-Path -LiteralPath $protoFile -PathType Leaf)) {
            throw "Proto schema not found: $protoFile"
        }
    }

    & $Python -c 'import grpc_tools.protoc; import google.protobuf'
    if ($LASTEXITCODE -ne 0) {
        throw 'Install client dependencies with the selected Python: python -m pip install -r client/requirements.txt'
    }

    [System.IO.Directory]::CreateDirectory($OutputDir) | Out-Null
    & $Python -m grpc_tools.protoc "--proto_path=$protoDir" "--python_out=$OutputDir" @protoFiles
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    Write-Host "Python protobuf bindings generated in: $OutputDir"
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
