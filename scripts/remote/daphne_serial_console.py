#!/usr/bin/env python3
"""Open DAPHNE's stable USB if01 console at 115200 8N1, preferring minicom."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


DEFAULT_PORT = "/dev/serial/by-id/usb-Xilinx_DAPHNE_Mezzanine_004_DAPHNE004-if01-port0"
BAUD = 115200


def run_minicom(executable, port):
    # A private profile avoids inherited modem strings and flow-control settings.
    # -o skips modem initialization. Exit with Ctrl-A, Q to avoid modem reset.
    with tempfile.TemporaryDirectory(prefix="daphne-minicom-") as home:
        Path(home, ".minirc.daphne").write_text(
            f"pu port {port}\npu baudrate 115200\n"
            "pu bits 8\npu parity N\npu stopbits 1\n"
            "pu rtscts No\npu xonxoff No\n", encoding="ascii"
        )
        env = dict(os.environ, HOME=home)
        env.pop("MINICOM", None)
        print(f"DAPHNE: minicom, {port}, 115200 8N1. Salir: Ctrl-A, Q.", flush=True)
        return subprocess.call(
            [executable, "-o", "-8", "-b", str(BAUD), "-D", port, "daphne"], env=env
        )


def run_python(port):
    import copy
    import fcntl
    import select
    import termios
    import tty

    stdin = sys.stdin.fileno()
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    serial_attrs = terminal_attrs = None
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        serial_attrs = termios.tcgetattr(fd)
        attrs = copy.deepcopy(serial_attrs)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = ((attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB
                                | termios.CRTSCTS | termios.HUPCL))
                    | termios.CS8 | termios.CREAD | termios.CLOCAL)
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        terminal_attrs = termios.tcgetattr(stdin)
        print(f"DAPHNE: consola Python, {port}, 115200 8N1. Salir: Ctrl-].", flush=True)
        tty.setraw(stdin)
        while True:
            readable, _, _ = select.select([stdin, fd], [], [])
            if fd in readable:
                data = os.read(fd, 4096)
                if not data:
                    raise OSError("Puerto serie desconectado")
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            if stdin in readable:
                data = os.read(stdin, 4096)
                if not data:
                    return 0
                outgoing, escape, _ = data.partition(b"\x1d")
                while outgoing:
                    if not select.select([], [fd], [], 2)[1]:
                        raise OSError("Timeout al escribir al puerto serie")
                    try:
                        count = os.write(fd, outgoing)
                    except BlockingIOError:
                        continue
                    if not count:
                        raise OSError("Fallo al escribir al puerto serie")
                    outgoing = outgoing[count:]
                if escape:
                    return 0
    finally:
        try:
            if terminal_attrs is not None:
                termios.tcsetattr(stdin, termios.TCSANOW, terminal_attrs)
                print()
        finally:
            try:
                if serial_attrs is not None:
                    termios.tcsetattr(fd, termios.TCSANOW, serial_attrs)
            finally:
                try:
                    if exclusive:
                        fcntl.ioctl(fd, termios.TIOCNXCL)
                finally:
                    os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT, help="Ruta estable /dev/serial/by-id/...-if01-port0")
    parser.add_argument("--check", action="store_true", help="Mostrar disponibilidad sin abrir el puerto")
    args = parser.parse_args(argv)
    port = args.port
    if (not port.startswith("/dev/serial/by-id/") or not port.endswith("-if01-port0")
            or any(char.isspace() for char in port) or "/../" in port):
        parser.error("usar una ruta estable by-id de if01; if00 esta reservado para JTAG")
    minicom = shutil.which("minicom")
    if args.check:
        print(f"port={port}\nresolved_port={os.path.realpath(port)}\nbaud={BAUD}\nformat=8N1\nflow_control=none")
        print(f"backend={minicom or 'python (stdlib)'}")
        print(f"port_exists={os.path.exists(port)}")
        print(f"port_access={os.access(port, os.R_OK | os.W_OK)}")
        return 0 if os.path.exists(port) and os.access(port, os.R_OK | os.W_OK) else 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("ERROR: se necesita una terminal interactiva; conectar con ssh -t.", file=sys.stderr)
        return 1
    try:
        return run_minicom(minicom, port) if minicom else run_python(port)
    except (OSError, KeyboardInterrupt) as error:
        print(f"ERROR: {error or 'interrumpido'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
