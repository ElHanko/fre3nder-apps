#!/usr/bin/env python3
"""Offline tests for Moonraker input acquisition; no network or builds."""
import hashlib
from contextlib import redirect_stderr
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "apps/moonraker/scripts/fetch-moonraker-inputs"
loader = importlib.machinery.SourceFileLoader("fetch_moonraker_inputs", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class Response(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class FetchMoonrakerInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.recipe = self.base / "recipe"
        self.recipe.mkdir()
        self.origin = self.base / "upstream"
        self.origin.mkdir()
        subprocess.run(["git", "init", "-q", str(self.origin)], check=True)
        entry = self.origin / "moonraker/moonraker.py"
        entry.parent.mkdir()
        entry.write_text("# fixture\n")
        subprocess.run(["git", "-C", str(self.origin), "add", "moonraker/moonraker.py"], check=True)
        subprocess.run(["git", "-C", str(self.origin), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.origin), "rev-parse", "HEAD"], text=True).strip()
        self.filename = "testdep-1.0-py3-none-any.whl"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("testdep/__init__.py", "version = '1.0'\n")
        self.wheel = stream.getvalue()
        self.digest = hashlib.sha256(self.wheel).hexdigest()
        self.meta_url = "https://pypi.org/pypi/testdep/1.0/json"
        self.wheel_url = "https://files.pythonhosted.org/packages/testdep.whl"
        self.meta = {"urls": [{"filename": self.filename, "size": len(self.wheel),
                               "digests": {"sha256": self.digest}, "url": self.wheel_url}]}
        (self.recipe / "upstream.json").write_text(json.dumps({
            "repository": str(self.origin), "commit": self.commit,
        }))
        (self.recipe / "python-wheels.json").write_text(json.dumps({
            "target": {"python": "3.12", "platform": "any", "implementation": "py", "abi": "none"},
            "wheels": [{
            "name": "testdep", "version": "1.0", "filename": self.filename,
            "sha256": self.digest,
        }]}))
        self.cache = self.base / "cache"

    def response(self, request, timeout=60):
        url = request.full_url
        if url == self.meta_url:
            return Response(json.dumps(self.meta).encode(), url)
        if url == self.wheel_url:
            return Response(self.wheel, url)
        raise AssertionError(f"unexpected request: {url}")

    def test_fetch_then_reuse_pinned_offline_cache(self):
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response) as get:
            source, wheels = helper.fetch(self.cache)
            self.assertEqual(source, self.cache / "source")
            self.assertEqual(wheels, self.cache / "wheels")
            self.assertTrue((source / "moonraker/moonraker.py").is_file())
            self.assertEqual((wheels / self.filename).read_bytes(), self.wheel)
            self.assertEqual(get.call_count, 2)
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            helper.fetch(self.cache)

    def test_progress_messages_distinguish_download_and_cache(self):
        first = io.StringIO()
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response), \
                redirect_stderr(first):
            helper.fetch(self.cache)
        output = first.getvalue()
        self.assertIn("Moonraker source: fetching pinned commit", output)
        self.assertIn("[1/1]", output)
        self.assertIn("resolving PyPI download", output)
        self.assertIn(f"downloading ({helper.format_size(len(self.wheel))})", output)
        self.assertIn("downloaded, SHA-256 OK", output)
        self.assertIn("All Moonraker inputs are ready", output)

        second = io.StringIO()
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network used")), \
                redirect_stderr(second):
            helper.fetch(self.cache)
        self.assertIn("Moonraker source: checking cached checkout", second.getvalue())
        self.assertIn("cached, SHA-256 OK", second.getvalue())

    def test_download_size_uses_appropriate_units(self):
        self.assertEqual(helper.format_size(512), "512 B")
        self.assertEqual(helper.format_size(16 * 1024), "16.0 KiB")
        self.assertEqual(helper.format_size(150 * 1024), "150.0 KiB")
        self.assertEqual(helper.format_size(1024 * 1024), "1.0 MiB")
        self.assertEqual(helper.format_size(1330000), "1.3 MiB")

    def test_existing_tampered_wheel_is_rejected(self):
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response):
            _, wheels = helper.fetch(self.cache)
        (wheels / self.filename).write_bytes(b"tampered")
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                helper.fetch(self.cache)

    def test_dirty_source_is_rejected(self):
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response):
            source, _ = helper.fetch(self.cache)
        (source / "moonraker/moonraker.py").write_text("changed\n")
        with mock.patch.object(helper, "RECIPE", self.recipe):
            with self.assertRaisesRegex(ValueError, "uncommitted changes"):
                helper.fetch(self.cache)

    def test_wheel_url_must_be_pypi_https(self):
        self.meta["urls"][0]["url"] = "https://example.invalid/wheel.whl"
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response):
            with self.assertRaisesRegex(ValueError, "invalid PyPI wheel"):
                helper.fetch_wheel(self.base, {
                    "name": "testdep", "version": "1.0", "filename": self.filename,
                    "sha256": self.digest,
                })

    def test_existing_source_pin_cannot_be_silently_changed(self):
        with mock.patch.object(helper, "RECIPE", self.recipe), \
                mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response):
            source, _ = helper.fetch(self.cache)
        with self.assertRaisesRegex(ValueError, "pinned commit"):
            helper.validate_source(source, "0" * 40)

    def test_selected_inputs_have_separate_cache_and_remain_unchanged(self):
        upstream = self.base / 'selected-upstream.json'
        lock = self.base / 'selected-lock.json'
        upstream.write_text(json.dumps({'repository': str(self.origin), 'commit': self.commit,
                                        'fixture': 'alternative'}))
        lock.write_bytes((self.recipe / 'python-wheels.json').read_bytes() + b'\n')
        paths = (upstream, lock, self.recipe / 'upstream.json', self.recipe / 'python-wheels.json')
        before = {p: p.read_bytes() for p in paths}
        with mock.patch.object(helper, 'RECIPE', self.recipe), \
                mock.patch.object(helper.urllib.request, 'urlopen', side_effect=self.response):
            default_source, default_wheels = helper.fetch(self.cache)
            source, wheels = helper.fetch(self.cache, upstream_file=upstream, lock_file=lock)
        self.assertNotEqual(source, default_source)
        self.assertNotEqual(wheels, default_wheels)
        self.assertEqual(source.parent.parent, self.cache / 'inputs')
        self.assertEqual((wheels / self.filename).read_bytes(), (default_wheels / self.filename).read_bytes())
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_missing_pypi_wheel_identity_is_rejected(self):
        self.meta["urls"][0]["digests"]["sha256"] = "0" * 64
        with mock.patch.object(helper.urllib.request, "urlopen", side_effect=self.response):
            with self.assertRaisesRegex(ValueError, "locked wheel"):
                helper.fetch_wheel(self.base, {
                    "name": "testdep", "version": "1.0", "filename": self.filename,
                    "sha256": self.digest,
                })


if __name__ == "__main__":
    unittest.main()
