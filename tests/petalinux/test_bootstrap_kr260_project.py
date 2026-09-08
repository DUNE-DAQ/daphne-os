from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "petalinux" / "bootstrap_kr260_project.sh"
LOCAL_APPEND = ROOT / "petalinux" / "config" / "kr260" / "local.conf.append"
EMMC_WKS = ROOT / "petalinux" / "meta-daphne" / "wic" / "daphne-emmc.wks"
DEVELOPER_PACKAGEGROUP = (
    ROOT / "petalinux" / "meta-daphne" / "recipes-core" / "packagegroups"
    / "packagegroup-daphne-server-build.bb"
)
PROTOBUF_APPEND = (
    ROOT / "petalinux" / "meta-daphne" / "recipes-devtools" / "protobuf"
    / "protobuf_%.bbappend"
)


class BootstrapKr260ProjectTests(unittest.TestCase):
    def test_developer_profile_includes_protobuf_static_cmake_dependencies(self) -> None:
        # Protobuf's installed CMake config imports utf8_validity, which is
        # packaged as a static library even with shared Protobuf enabled.
        recipe = DEVELOPER_PACKAGEGROUP.read_text(encoding="utf-8")
        self.assertIn("protobuf-staticdev", recipe.split())

    def test_developer_profile_enables_target_protoc_binary(self) -> None:
        fragment = PROTOBUF_APPEND.read_text(encoding="utf-8")
        self.assertIn(
            'PACKAGECONFIG:append:class-target = " '
            "${@bb.utils.contains('DAPHNE_IMAGE_PROFILE', 'developer', "
            "'compiler', '', d)}\"",
            fragment,
        )

    def test_developer_packagegroup_sets_architecture_before_inheriting(self) -> None:
        # packagegroup.bbclass immediately snapshots PACKAGE_ARCH. Setting it
        # afterwards still inherits allarch, which rejects renamed Protobuf
        # packages during RPM packaging even when PACKAGE_ARCH later changes.
        recipe = DEVELOPER_PACKAGEGROUP.read_text(encoding="utf-8")
        self.assertLess(
            recipe.index('PACKAGE_ARCH = "${MACHINE_ARCH}"'),
            recipe.index("inherit packagegroup"),
        )

    def test_provisioning_profile_is_accepted_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            project = Path(root_text) / "project"
            (project / "build" / "conf").mkdir(parents=True)
            (project / "project-spec" / "configs").mkdir(parents=True)
            (project / "build" / "conf" / "bblayers.conf").write_text(
                'BBLAYERS = ""\n', encoding="utf-8"
            )
            (project / "build" / "conf" / "local.conf").write_text(
                "", encoding="utf-8"
            )
            (project / "project-spec" / "configs" / "config").write_text(
                'CONFIG_SUBSYSTEM_MACHINE_NAME="AUTO"\n', encoding="utf-8"
            )

            env = os.environ.copy()
            env["DAPHNE_META_LAYER_MODE"] = "symlink"
            # A hardware-build environment must not redirect the OS layer.
            env["DAPHNE_FIRMWARE_ROOT"] = str(Path(root_text) / "missing-firmware")
            env["DAPHNE_OS_ROOT"] = str(ROOT)
            subprocess.run(
                [str(BOOTSTRAP), str(project), "--image-profile", "provisioning"],
                check=True,
                env=env,
                text=True,
                capture_output=True,
            )

            local_conf = (project / "build" / "conf" / "local.conf").read_text(
                encoding="utf-8"
            )
            self.assertIn('DAPHNE_IMAGE_PROFILE = "provisioning"', local_conf)

            project_config = (
                project / "project-spec" / "configs" / "config"
            ).read_text(encoding="utf-8")
            self.assertIn(
                "CONFIG_SUBSYSTEM_PMUFW_SERIAL_PSU_UART_1_SELECT=y",
                project_config,
            )
            self.assertIn(
                "CONFIG_SUBSYSTEM_FSBL_SERIAL_PSU_UART_1_SELECT=y",
                project_config,
            )
            self.assertIn(
                "CONFIG_SUBSYSTEM_TF-A_SERIAL_PSU_UART_1_SELECT=y",
                project_config,
            )
            self.assertIn(
                "CONFIG_SUBSYSTEM_SERIAL_PSU_UART_1_SELECT=y",
                project_config,
            )
            self.assertIn(
                "# CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL is not set",
                project_config,
            )
            self.assertNotIn(
                "CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL=y",
                project_config,
            )
            self.assertNotIn(
                "CONFIG_SUBSYSTEM_SERIAL_PSU_CORESIGHT_0_SELECT=y",
                project_config,
            )

    def test_minimal_xsa_profile_also_disables_qspi_image_selector(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            project = Path(root_text) / "project"
            (project / "build" / "conf").mkdir(parents=True)
            (project / "project-spec" / "configs").mkdir(parents=True)
            (project / "build" / "conf" / "bblayers.conf").write_text(
                'BBLAYERS = ""\n', encoding="utf-8"
            )
            (project / "build" / "conf" / "local.conf").write_text(
                "", encoding="utf-8"
            )
            config = project / "project-spec" / "configs" / "config"
            config.write_text(
                "CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL=y\n", encoding="utf-8"
            )

            subprocess.run(
                [str(BOOTSTRAP), str(project), "--image-profile", "minimal"],
                check=True,
                env={**os.environ, "DAPHNE_META_LAYER_MODE": "symlink"},
                text=True,
                capture_output=True,
            )

            project_config = config.read_text(encoding="utf-8")
            self.assertIn(
                "# CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL is not set",
                project_config,
            )
            self.assertNotIn(
                "CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL=y",
                project_config,
            )

    def test_provisioning_profile_excludes_runtime_package_set(self) -> None:
        fragment = LOCAL_APPEND.read_text(encoding="utf-8")
        self.assertIn("DAPHNE_RUNTIME_PACKAGES", fragment)
        self.assertIn(
            "contains('DAPHNE_IMAGE_PROFILE', 'provisioning', ''",
            fragment,
        )

    def test_factory_wic_image_is_enabled_with_compact_boot_partition(self) -> None:
        fragment = LOCAL_APPEND.read_text(encoding="utf-8")
        self.assertIn(
            'IMAGE_FSTYPES:append:pn-petalinux-image-minimal = " wic.gz"',
            fragment,
        )
        self.assertIn(
            'WKS_FILE:pn-petalinux-image-minimal = "daphne-emmc.wks"',
            fragment,
        )

        wks = EMMC_WKS.read_text(encoding="utf-8")
        self.assertIn("--fixed-size=128M", wks)
        self.assertIn("--label boot", wks)
        self.assertIn("--label root", wks)


if __name__ == "__main__":
    unittest.main()
