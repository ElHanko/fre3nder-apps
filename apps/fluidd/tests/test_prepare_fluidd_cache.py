#!/usr/bin/env python3
"""Offline checks for the pinned Fluidd download cache and progress output."""

from contextlib import redirect_stderr
import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT = Path(__file__).resolve().parents[3] / "apps/fluidd/scripts/prepare-fluidd"
loader = importlib.machinery.SourceFileLoader("fluidd_cache_test", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class Response(io.BytesIO):
    def geturl(self):
        return "https://github.com/fluidd-core/fluidd/releases/download/v1.37.6/fluidd.zip"


class FluiddCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = self.root / "apps/fluidd"
        source.mkdir(parents=True)
        self.source = source
        self.cache = self.root / "local/fluidd"
        self.package = self.root / "local/fluidd/package"
        for name in ("manifest.toml.in", "service", *helper.PACKAGE_FILES):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(helper.SOURCE / name, target)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zipped:
            zipped.writestr("index.html", "<html>Fluidd</html>")
            zipped.writestr("release_info.json", json.dumps({
                "project_name": "fluidd", "project_owner": "fluidd-core", "version": "v1.37.6"
            }))
            zipped.writestr("large-file.bin", b"x" * (1024 * 1024 + 1024))
        self.data = archive.getvalue()
        self.upstream = {
            "version": "v1.37.6",
            "asset_url": "https://github.com/fluidd-core/fluidd/releases/download/v1.37.6/fluidd.zip",
            "asset_size": len(self.data),
            "asset_sha256": hashlib.sha256(self.data).hexdigest(),
        }
        (source / "upstream.json").write_text(json.dumps(self.upstream))
        self.source_patch = mock.patch.object(helper, "SOURCE", source)
        self.cache_patch = mock.patch.object(helper, "CACHE_DIR", self.cache)
        self.output_patch = mock.patch.object(helper, "DEFAULT_OUTPUT", self.package)
        self.source_patch.start()
        self.cache_patch.start()
        self.output_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.addCleanup(self.cache_patch.stop)
        self.addCleanup(self.output_patch.stop)

    def test_first_run_downloads_second_run_reuses_verified_cache(self):
        logs = io.StringIO()
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=Response(self.data)) as network, \
                mock.patch.object(sys, "argv", ["prepare-fluidd"]), redirect_stderr(logs):
            helper.main()
        network.assert_called_once()
        output = logs.getvalue()
        self.assertIn("downloading Fluidd v1.37.6", output)
        self.assertIn("downloaded 1.0 MiB /", output)
        self.assertIn("download complete, SHA-256 OK", output)
        self.assertIn("ready:", output)
        payload = self.package / "payload"
        self.assertTrue((payload / "index.html").is_file())
        self.assertEqual(len(list(self.cache.glob("*.zip"))), 1)

        logs = io.StringIO()
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network used")), \
                mock.patch.object(sys, "argv", ["prepare-fluidd"]), redirect_stderr(logs):
            helper.main()
        self.assertIn("cached archive:", logs.getvalue())
        self.assertIn("ready:", logs.getvalue())
        self.assertEqual({p.relative_to(self.package).as_posix() for p in self.package.rglob("*") if p.is_file()}, {
            "manifest.toml.in", "service", "upstream.json", "licenses/UPSTREAM", "licenses/LICENSE.fluidd",
            "payload/index.html", "payload/release_info.json", "payload/large-file.bin",
        })

    def test_tampered_cache_is_rejected_without_network_or_payload_change(self):
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=Response(self.data)):
            cached = helper.cached_archive(self.upstream)
        cached.write_bytes(b"tampered")
        payload = self.package / "payload"
        payload.mkdir(parents=True)
        (payload / "marker").write_text("preserve")
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network used")), \
                mock.patch.object(sys, "argv", ["prepare-fluidd"]):
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                helper.main()
        self.assertEqual((payload / "marker").read_text(), "preserve")

    def test_incomplete_download_is_not_published_to_cache(self):
        with mock.patch.object(helper.urllib.request, "urlopen", return_value=Response(self.data[:-100])):
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                helper.cached_archive(self.upstream)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_explicit_archive_does_not_download_or_populate_cache(self):
        supplied = self.root / "supplied.zip"
        supplied.write_bytes(self.data)
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network used")), \
                mock.patch.object(sys, "argv", ["prepare-fluidd", "--archive", str(supplied)]):
            helper.main()
        self.assertTrue((self.package / "payload/index.html").is_file())
        self.assertFalse(list(self.cache.glob("*.zip")))

    def test_cache_directory_symlink_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        self.cache.parent.mkdir()
        self.cache.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "real directory"):
            helper.cached_archive(self.upstream)
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
