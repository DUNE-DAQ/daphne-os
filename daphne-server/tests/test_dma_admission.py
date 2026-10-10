import subprocess
import sys
import unittest

BINARY = sys.argv.pop() if len(sys.argv) > 1 else "daphneServer"

class AdmissionTests(unittest.TestCase):
    def test_backend_mismatch_fails_before_hardware_initialization(self):
        for args in (("--gateware-mode","raw-dma"), ("--dma","--gateware-mode","self-trigger"),
                     ("--dma","--gateware-mode","full-stream")):
            with self.subTest(args=args):
                result = subprocess.run([BINARY,*args],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,78)
                self.assertIn("BACKEND_MISMATCH",result.stderr)
                self.assertNotIn("Starting daphneServer",result.stdout)

if __name__ == '__main__': unittest.main()
