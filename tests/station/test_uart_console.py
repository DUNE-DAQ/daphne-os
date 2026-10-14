import contextlib
import io
import json
from pathlib import Path
import re
import runpy
import sys
import types
import unittest
from unittest.mock import patch

import tempfile
import getpass
_tmp = tempfile.TemporaryDirectory()
BASE = Path(_tmp.name)
import shutil
shutil.copytree(Path(__file__).resolve().parents[2] / 'scripts/station/bin', BASE / 'bin')
(BASE / 'station.json').write_text(json.dumps({'station_id':'test','vivado_root':'/tools/test','fixture_server_ip':'192.168.0.104','fixture_prefix':24,'tftp_root':'/test','tftp_release_path':'release','fixture_public_key':'/fake/daphne_fixture_ed25519.pub'}))
sys.path.insert(0, str(BASE / 'bin'))
import uart_console as uc

class Output:
    def __init__(self): self.buffer = io.BytesIO()
    def write(self, text): self.buffer.write(text.encode()); return len(text)
    def flush(self): pass
    def text(self): return self.buffer.getvalue().decode()

class Port:
    def __init__(self, stage='linux', fail=None, line_ending=b'\r\n'):
        self.stage, self.fail, self.line_ending = stage, fail, line_ending
        self.queue, self.writes = [], []
        self.root_observed = stage == 'linux'
        self.closed = False
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def flush(self): pass
    def read(self, size):
        if not self.queue: return b''
        value = self.queue.pop(0)
        if b'sh-5.2# ' in value: self.root_observed = True; self.stage = 'linux'
        return value
    def write(self, data):
        self.writes.append(data)
        if self.stage == 'kernel': return len(data)
        if self.stage == 'uboot':
            if data == b'\n': self.queue.append(b'\r\nZynqMP> '); return len(data)
            if not data.endswith(b'\r'): raise AssertionError('U-Boot requires CR')
            if data == b'\r': self.queue.append(b'\r\nZynqMP> ')
            elif data.startswith(b'booti '):
                self.stage = 'kernel'
                self.queue += [b'## Flattened Device Tree blob at 40000000\r\n',
                               b'Starting kernel ...\r\nRemoving MTD device #0 (nor0)\r\n',
                               b'Linux version 6.18\r\nsh: no job control in this shell\r\nsh-5.2# ']
            else:
                token = re.search(rb'DAPHNE_RESULT_[0-9a-f]+', data).group()
                self.queue.append(data + b'\r\n' + token + b':0\r\nZynqMP> ')
            return len(data)
        if not data.endswith(b'\n') or b'\r' in data:
            return len(data)  # Linux without icrnl ignores CR as a line terminator.
        if self.stage == 'login':
            if data == b'\n': self.queue.append(b'daphne-005 login: ')
            elif data == b'root\n': self.stage = 'password'; self.queue.append(b'Password: ')
            else: raise AssertionError('Unexpected login input')
            return len(data)
        if self.stage == 'password':
            if data == b'\n': raise AssertionError('Injected an empty password')
            self.stage = 'linux'; self.queue.append(b'\r\nsh-5.2# ')
            return len(data)
        if data == b'\n': self.queue.append(b'\r\nsh-5.2# '); return len(data)
        if not self.root_observed: raise AssertionError('Command sent before Linux root was observed')
        token = re.search(rb'DAPHNE_RESULT_[0-9a-f]+', data).group()
        status = self.fail(data) if self.fail else 0
        # Echo includes the token but must not be mistaken for a result.
        self.queue += [data, self.line_ending + token + b':' + str(status).encode() + self.line_ending + b'sh-5.2# ']
        return len(data)

class Clock:
    def __init__(self): self.value = 0
    def monotonic(self): self.value += .05; return self.value
    def sleep(self, value): self.value += value

