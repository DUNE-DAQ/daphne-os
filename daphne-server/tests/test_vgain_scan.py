"""Execute the Bash scan with fake clients; no network or hardware access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("DAPHNE_TEST_BASH")
if not BASH:
    BASH = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt"
            else shutil.which("bash"))


def shell_path(path):
    value = Path(path).resolve().as_posix()
    if os.name == "nt":
        return "/" + value[0].lower() + value[2:]
    return value


FAKE_CLIENT = r'''#!/usr/bin/env bash
client=${1##*/}
shift
printf '%s' "$client" >> "$SCAN_TEST_CALLS"
printf '\t%s' "$@" >> "$SCAN_TEST_CALLS"
printf '\n' >> "$SCAN_TEST_CALLS"
if [[ "$client" != protobuf_acquire_list_channels.py ]]; then
    echo 'fake configuration readback OK'
    exit 0
fi
channels=()
dma=false
while (( $# )); do
    case "$1" in
        -foldername) folder=$2; shift 2 ;;
        -L) samples=$2; shift 2 ;;
        -N) waveforms=$2; shift 2 ;;
        --dma) dma=true; shift ;;
        -channel_list)
            shift
            while (( $# )) && [[ "$1" != -* ]]; do channels+=("$1"); shift; done ;;
        *) shift ;;
    esac
done
if [[ "${SCAN_TEST_WAIT:-}" == 1 ]]; then
    trap 'echo cancelled >> "$SCAN_TEST_CALLS"; exit 130' TERM INT HUP
    echo ready > "$SCAN_TEST_READY"
    while :; do sleep 0.05; done
fi
if [[ "${SCAN_TEST_FAIL:-}" == 1 && "$folder" == */vgain_1800 ]]; then
    echo partial > "$folder/channel_${channels[0]}.dat"
    exit 1
fi
for channel in "${channels[@]}"; do
    dd if=/dev/zero of="$folder/channel_${channel}.dat" bs=$((samples * waveforms * 2)) count=1 2>/dev/null || exit 1
done
if [[ "$dma" == true ]]; then
    printf '{"saved_encoding":"offset_binary"}\n' > "$folder/dma_format.json"
    printf '{"waveforms":%s}\n' "$waveforms" > "$folder/dma_metadata_test.jsonl"
fi
'''


@unittest.skipUnless(BASH and Path(BASH).is_file(), "Bash is required")
class VgainScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vgain scan ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scan = self.root / "bash_scripts" / "vgain_scan.sh"
        self.scan.parent.mkdir()
        self.scan.write_text((ROOT / "bash_scripts" / "vgain_scan.sh").read_text(), newline="\n")
        self.fake = self.root / "fake_python"
        self.fake.write_text(FAKE_CLIENT, newline="\n")
        self.fake.chmod(0o755)
        self.output = self.root / "data"
        self.calls_file = self.root / "calls.tsv"
        self.env = dict(os.environ, DAPHNE_PYTHON=shell_path(self.fake),
                        SCAN_TEST_CALLS=shell_path(self.calls_file),
                        SCAN_TEST_READY=shell_path(self.root / "ready"))

    def arguments(self, *options):
        return ["-folder", shell_path(self.output), "-vgain_list", "[1700,1800]",
                "-bias", "0", "-channel", "0", "1", "-L", "8", "-N", "2",
                "-ip", "fake", "-port", "40001", "--yes", *options]

    def run_scan(self, *options, resume=False, env=None):
        args = (["-folder", shell_path(self.output), "--resume", "--yes", *options]
                if resume else self.arguments(*options))
        return subprocess.run([BASH, shell_path(self.scan), *args], env=env or self.env,
                              capture_output=True, text=True, timeout=30)

    def calls(self, client=None):
        rows = [line.split("\t") for line in self.calls_file.read_text().splitlines()]
        return [row for row in rows if client is None or row[0] == client]

    def metadata(self):
        return dict(line.split("=", 1) for line in
                    (self.output / "scan_metadata.txt").read_text().splitlines())

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_syntax(self):
        self.assert_ok(subprocess.run([BASH, "-n", shell_path(self.scan)], capture_output=True, text=True))

    def test_sourced_dma_scan_preserves_calling_shell(self):
        result = subprocess.run([BASH, "-c", 'source "$@" || exit $?; echo caller_alive', "test",
                                 shell_path(self.scan), *self.arguments("--dma", "--force-acq")],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assert_ok(result)
        self.assertIn("caller_alive", result.stdout)
        self.assertEqual(self.metadata()["status"], "complete")

    def test_spybuffer_default_and_completed_resume(self):
        self.assert_ok(self.run_scan())
        self.assertEqual(self.metadata()["backend"], "spybuffer")
        self.assertFalse(any("--dma" in row or "--force-acq" in row for row in self.calls()))
        calls = self.calls_file.read_text()
        self.assert_ok(self.run_scan(resume=True))
        self.assertEqual(self.calls_file.read_text(), calls)

    def test_dma_force_reaches_points_and_final_restoration(self):
        self.assert_ok(self.run_scan("--dma", "--force-acq", "-trigger_source", "software"))
        pedestal = self.calls("protobuf_configure_pedestal_level.py")
        self.assertEqual(len(pedestal), 3)
        for row in pedestal:
            self.assertIn("--dma", row)
            self.assertIn("--force-acq", row)
            self.assertNotIn("--pretrigger", row)
        for row in self.calls("protobuf_acquire_list_channels.py"):
            self.assertIn("--dma", row)
            self.assertIn("--force-acq", row)
            self.assertEqual(row[row.index("--capture-mode") + 1], "persistent")
        for point in (self.output / "vbias_0").glob("vgain_*"):
            manifest = (point / "SHA256SUMS").read_text()
            names = [line[66:] for line in manifest.splitlines()]
            self.assertIn("dma_format.json", names)
            self.assertIn("dma_metadata_test.jsonl", names)
        self.assertEqual(self.metadata()["status"], "complete")
        self.assertEqual(self.metadata()["force_acq"], "true")

    def test_dma_external_pretrigger_and_deadlines_only_affect_data(self):
        self.assert_ok(self.run_scan("--dma", "--capture-mode", "triggered", "--pretrigger", "3",
                                     "--trigger-timeout-ms", "2000", "--job-timeout-ms", "5000"))
        for row in self.calls("protobuf_acquire_list_channels.py"):
            self.assertEqual(row[row.index("--pretrigger") + 1], "3")
            self.assertEqual(row[row.index("-trigger_source") + 1], "external")
            self.assertEqual(row[row.index("--trigger-timeout-ms") + 1], "2000")
            self.assertEqual(row[row.index("--job-timeout-ms") + 1], "5000")
            self.assertNotIn("--force-acq", row)
        for row in self.calls("protobuf_configure_pedestal_level.py"):
            self.assertIn("--dma", row)
            self.assertNotIn("--capture-mode", row)
            self.assertNotIn("--force-acq", row)

    def test_finite_dma_requires_and_forwards_software(self):
        self.assert_ok(self.run_scan("--dma", "--force_acq", "--capture-mode", "finite",
                                     "-trigger_source", "software"))
        for row in self.calls("protobuf_acquire_list_channels.py"):
            self.assertEqual(row[row.index("--capture-mode") + 1], "finite")
            self.assertIn("--force-acq", row)

    def test_invalid_dma_options_fail_before_any_client(self):
        invalid = (
            ("--force-acq",), ("--pretrigger", "0"), ("--capture-mode", "persistent"),
            ("--dma", "-trigger_source", "all"), ("--dma", "--capture-mode", "finite"),
            ("--dma", "--capture-mode", "unknown"), ("--dma", "--pretrigger", "8"),
            ("--dma", "--trigger-timeout-ms", "9"), ("--dma", "--job-timeout-ms", "1"),
            ("--dma", "--job-timeout-ms", "604800001"),
            ("--dma", "--pressure-timeout-ms", "9"),
            ("--dma", "--capture-mode", "triggered", "--pressure-timeout-ms", "100"),
            ("--dma", "--pretrigger", "-1"), ("--dma", "--pretrigger", "abc"),
        )
        for options in invalid:
            with self.subTest(options=options):
                result = self.run_scan(*options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls_file.exists())

    def test_failed_dma_scan_restores_and_resume_retains_settings(self):
        env = dict(self.env, SCAN_TEST_FAIL="1")
        self.assertNotEqual(self.run_scan("--dma", "--force-acq", "--pretrigger", "2",
                                          "--pressure-timeout-ms", "1000", env=env).returncode, 0)
        self.assertEqual(self.metadata()["status"], "failed_restored")
        self.calls_file.write_text("")
        self.assert_ok(self.run_scan(resume=True))
        rows = self.calls("protobuf_acquire_list_channels.py")
        self.assertEqual(len(rows), 1)
        self.assertIn("vgain_1800", rows[0][rows[0].index("-foldername") + 1])
        self.assertIn("--force-acq", rows[0])
        self.assertEqual(rows[0][rows[0].index("--pretrigger") + 1], "2")
        self.assertEqual(rows[0][rows[0].index("--pressure-timeout-ms") + 1], "1000")

    def test_completed_dma_resume_checks_metadata_corruption(self):
        self.assert_ok(self.run_scan("--dma", "--force-acq"))
        metadata = self.output / "vbias_0" / "vgain_1700" / "dma_metadata_test.jsonl"
        metadata.write_text("corrupt\n")
        previous = self.calls_file.read_text()
        self.assertNotEqual(self.run_scan(resume=True).returncode, 0)
        self.assertEqual(previous, self.calls_file.read_text())

    def test_resume_rejects_missing_contract_and_cli_overrides(self):
        self.assert_ok(self.run_scan("--dma"))
        self.assertNotEqual(self.run_scan("--dma", resume=True).returncode, 0)
        path = self.output / "scan_metadata.txt"
        path.write_text(path.read_text().replace("backend=dma\n", ""))
        previous = self.calls_file.read_text()
        self.assertNotEqual(self.run_scan(resume=True).returncode, 0)
        self.assertEqual(previous, self.calls_file.read_text())

    def test_version_one_spybuffer_metadata_can_resume(self):
        self.assert_ok(self.run_scan())
        path = self.output / "scan_metadata.txt"
        dma_keys = {"backend", "capture_mode", "force_acq", "pretrigger", "trigger_timeout_ms",
                    "job_timeout_ms", "pressure_timeout_ms"}
        text = "\n".join(line for line in path.read_text().splitlines()
                         if line.split("=", 1)[0] not in dma_keys)
        path.write_text(text.replace("format_version=2", "format_version=1") + "\n")
        previous = self.calls_file.read_text()
        self.assert_ok(self.run_scan(resume=True))
        self.assertEqual(previous, self.calls_file.read_text())

    def test_sigterm_waits_for_child_before_dma_restoration(self):
        wrapper = r'''
bash "$@" &
scan_pid=$!
for ((i=0; i<400; i++)); do
    [[ -f "$SCAN_TEST_READY" ]] && break
    sleep 0.05
done
[[ -f "$SCAN_TEST_READY" ]] || { kill -TERM "$scan_pid"; wait "$scan_pid"; exit 99; }
kill -TERM "$scan_pid"
wait "$scan_pid"
'''
        result = subprocess.run([BASH, "-c", wrapper, "test", shell_path(self.scan),
                                 *self.arguments("--dma", "--force-acq")],
                                env=dict(self.env, SCAN_TEST_WAIT="1"),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 143, result.stdout + result.stderr)
        rows = self.calls()
        cancelled = rows.index(["cancelled"])
        restoration = [row for row in rows[cancelled + 1:] if row[0] == "protobuf_configure_pedestal_level.py"]
        self.assertEqual(len(restoration), 1)
        self.assertIn("--dma", restoration[0])
        self.assertIn("--force-acq", restoration[0])
        self.assertEqual(self.metadata()["status"], "interrupted_term_restored")


if __name__ == "__main__":
    unittest.main()
