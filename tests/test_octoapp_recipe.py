#!/usr/bin/env python3
"""Host-only OctoApp recipe checks; no network, target build, or signing key."""

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/octoapp"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class OctoAppRecipeTests(unittest.TestCase):
    def setUp(self):
        self.prepare = load(
            "prepare_octoapp_test",
            ROOT / "scripts/prepare-octoapp",
        )

    def test_pinned_manifest_and_upstream(self):
        manifest = tomllib.loads((SOURCE / "manifest.toml.in").read_text())
        self.assertEqual(
            manifest["app"],
            {
                "name": "octoapp",
                "version": "3.2.4-fre3nder.4",
                "release_serial": 4,
            },
        )
        self.assertEqual(manifest["runtime"]["autostart"], True)

        upstream = json.loads((SOURCE / "upstream.json").read_text())
        self.assertEqual(upstream["version"], "3.2.4")
        self.assertEqual(
            upstream["commit"],
            "f6d0cc21aefe77e54aa8e8674c65e911bed1a55e",
        )
        self.assertEqual(upstream["license"], "AGPL-3.0-or-later")

    def test_service_keeps_dependencies_and_updates_isolated(self):
        service = (SOURCE / "service").read_text()
        self.assertIn("include-system-site-packages = false", service)
        self.assertNotIn("OCTOAPP_DISABLE_SYSTEM_CONFIG", service)
        prepare = (ROOT / "scripts/prepare-octoapp").read_text()
        self.assertEqual(
            prepare.count(
                'system_config = destination / "moonraker_octoapp/systemconfigmanager.py"'
            ),
            1,
        )
        self.assertEqual(prepare.count("system_config.unlink()"), 1)
        self.assertNotIn(
            '(destination / "moonraker_octoapp/systemconfigmanager.py").unlink()',
            prepare,
        )
        self.assertIn('"ConfigFolder": str(state)', service)
        for forbidden in (
            "pip install",
            "git clone",
            "systemctl",
            "apt install",
            "opkg install",
            "moonraker.asvc",
            "update_manager",
        ):
            self.assertNotIn(forbidden, service)

    def test_fre3nder_patch_removes_upstream_system_writes(self):
        patch = (
            SOURCE / "patches/0001-fre3nder-disable-system-config.patch"
        ).read_text()
        self.assertNotIn("OCTOAPP_DISABLE_SYSTEM_CONFIG", patch)
        self.assertIn(
            "-from .systemconfigmanager import SystemConfigManager",
            patch,
        )
        self.assertIn(
            "-                SystemConfigManager.EnsureUpdateManagerFilesSetup",
            patch,
        )
        self.assertIn(
            "-            SystemConfigManager.EnsureAllowedServicesFile",
            patch,
        )
        self.assertIn("moonraker_octoapp/moonrakerclient.py", patch)
        self.assertIn("configured moonraker.conf path", patch)

    def test_fre3nder_patch_is_valid_unified_diff(self):
        patch = SOURCE / "patches/0001-fre3nder-disable-system-config.patch"
        result = subprocess.run(
            ["git", "apply", "--numstat", str(patch)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("moonraker_octoapp/moonrakerhost.py", result.stdout)

    def test_requirements_exclude_native_and_non_klipper_optional_packages(self):
        requirements = [
            line.strip()
            for line in (SOURCE / "requirements.in").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        joined = "\n".join(requirements)
        for expected in (
            "octowebsocket_client",
            "octoflatbuffers==24.3.27",
            "requests",
            "httpx",
            "qrcode",
        ):
            self.assertIn(expected, joined)
        for excluded in ("pillow", "pycryptodome", "paho-mqtt", "pybind11"):
            self.assertNotIn(excluded, joined.lower())

    def test_host_tools_do_not_depend_on_system_pip(self):
        lock_script = (ROOT / "scripts/lock-octoapp").read_text()
        prepare_script = (ROOT / "scripts/prepare-octoapp").read_text()
        self.assertIn('PIP_VERSION = "26.2.1"', lock_script)
        self.assertIn("PIP_SHA256 =", lock_script)
        self.assertIn('env["PYTHONPATH"]', lock_script)
        self.assertNotIn('"pip",\n        "--isolated"', prepare_script)
        self.assertIn("download_locked_wheel", prepare_script)

    def test_lock_manifest_matches_recipe_when_present(self):
        lock_path = SOURCE / "python-wheels.json"
        if not lock_path.exists():
            self.skipTest("run scripts/lock-octoapp before final validation")
        upstream = json.loads((SOURCE / "upstream.json").read_text())
        lock = json.loads(lock_path.read_text())
        self.assertEqual(
            lock["resolver"],
            {
                "name": "pip",
                "version": "26.2.1",
                "wheel_sha256": "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
            },
        )
        self.prepare.validate_inputs(upstream, lock)
        self.assertGreater(len(lock["wheels"]), 5)

    def test_dependency_tree_hash_is_deterministic_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a/one.py").write_text("one\n")
            (root / "two.txt").write_text("two\n")
            first = self.prepare.dependency_tree_hash(root)
            second = self.prepare.dependency_tree_hash(root)
            self.assertEqual(first, second)
            (root / "two.txt").write_text("changed\n")
            self.assertNotEqual(first, self.prepare.dependency_tree_hash(root))


if __name__ == "__main__":
    unittest.main()