class Tests(unittest.TestCase):
    def run_script(self, name, port, *args):
        out = Output()
        fake_serial = types.SimpleNamespace(Serial=lambda *a, **kw: port, SerialException=OSError)
        argv = [str(BASE / 'bin' / name), 'DAPHNE-005', '/dev/fake-uart', *args]
        with patch.dict(sys.modules, {'serial': fake_serial}), patch.object(sys, 'argv', argv), contextlib.redirect_stdout(out), patch.object(getpass, 'getpass', return_value='test-password'):
            runpy.run_path(argv[0], run_name='__main__')
        return out.text()
    def test_linux_uses_lf_without_stty(self):
        port = Port()
        c = uc.Console(port)
        c.ready_linux_root(timeout=1)
        c.run('echo READY', timeout=1)
        self.assertTrue(all(x.endswith(b'\n') and b'\r' not in x for x in port.writes))
    def test_uboot_uses_cr(self):
        port = Port('uboot'); c = uc.Console(port)
        c.prompt(linux=False, timeout=1)
        c.run('mmc dev 0 0', linux=False, timeout=1)
        self.assertTrue(all(x.endswith(b'\r') for x in port.writes))
    def test_boot_banner_is_not_linux_readiness(self):
        port = Port('uboot')
        output = self.run_script('boot-provision-shell', port)
        self.assertIn('Linux provisioning shell READY', output)
        self.assertTrue(port.root_observed)
        self.assertTrue(port.closed)
        self.assertTrue(any(b'uname -s' in x for x in port.writes))
    def test_linux_readiness_rejects_uboot(self):
        port = Port('uboot')
        with self.assertRaises(uc.ConsoleError): uc.Console(port).ready_linux_root(timeout=1)
        self.assertFalse(any(b'id -u' in x for x in port.writes))
    def test_boot_chatter_cannot_satisfy_prompt(self):
        port = Port('kernel')
        port.queue = [b'## Flattened Device Tree\r\n', b'Removing MTD device #0 (nor0)\r\n']
        with patch.object(uc, 'time', Clock()), self.assertRaises(uc.ConsoleError):
            uc.Console(port).ready_linux_root(timeout=.5)
        self.assertFalse(any(b'id -u' in x for x in port.writes))
    def test_failed_command_propagates_status(self):
        port = Port(fail=lambda data: 7)
        with self.assertRaises(uc.ConsoleError) as result:
            uc.Console(port).run('false', timeout=1)
        self.assertEqual(result.exception.status, 7)
    def test_echo_without_result_times_out(self):
        class EchoOnly(Port):
            def write(self, data): self.writes.append(data); self.queue.append(data); return len(data)
        with patch.object(uc, 'time', Clock()), self.assertRaises(uc.ConsoleError):
            uc.Console(EchoOnly()).run('echo TEST', timeout=.5)
    def test_linux_login_does_not_inject_empty_password(self):
        port = Port('login')
        output = self.run_script('linux-console', port, 'echo TEST')
        self.assertIn('DAPHNE_RESULT_', output)
        self.assertTrue(port.closed)
    def test_console_cli_failed_command_is_nonzero(self):
        port = Port(fail=lambda data: 7 if data.startswith(b'false;') else 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            self.run_script('linux-console', port, 'false')
        self.assertEqual(result.exception.code, 7)
    def test_double_cr_newline_is_accepted(self):
        uc.Console(Port(line_ending=b'\r\r\n')).run('echo TEST', timeout=1)
    def test_provisioning_completes_in_cr_rejecting_linux(self):
        record = BASE / 'records/DAPHNE-005/board-config-v1.json'
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'network': {'hostname':'daphne-005','ipv4_address':'192.168.0.205','production_mac':'00:0a:35:24:03:ee'}}))
        original_is_file, original_read_text = Path.is_file, Path.read_text
        def is_file(path): return True if path.name == 'daphne_fixture_ed25519.pub' else original_is_file(path)
        def read_text(path, *a, **kw): return 'ssh-ed25519 AAAA fixture\n' if path.name == 'daphne_fixture_ed25519.pub' else original_read_text(path,*a,**kw)
        port = Port()
        with patch.object(Path, 'is_file', is_file), patch.object(Path, 'read_text', read_text):
            output = self.run_script('provision-linux', port)
        self.assertIn('Provisioned DAPHNE-005', output)
        self.assertTrue(all(x.endswith(b'\n') and b'\r' not in x for x in port.writes))
        self.assertEqual(sum(b'DAPHNE_RESULT_' in x for x in port.writes),12)
    def test_provisioning_stops_at_first_failed_step(self):
        original_is_file, original_read_text = Path.is_file, Path.read_text
        def is_file(path): return True if path.name == 'daphne_fixture_ed25519.pub' else original_is_file(path)
        def read_text(path,*a,**kw): return 'ssh-ed25519 AAAA fixture\n' if path.name == 'daphne_fixture_ed25519.pub' else original_read_text(path,*a,**kw)
        port=Port(fail=lambda data: 1 if data.startswith(b'mkdir ') else 0)
        with patch.object(Path,'is_file',is_file), patch.object(Path,'read_text',read_text), self.assertRaises(SystemExit):
            self.run_script('provision-linux',port)
        self.assertFalse(any(x.startswith(b'chmod ') for x in port.writes))

if __name__ == '__main__': unittest.main(verbosity=2)