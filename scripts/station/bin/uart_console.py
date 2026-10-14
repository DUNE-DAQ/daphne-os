"""Serial framing and readiness checks for the Cooper deployment helpers."""

import re
import secrets
import sys
import time


UBOOT = re.compile(rb"(?:^|[\r\n])ZynqMP>[ \t]*$")
ROOT = re.compile(rb"(?:^|[\r\n])[^\r\n#]*#[ \t]*$")
LOGIN = re.compile(rb"(?:^|[\r\n])[^\r\n]*login:[ \t]*$", re.I)
PASSWORD = re.compile(rb"(?:^|[\r\n])[^\r\n]*password:[ \t]*$", re.I)


class ConsoleError(RuntimeError):
    def __init__(self, message, status=1, output=b""):
        super().__init__(message)
        self.status = status
        self.output = output


class Console:
    def __init__(self, port, log=None, display=False):
        self.port = port
        self.log = log
        self.display = display

    def read(self):
        data = self.port.read(8192)
        if data and self.log is not None:
            self.log.write(data)
            self.log.flush()
        if data and self.display:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        return data

    def send(self, text, linux=True):
        self.port.write(text.encode() + (b"\n" if linux else b"\r"))
        self.port.flush()

    def prompt(self, linux=True, timeout=30, allow_login=False, wake=True):
        deadline = time.monotonic() + timeout
        next_wake = 0.0
        output = b""
        while time.monotonic() < deadline:
            if wake and time.monotonic() >= next_wake:
                self.send("", linux=linux)
                next_wake = time.monotonic() + 1
            chunk = self.read()
            output = (output + chunk)[-131072:]
            if UBOOT.search(output):
                if linux:
                    raise ConsoleError("Board is at U-Boot, not Linux; boot the provisioning shell first")
                return "uboot"
            if ROOT.search(output):
                if not linux:
                    raise ConsoleError("Board is already in a shell, not U-Boot")
                return "root"
            if linux:
                if LOGIN.search(output):
                    if not allow_login:
                        raise ConsoleError("Linux is at a login prompt; start the temporary provisioning shell first")
                    return "login"
                if PASSWORD.search(output):
                    if not allow_login:
                        raise ConsoleError("Linux is asking for a password, not at a provisioning root shell")
                    return "password"
            if not chunk:
                time.sleep(0.02)
        raise ConsoleError("Timed out waiting for " + ("Linux root/login prompt" if linux else "U-Boot prompt"))

    def run(self, command, linux=True, timeout=90, label="command"):
        token = "DAPHNE_RESULT_" + secrets.token_hex(8)
        if linux:
            suffix = "; daphne_command_status=$?; printf '\\n" + token + ":%s\\n' \"$daphne_command_status\""
        else:
            suffix = "; echo " + token + ":$?"
        self.send(command + suffix, linux=linux)
        pattern = re.compile(rb"(?:^|[\r\n])" + token.encode() + rb":([0-9]+)(?=[\r\n])")
        deadline = time.monotonic() + timeout
        output = b""
        while time.monotonic() < deadline:
            chunk = self.read()
            output += chunk
            match = pattern.search(output)
            if match:
                result = int(match.group(1))
                if result:
                    raise ConsoleError(f"{label} failed (exit {result})", result, output)
                if linux or UBOOT.search(output):
                    return output
            if not chunk:
                time.sleep(0.02)
        raise ConsoleError(f"Timed out waiting for {label}; stop and inspect the console", output=output)

    def verify_linux_root(self):
        self.run('test "$(id -u)" = 0 && test "$(uname -s)" = Linux',
                 timeout=30, label="Linux root-shell verification")

    def ready_linux_root(self, timeout=180):
        self.prompt(timeout=timeout)
        self.verify_linux_root()
