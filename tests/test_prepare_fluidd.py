#!/usr/bin/env python3
"""Host-only Fluidd source checks; no download, signing key, or package build."""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import tomllib
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/fluidd"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FluiddSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.helper = load("prepare_fluidd_test", ROOT / "scripts/prepare-fluidd")

    def fixture(self, extra=None):
        path = self.root / "fluidd.zip"
        members = {
            "index.html": "<html>Fluidd</html>",
            "release_info.json": json.dumps({
                "project_name": "fluidd",
                "project_owner": "fluidd-core",
                "version": "v1.37.6",
            }),
        }
        members.update(extra or {})
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return path, {
            "asset_size": path.stat().st_size,
            "asset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "version": "v1.37.6",
        }

    def test_pinned_manifest_and_service(self):
        manifest = tomllib.loads((SOURCE / "manifest.toml.in").read_text())
        self.assertEqual(manifest["app"], {
            "name": "fluidd", "version": "1.37.6-fre3nder.1", "release_serial": 1,
        })
        self.assertEqual(manifest["runtime"]["autostart"], False)
        self.assertEqual(manifest["web"]["frontend"], True)
        upstream = json.loads((SOURCE / "upstream.json").read_text())
        self.assertEqual(upstream["asset_size"], 4359674)
        self.assertEqual(upstream["asset_sha256"], "9fe5bcd4a443f4cccd20cef222e70cc334a874070b21d116097a28405b0ed456")
        service = (SOURCE / "service").read_text()
        for forbidden in ("urllib", "urlopen", "https://", "moonraker.conf", "frontend/active", "S62"):
            self.assertNotIn(forbidden, service)

    def test_archive_hash_and_safe_extract(self):
        archive, upstream = self.fixture()
        target = self.root / "payload"
        self.helper.prepare(archive, target, upstream)
        self.assertEqual((target / "index.html").read_text(), "<html>Fluidd</html>")
        upstream["asset_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.helper.prepare(archive, target, upstream)
        upstream["asset_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        upstream["asset_size"] += 1
        with self.assertRaisesRegex(ValueError, "size"):
            self.helper.prepare(archive, target, upstream)

    def test_unsafe_zip_and_wrong_release_are_rejected(self):
        for member in ("../escape", "/absolute", "nested//name", "nested\\name"):
            with self.subTest(member=member):
                archive, upstream = self.fixture({member: "bad"})
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    self.helper.prepare(archive, self.root / "payload", upstream)
        archive, upstream = self.fixture({"release_info.json": '{"version":"v1.0.0"}'})
        with self.assertRaisesRegex(ValueError, "identity or version"):
            self.helper.prepare(archive, self.root / "payload", upstream)

    def test_zip_symlink_is_rejected(self):
        archive, upstream = self.fixture()
        member = zipfile.ZipInfo("linked")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "a") as zipped:
            zipped.writestr(member, "index.html")
        upstream["asset_size"] = archive.stat().st_size
        upstream["asset_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.helper.prepare(archive, self.root / "payload", upstream)

    def test_service_validates_payload_without_platform_writes(self):
        archive, upstream = self.fixture()
        runtime = self.root / "runtime"
        self.helper.prepare(archive, runtime / "payload", upstream)
        env = dict(os.environ, FRE3NDER_APP_RUNTIME_DIR=str(runtime))
        for action in ("install", "update", "restore", "start", "status", "stop", "uninstall"):
            result = subprocess.run(["sh", str(SOURCE / "service"), action], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, (action, result.stderr))
        (runtime / "payload/index.html").write_text("")
        for action in ("install", "update", "restore", "status"):
            result = subprocess.run(["sh", str(SOURCE / "service"), action], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_generic_builder_checks_web_capability_without_signing(self):
        builder = load("fre3app_builder_test", ROOT / "scripts/build-fre3app")
        fingerprint = "a" * 64
        self.assertIn(b"frontend = true", builder.render_manifest(SOURCE, fingerprint))
        dummy = ROOT / "apps/dummy"
        self.assertNotIn("web", tomllib.loads(builder.render_manifest(dummy, fingerprint).decode()))


if __name__ == "__main__":
    unittest.main()
