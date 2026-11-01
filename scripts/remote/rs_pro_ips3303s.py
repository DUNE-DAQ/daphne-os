#!/usr/bin/env python3
"""Coldbox RS PRO IPS-3303S: fixed 24 V / 1 A, independent CH1/CH2.

Only OUT0/OUT1 can change the instrument. There is no setpoint/mode setter.
The USB connection itself must already exist; no REMOTE/LOCAL is sent.
"""

import argparse
from contextlib import contextmanager
from decimal import Decimal
import json
import re
import sys
import time


DEFAULT_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A505EMDH-if00-port0"
EXPECTED_SERIAL = "725D240G2"
READ_COMMANDS = frozenset(
    ["*IDN?", "STATUS?"]
    + [f"{name}{channel}?" for name in ("VSET", "ISET", "VOUT", "IOUT")
       for channel in (1, 2)]
)


class SupplyError(Exception):
    """Communication, identity, protocol or interlock failure."""


def parse_value(reply, unit):
    text = reply.decode("ascii", errors="strict")
    match = re.fullmatch(r"([0-9]+\.[0-9]+)" + unit + r"\r\n", text)
    if not match:
        raise SupplyError(f"Respuesta {unit} invalida: {reply!r}")
    return Decimal(match.group(1))


def parse_status(reply):
    # Firmware V2.10 sends ASCII positions bit0..bit7 (NOT an MSB-first integer).
    # This is the 9600-capable layout: output=bit5, baud=bits6,7.
    # The older IPS manual's output=bit6 layout must NOT be used here.
    if not re.fullmatch(rb"[01]{8}\r\n", reply):
        raise SupplyError(f"STATUS? invalido o incompleto: {reply!r}")
    bits = reply[:8].decode("ascii")
    mode = {"01": "independent", "11": "series", "10": "parallel"}.get(bits[2:4])
    if mode is None:
        raise SupplyError(f"Modo desconocido: {bits}")
    if bits[6:8] != "10":
        raise SupplyError(f"STATUS? no corresponde al protocolo a 9600 baudios: {bits}")
    return {
        "raw": bits,
        "mode": mode,
        "output_enabled": bits[5] == "1",
        "baud": 9600,
        "ch1_regulation": "CV" if bits[0] == "1" else "CC",
        "ch2_regulation": "CV" if bits[1] == "1" else "CC",
    }


class SerialTransport:
    """Linux standard-library transport, 9600 8N1, bounded CRLF replies."""

    def __init__(self, fd, timeout=2.0):
        self.fd = fd
        self.timeout = timeout

    def _write(self, payload):
        import os
        import select

        deadline = time.monotonic() + self.timeout
        while payload:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise SupplyError("Timeout al enviar; estado de la salida desconocido")
            try:
                count = os.write(self.fd, payload)
            except BlockingIOError:
                continue
            if count <= 0:
                raise SupplyError("No se pudo enviar el comando completo")
            payload = payload[count:]

    def query(self, command):
        import os
        import select

        if command not in READ_COMMANDS:
            raise SupplyError("Consulta no permitida")
        self._write(command.encode("ascii") + b"\r")
        deadline = time.monotonic() + self.timeout
        reply = b""
        while time.monotonic() < deadline:
            if not select.select([self.fd], [], [], max(0, deadline - time.monotonic()))[0]:
                break
            try:
                chunk = os.read(self.fd, 256)
            except BlockingIOError:
                continue
            if not chunk:
                raise SupplyError("USB desconectado; estado desconocido")
            reply += chunk
            if len(reply) > 256:
                raise SupplyError("Respuesta demasiado larga")
            if b"\n" in reply:
                if not reply.endswith(b"\r\n") or reply.count(b"\n") != 1:
                    raise SupplyError(f"Respuesta mal delimitada: {reply!r}")
                time.sleep(0.06)
                return reply
        # Never retry a partial/timed-out transaction: a late reply could be
        # mistaken for a different channel's setpoint in an enable check.
        raise SupplyError(f"Sin respuesta completa para {command}: {reply!r}")

    def write_output(self, enabled):
        if type(enabled) is not bool:
            raise SupplyError("Estado de salida invalido")
        self._write(b"OUT1\n" if enabled else b"OUT0\n")
        time.sleep(0.15)


@contextmanager
def open_serial(port):
    import copy
    import fcntl
    import os
    import termios

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = None
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        original = termios.tcgetattr(fd)
        attrs = copy.deepcopy(original)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = ((attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB
                                | termios.CRTSCTS | termios.HUPCL))
                    | termios.CS8 | termios.CREAD | termios.CLOCAL)
        attrs[4] = attrs[5] = termios.B9600
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        time.sleep(0.25)
        termios.tcflush(fd, termios.TCIFLUSH)
        yield SerialTransport(fd)
    finally:
        try:
            if original is not None:
                termios.tcsetattr(fd, termios.TCSANOW, original)
        finally:
            try:
                if exclusive:
                    fcntl.ioctl(fd, termios.TIOCNXCL)
            finally:
                os.close(fd)


