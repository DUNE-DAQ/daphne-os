from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "petalinux" / "bootstrap_kr260_project.sh"
LOCAL_APPEND = ROOT / "petalinux" / "config" / "kr260" / "local.conf.append"
EMMC_WKS = ROOT / "petalinux" / "meta-daphne" / "wic" / "daphne-emmc.wks"
DEVELOPER_WKS = EMMC_WKS.with_name("daphne-emmc-developer.wks.in")
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
            env["DAPHNE_META_LAYER_MODE"] = "copy"
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
                env={**os.environ, "DAPHNE_META_LAYER_MODE": "copy"},
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
            'WKS_FILE:pn-petalinux-image-minimal = "'
            "${@bb.utils.contains('DAPHNE_IMAGE_PROFILE', 'developer', "
            "'daphne-emmc-developer.wks.in', 'daphne-emmc.wks', d)}\"",
            fragment,
        )

        wks = EMMC_WKS.read_text(encoding="utf-8")
        self.assertIn("--fixed-size=128M", wks)
        self.assertIn("--label boot", wks)
        self.assertIn("--label root", wks)

    def test_developer_workspace_budget_is_scoped_to_runtime_image(self) -> None:
        fragment = LOCAL_APPEND.read_text(encoding="utf-8")
        self.assertIn(
            'IMAGE_ROOTFS_EXTRA_SPACE:pn-petalinux-image-minimal ?= "'
            "${@bb.utils.contains('DAPHNE_IMAGE_PROFILE', 'developer', "
            "'2097152', '0', d)}\"",
            fragment,
        )
        self.assertNotIn("\nIMAGE_ROOTFS_EXTRA_SPACE =", fragment)

    def test_developer_wic_only_adds_root_filesystem_workspace(self) -> None:
        def partitions(path: Path) -> list[list[str]]:
            return [
                shlex.split(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("part ")
            ]

        compact = partitions(EMMC_WKS)
        developer = partitions(DEVELOPER_WKS)
        self.assertEqual(len(compact), 2)
        self.assertEqual(len(developer), 2)
        self.assertEqual(developer[0], compact[0])
        # PetaLinux 2026.1 detects explicit --extra-space via the literal flag
        # token; the equals form is parsed but then reset to its 10 MiB default.
        self.assertEqual(
            developer[1], compact[1] + ["--extra-space", "${IMAGE_ROOTFS_EXTRA_SPACE}K"]
        )
        self.assertFalse(any("--extra-space" in arg for part in compact for arg in part))

    def test_profile_switch_refreshes_config_and_copies_developer_template(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            project = Path(root_text) / "project"
            (project / "build" / "conf").mkdir(parents=True)
            (project / "project-spec" / "configs").mkdir(parents=True)
            (project / "build" / "conf" / "bblayers.conf").write_text(
                'BBLAYERS = ""\n', encoding="utf-8"
            )
            local_conf = project / "build" / "conf" / "local.conf"
            local_conf.write_text("", encoding="utf-8")
            (project / "project-spec" / "configs" / "config").write_text(
                "", encoding="utf-8"
            )
            layer = project / "project-spec/meta-daphne"
            staged_input = layer / "recipes-apps/daphne-server/files/staged/project-input"
            env = {**os.environ, "DAPHNE_OS_ROOT": str(ROOT)}
            env.pop("DAPHNE_META_LAYER_MODE", None)
            for index, profile in enumerate(("developer", "minimal", "provisioning", "developer")):
                with self.subTest(profile=profile):
                    subprocess.run(
                        [str(BOOTSTRAP), str(project), "--image-profile", profile],
                        check=True,
                        env=env,
                        text=True,
                        capture_output=True,
                    )
                    config = local_conf.read_text(encoding="utf-8")
                    self.assertIn(f'DAPHNE_IMAGE_PROFILE = "{profile}"', config)
                    self.assertEqual(config.count("\nDAPHNE_IMAGE_PROFILE ="), 1)
                    self.assertEqual(config.count("\nWKS_FILE:"), 1)
                    self.assertEqual(config.count("\nIMAGE_ROOTFS_EXTRA_SPACE:"), 1)
                    self.assertIn(LOCAL_APPEND.read_text(encoding="utf-8"), config)
                    template = (
                        project / "project-spec" / "meta-daphne" / "wic"
                        / DEVELOPER_WKS.name
                    )
                    self.assertEqual(template.read_bytes(), DEVELOPER_WKS.read_bytes())
                    self.assertFalse(layer.is_symlink())
                    if index == 0:
                        staged_input.write_text("preserve staged runtime input")
                    else:
                        self.assertEqual(staged_input.read_text(), "preserve staged runtime input")
            result = subprocess.run(
                [str(BOOTSTRAP), str(project)], capture_output=True, text=True,
                env={**env, "DAPHNE_META_LAYER_MODE": "symlink"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(staged_input.read_text(), "preserve staged runtime input")


if __name__ == "__main__":
    unittest.main()
