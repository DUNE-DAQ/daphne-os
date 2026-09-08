"""Regress the source/OS boundary without a companion firmware checkout."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RepositoryBoundaryTests(unittest.TestCase):
    def test_hdl_and_vivado_implementation_are_not_in_os(self) -> None:
        for relative in ("ip_repo", "xilinx", "rtl", "cores", "formal", "scripts/fusesoc"):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_os_and_native_server_entry_points_are_present(self) -> None:
        for relative in (
            "petalinux/meta-daphne/conf/layer.conf", "daphne-server/CMakeLists.txt",
            "scripts/server/build_native.sh", "scripts/deploy/daphne_deploy_campaign.py",
            "scripts/remote/xsdb_boot_uboot.tcl",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_os_wrappers_resolve_the_os_root(self) -> None:
        for relative in (
            "petalinux/bootstrap_kr260_project.sh", "petalinux/init_kr260_project.sh",
            "petalinux/build_kr260_image.sh", "petalinux/collect_project_artifacts.sh",
            "petalinux/generate_qspi_boot_candidates.sh", "remote/test_qspi_primary_multiboot.sh",
        ):
            source = (ROOT / "scripts" / relative).read_text()
            self.assertIn("DAPHNE_OS_ROOT", source)
            self.assertNotIn("DAPHNE_FIRMWARE_ROOT", source)

    def test_native_helper_keeps_install_and_hardware_tests_separate(self) -> None:
        source = (ROOT / "scripts/server/build_native.sh").read_text()
        self.assertIn("-DDAPHNE_ENABLE_HARDWARE_TESTS=OFF", source)
        self.assertIn("-DDAPHNE_BUILD_PY_PROTO=ON", source)
        self.assertNotIn("systemctl", source)
        self.assertNotIn("cmake --install", source)

    def test_complete_server_history_is_reachable(self) -> None:
        subprocess.run(["python3", str(ROOT / "scripts/check_server_history.py")], check=True)


if __name__ == "__main__":
    unittest.main()
