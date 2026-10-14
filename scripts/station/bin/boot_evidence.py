"""Validate the boot messages actually emitted by the pinned firmware."""
import re
from uart_console import ConsoleError


def validate_boot_output(output, hostname):
    output = output.replace(b'\r', b'')
    if re.search(rb'kernel panic|bad crc', output, re.I):
        raise ConsoleError('Normal boot reported a kernel panic or invalid environment')
    checks = (
        ('QSPI boot mode', rb'(?:^|\n)(?:Bootmode:[ \t]+QSPI_MODE|QSPI (?:24|32) bit Boot Mode)'),
        ('saved SPI environment OK', rb'Loading Environment from SPIFlash\.\.\.[^\n]*\n?[ \t]*OK(?:\n|$)'),
        ('DAPHNE controller startup', rb'DAPHNE Slow Controller'),
        ('multi-user Linux', rb'Multi-User System'),
        ('expected hostname login', re.escape(hostname.encode()) + rb' login:'),
    )
    for label, pattern in checks:
        if not re.search(pattern, output):
            raise ConsoleError('Missing normal-boot evidence: ' + label)
