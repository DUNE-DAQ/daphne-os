#!/usr/bin/env python3
"""Run the actual driver's portable codecs, ownership and range helpers.

Linux uses system UAPI headers. Windows uses minimal type/ioctl/errno shims
with MSVC; this checks portable C logic, not ARM/Linux ABI qualification.
"""
import argparse
import os
import re
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--linux-uapi', type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        if not args.linux_uapi:
            parser.error('Windows requires --linux-uapi pointing to include/uapi/asm-generic')
        headers = out / 'host-shim/linux'
        headers.mkdir(parents=True, exist_ok=True)
        (headers / 'types.h').write_text('#include <stdint.h>\n'
            'typedef uint32_t __u32; typedef int32_t __s32; typedef uint64_t __u64;\n'
            '#define __aligned_u64 __declspec(align(8)) __u64\n')
        (headers / 'ioctl.h').write_bytes((args.linux_uapi / 'ioctl.h').read_bytes())
        errno = (args.linux_uapi / 'errno-base.h').read_text() + (args.linux_uapi / 'errno.h').read_text()
        definitions = []
        for name in ('EINVAL', 'ENOMEM', 'E2BIG', 'ESTALE', 'EBUSY', 'ERANGE'):
            value = re.search(r'^#define\s+' + name + r'\s+(\d+)', errno, re.MULTILINE).group(1)
            definitions.append(f'#ifndef {name}\n#define {name} {value}\n#endif\n')
        (headers / 'errno.h').write_text(''.join(definitions))
        developer = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/Tools/VsDevCmd.bat')
        # Quote fixed paths through a batch file; no user text is shell code.
        command = out / 'build-contract.cmd'
        command.write_text(f'@echo off\ncall "{developer}" -arch=x64 >nul\n'
            'if errorlevel 1 exit /b %errorlevel%\n'
            f'cl /nologo /std:c11 /W4 /WX /O2 /I"{headers.parent}" '
            f'/Fe:"{out / "session_contract_test.exe"}" /Fo:"{out / "session_contract_test.obj"}" '
            f'"{source / "session_contract_test.c"}"\n'
            'if errorlevel 1 exit /b %errorlevel%\n'
            f'"{out / "session_contract_test.exe"}"\n')
        result = subprocess.run(['cmd.exe', '/d', '/c', str(command)], capture_output=True, text=True)
    else:
        exe = out / 'session_contract_test'
        compile_result = subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
            str(source / 'session_contract_test.c'), '-o', str(exe)], capture_output=True, text=True)
        (out / 'contract-compile.log').write_text(compile_result.stdout + compile_result.stderr)
        if compile_result.returncode:
            raise RuntimeError(compile_result.stdout + compile_result.stderr)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
    (out / 'contract-test.log').write_text(result.stdout + result.stderr)
    if result.returncode or 'AFE_DMA_SESSION_CONTRACT_PASS' not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
