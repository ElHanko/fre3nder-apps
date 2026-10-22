#!/usr/bin/env python3
"""Offline host-side checks for the Moonraker system fre3app recipe.

No device access, signing keys, network or root privileges required.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[3]
RECIPE = ROOT / "apps/moonraker"
PREPARE = ROOT / "apps/moonraker/scripts/prepare-moonraker"


def module_from(path):
    loader = importlib.machinery.SourceFileLoader("moonraker_prepare_recipe_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class MoonrakerRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = module_from(PREPARE)

    def test_manifest_matches_system_app_contract(self):
        manifest = tomllib.loads((RECIPE / "manifest.toml.in").read_text())
        self.assertEqual(manifest["app"]["name"], "moonraker")
        self.assertGreaterEqual(manifest["app"]["release_serial"], 0)
        self.assertEqual(manifest["publisher"]["id"], "fre3nder-official")
        self.assertEqual(manifest["target"], {
            "platform": "fre3nder-x2000", "arch": "mipsel"
        })
        self.assertEqual(manifest["runtime"], {
            "service": "service", "autostart": False
        })
        self.assertEqual(manifest["signature"]["algorithm"], "Ed25519")

    def test_upstream_and_lock_are_pinned(self):
        upstream = json.loads((RECIPE / "upstream.json").read_text())
        self.assertEqual(upstream["commit"],
                         "9e676eba6b02661a4dfa3ec6e7ac3f3504498e6d")
        self.assertEqual(upstream["repository"],
                         "https://github.com/Arksine/moonraker.git")
        lock = json.loads((RECIPE / "python-wheels.json").read_text())
        self.assertEqual(lock["target"], {
            "python": "3.12", "platform": "any", "implementation": "py", "abi": "none"
        })
        self.assertGreater(len(lock["wheels"]), 0)
        filenames = set()
        for entry in lock["wheels"]:
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertNotIn(entry["filename"], filenames)
            filenames.add(entry["filename"])
            self.assertTrue(entry["filename"].endswith(".whl"))

    def test_service_preserves_platform_printer_data_and_is_offline(self):
        script = (RECIPE / "service").read_text()
        self.assertIn("FRE3NDER_APP_RUNTIME_DIR", script)
        self.assertIn("FRE3NDER_APP_DATA_DIR", script)
        self.assertIn("$home/printer_data", script)
        self.assertIn("/run/fre3nder-moonraker", script)
        self.assertIn("-u \"$uds\"", script)
        self.assertIn("status) running", script)
        for forbidden in ("pip install", "git clone", "apt install", "systemctl"):
            self.assertNotIn(forbidden, script)
        result = subprocess.run(["sh", "-n", str(RECIPE / "service")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_pin_and_offline_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            app_file = source / "moonraker/moonraker.py"
            app_file.parent.mkdir()
            app_file.write_text("print('pinned')\n")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run([
                "git", "-C", str(source), "-c", "user.name=Fixture",
                "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"
            ], check=True)
            commit = subprocess.check_output([
                "git", "-C", str(source), "rev-parse", "HEAD"
            ], text=True).strip()
            wheel_data = b"__version__ = '1.0'\n"
            cache = base / "wheels"
            cache.mkdir()
            filename = "testdep-1.0-py3-none-any.whl"
            with zipfile.ZipFile(cache / filename, "w") as archive:
                archive.writestr("testdep/__init__.py", wheel_data)
            digest = hashlib.sha256((cache / filename).read_bytes()).hexdigest()
            local_recipe = base / "recipe"
            local_recipe.mkdir()
            upstream = {
                "schema": 1, "python": "3.12", "commit": commit,
                "repository": "https://example.invalid/fixture.git"
            }
            lock = {
                "schema": 1,
                "target": {"python": "3.12", "platform": "any", "implementation": "py", "abi": "none"},
                "wheels": [{"name": "testdep", "version": "1.0", "filename": filename, "sha256": digest}]
            }
            (local_recipe / "upstream.json").write_text(json.dumps(upstream))
            (local_recipe / "python-wheels.json").write_text(json.dumps(lock))
            for name in ("manifest.toml.in", "service", "licenses/UPSTREAM"):
                target = local_recipe / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(RECIPE / name, target)
            output = base / "payload"
            with mock.patch.object(self.mod, "RECIPE", local_recipe):
                self.mod.prepare(source, cache, output)
                self.assertEqual((output / "source/moonraker/moonraker.py").read_text(),
                                 app_file.read_text())
                self.assertEqual((output / "python/testdep/__init__.py").read_bytes(),
                                 wheel_data)
                self.assertFalse((output / "source/.git").exists())
                self.assertEqual(json.loads((output / "provenance.json").read_text())
                                 ["source"]["commit"], commit)
                package = base / "package"
                with mock.patch.object(sys, "argv", [str(PREPARE), "--source", str(source),
                        "--wheels", str(cache), "--output", str(package)]):
                    self.mod.main()
                self.assertEqual({p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()}, {
                    "manifest.toml.in", "service", "licenses/UPSTREAM", "upstream.json", "python-wheels.json",
                    "payload/source/moonraker/moonraker.py", "payload/python/testdep/__init__.py",
                    "payload/provenance.json",
                })
                self.mod.prepare(source, cache, output)
                self.assertEqual((output / "source/moonraker/moonraker.py").read_text(),
                                 app_file.read_text())
                # Failed restaging must preserve the previously published payload.
                with mock.patch.object(self.mod, "copy_wheels", side_effect=ValueError("broken cache")):
                    with self.assertRaisesRegex(ValueError, "broken cache"):
                        self.mod.prepare(source, cache, output)
                self.assertEqual((output / "source/moonraker/moonraker.py").read_text(),
                                 app_file.read_text())
                app_file.write_text("print('dirty')\n")
                with self.assertRaisesRegex(ValueError, "dirty"):
                    self.mod.source_pin(source, upstream)
                app_file.write_text("print('pinned')\n")
                bad_lock = dict(lock)
                bad_lock["wheels"] = [dict(lock["wheels"][0], sha256="0" * 64)]
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    self.mod.copy_wheels(cache, bad_lock, base / "bad-wheel-output")

    def test_preparer_rejects_traversal_in_wheels(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cache = base / "wheels"
            cache.mkdir()
            name = "testdep-1.0-py3-none-any.whl"
            with zipfile.ZipFile(cache / name, "w") as archive:
                archive.writestr("../escape.txt", "escape")
            digest = hashlib.sha256((cache / name).read_bytes()).hexdigest()
            lock = {
                "target": {"python": "3.12", "platform": "any", "implementation": "py", "abi": "none"},
                "wheels": [{"filename": name, "sha256": digest}]
            }
            with self.assertRaisesRegex(ValueError, "unsafe wheel member"):
                self.mod.copy_wheels(cache, lock, base / "destination")
            self.assertFalse((base / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