class Supply:
    def __init__(self, transport):
        self.transport = transport

    def identity(self):
        reply = self.transport.query("*IDN?")
        fields = reply.decode("ascii", errors="strict").strip().split(",")
        if (len(fields) != 4 or fields[0].strip() != "RS PRO"
                or fields[1].strip() != "IPS-3303S"
                or fields[2].strip() != f"SN:{EXPECTED_SERIAL}"
                or fields[3].strip() != "V2.10"):
            raise SupplyError(f"Fuente/firmware no reconocido: {reply!r}")
        return reply.decode("ascii").strip()

    def status(self):
        return parse_status(self.transport.query("STATUS?"))

    def config(self):
        before = self.status()
        channels = {}
        for channel in (1, 2):
            channels[str(channel)] = {
                "voltage_V": str(parse_value(self.transport.query(f"VSET{channel}?"), "V")),
                "current_limit_A": str(parse_value(self.transport.query(f"ISET{channel}?"), "A")),
            }
        after = self.status()
        if (before["mode"], before["output_enabled"]) != (after["mode"], after["output_enabled"]):
            raise SupplyError("El estado cambio durante la lectura; repetir consulta")
        return {"status": after, "channels": channels}

    @staticmethod
    def require_safe(config):
        if config["status"]["mode"] != "independent":
            raise SupplyError("Encendido bloqueado: se requiere modo independiente")
        for channel, values in config["channels"].items():
            if (Decimal(values["voltage_V"]) != Decimal("24.000")
                    or Decimal(values["current_limit_A"]) != Decimal("1.000")):
                raise SupplyError(f"Encendido bloqueado: CH{channel} requiere exactamente 24 V y 1 A")

    def measure(self):
        return {str(channel): {
            "voltage_V": str(parse_value(self.transport.query(f"VOUT{channel}?"), "V")),
            "current_A": str(parse_value(self.transport.query(f"IOUT{channel}?"), "A")),
        } for channel in (1, 2)}

    def enable(self):
        # Fresh full checks under one exclusive connection; never fix settings.
        for _ in range(2):
            self.require_safe(self.config())
        try:
            self.transport.write_output(True)
            config = self.config()
            self.require_safe(config)
            if not config["status"]["output_enabled"]:
                raise SupplyError("La fuente no confirma las salidas habilitadas")
            return config
        except (SupplyError, OSError, UnicodeError, KeyboardInterrupt) as error:
            # Only after an explicitly requested ON: fail back to OFF on an
            # unconfirmed transition. No automatic ON retry is ever sent.
            try:
                self.transport.write_output(False)
            except (SupplyError, OSError):
                pass
            raise SupplyError(f"Encendido no verificado; se intento OUT0. Estado desconocido: {error}") from error

    def disable(self):
        # Shutdown is allowed even if setpoints or mode are unsafe.
        self.transport.write_output(False)
        state = self.status()
        if state["output_enabled"]:
            raise SupplyError("No se confirma el apagado; estado de la salida incierto")
        return state

    def run(self, command):
        identity = self.identity()
        action = {"on": self.enable, "off": self.disable, "config": self.config,
                  "status": self.status, "measure": self.measure}[command]
        return {"identity": identity, "command": command, "result": action()}


class SimulatedTransport:
    """In-memory instrument; never opens a serial port or loads termios."""

    def __init__(self):
        self.mode = "independent"
        self.enabled = False
        self.values = {"VSET1?": b"24.000V\r\n", "ISET1?": b"1.000A\r\n",
                       "VSET2?": b"24.000V\r\n", "ISET2?": b"1.000A\r\n"}
        self.history = []

    def query(self, command):
        if command not in READ_COMMANDS:
            raise SupplyError("Consulta no permitida")
        self.history.append(command)
        if command == "*IDN?":
            return b"RS PRO  ,IPS-3303S,SN:725D240G2,V2.10\r\n"
        if command == "STATUS?":
            mode = {"independent": "01", "series": "11", "parallel": "10"}[self.mode]
            regulation = "11" if self.enabled else "00"
            return (regulation + mode + "1" + str(int(self.enabled)) + "10\r\n").encode("ascii")
        if command in self.values:
            return self.values[command]
        if command.startswith("VOUT"):
            return b"23.998V\r\n" if self.enabled else b"0.000V\r\n"
        return b"0.460A\r\n" if self.enabled else b"0.000A\r\n"

    def write_output(self, enabled):
        if type(enabled) is not bool:
            raise SupplyError("Estado de salida invalido")
        self.history.append("OUT1" if enabled else "OUT0")
        self.enabled = enabled


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("on", "off", "config", "status", "measure"))
    parser.add_argument("--port", default=DEFAULT_PORT, help="Puerto Linux; se verifica identidad antes de actuar")
    parser.add_argument("--simulate", action="store_true", help="Simulacion en memoria, sin acceso al USB")
    args = parser.parse_args(argv)
    try:
        if args.simulate:
            result = Supply(SimulatedTransport()).run(args.command)
        else:
            with open_serial(args.port) as transport:
                result = Supply(transport).run(args.command)
        result["simulation"] = args.simulate
        print(json.dumps(result, indent=2))
        return 0
    except (SupplyError, OSError, UnicodeError, KeyboardInterrupt) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
