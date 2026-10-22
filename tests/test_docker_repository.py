"""Targeted no-build tests for the optional repository publisher."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "docker-repository" / "repositoryd.py"
spec = importlib.util.spec_from_file_location("fre3nder_repositoryd", SCRIPT)
repositoryd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repositoryd)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.toml"
        self.config.write_text('''
[server]
check_interval_hours = 6
[repository]
name = "Test repo"
signing_key = "/keys/repo-private.pem"
[publishers.test-publisher]
public_key = "/keys/test-public.pem"
[apps.test-app]
enabled = true
publisher = "test-publisher"
mode = "maintained"
channel = "stable"
''')
        self.app = {"name": "test-app", "publisher": "test-publisher",
                    "channel": "stable", "mode": "maintained"}
        self.fingerprint = "a" * 64

    def make_archive(self, *, tamper=False, serial=1):
        manifest = f'''format = 1
[app]
name = "test-app"
version = "1.0.0-fre3nder.1"
release_serial = {serial}
[publisher]
id = "test-publisher"
key_fingerprint = "{self.fingerprint}"
[target]
platform = "fre3nder-x2000"
arch = "mipsel"
[runtime]
service = "service"
autostart = true
[signature]
algorithm = "Ed25519"
file = "SHA256SUMS.sig"
signed_file = "SHA256SUMS"
'''.encode()
        files = {"manifest.toml": manifest, "service": b"#!/bin/sh\nexit 0\n"}
        sums = ''.join(f'{hashlib.sha256(content).hexdigest()}  {name}\n'
                       for name, content in sorted(files.items())).encode()
        archive_path = self.root / "test.fre3app"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for name, content in files.items():
                zf.writestr(name, content + (b"tampered" if tamper and name == "service" else b""))
            zf.writestr("SHA256SUMS", sums)
            # Fake signature is used only by mocked cryptographic unit tests.
            zf.writestr("SHA256SUMS.sig", bytes(64))
        return archive_path

    def test_config_accepts_generic_publisher_and_mode(self):
        repo, pub, apps, hours = repositoryd.load_config(self.config)
        self.assertEqual((repo["name"], apps["test-app"]["publisher"], hours),
                         ("Test repo", "test-publisher", 6.0))
        self.assertEqual(pub["test-publisher"]["public_key"], "/keys/test-public.pem")

    def test_reject_unknown_publisher(self):
        data = self.config.read_text().replace('publisher = "test-publisher"',
                                               'publisher = "unknown"')
        self.config.write_text(data)
        with self.assertRaises(repositoryd.RepositoryError):
            repositoryd.load_config(self.config)

    @mock.patch.object(repositoryd, "verify_signature")
    def test_reads_signed_package_metadata(self, verifier):
        archive = self.make_archive()
        item = repositoryd.validate_package(archive, self.app, "/keys/test-public.pem",
                                             self.fingerprint)
        self.assertEqual(item["version"], "1.0.0-fre3nder.1")
        self.assertEqual(item["release_serial"], 1)
        self.assertEqual(item["sha256"], repositoryd.hash_file(archive))
        verifier.assert_called_once()

    @mock.patch.object(repositoryd, "verify_signature")
    def test_reject_tampered_file_before_signature_verification(self, verifier):
        with self.assertRaisesRegex(repositoryd.RepositoryError, "checksum mismatch"):
            repositoryd.validate_package(self.make_archive(tamper=True), self.app,
                                         "/keys/test-public.pem", self.fingerprint)
        verifier.assert_not_called()

    @mock.patch.object(repositoryd, "verify_signature")
    def test_reject_release_serial_zero_in_stable(self, verifier):
        with self.assertRaisesRegex(repositoryd.RepositoryError, "testing channel"):
            repositoryd.validate_package(self.make_archive(serial=0), self.app,
                                         "/keys/test-public.pem", self.fingerprint)

    @mock.patch.object(repositoryd, "verify_signature")
    def test_reject_untrusted_publisher_key(self, verifier):
        with self.assertRaisesRegex(repositoryd.RepositoryError, "publisher identity"):
            repositoryd.validate_package(self.make_archive(), self.app,
                                         "/keys/different.pem", "b" * 64)

    @mock.patch.object(repositoryd, "sign_index", return_value=b"s" * 64)
    def test_index_idempotence_and_monotonic_revisions(self, signer):
        public = self.root / "public"
        public.mkdir()
        args = (public, "Test repo", "c" * 64, Path("/keys/repo-private.pem"))
        self.assertTrue(repositoryd.publish_index(*args, []))
        first = json.loads((public / "index.json").read_text())
        self.assertEqual(first["revision"], 1)
        self.assertEqual((public / "index.json.sig").read_bytes(), b"s" * 64)
        self.assertTrue((public / "index.json").stat().st_mode & 0o004)
        self.assertFalse(repositoryd.publish_index(*args, []))
        self.assertEqual(signer.call_count, 1)
        self.assertTrue(repositoryd.publish_index(*args, [{"name": "test-app"}]))
        second = json.loads((public / "index.json").read_text())
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["packages"], [{"name": "test-app"}])

    def test_unsafe_zip_member_name(self):
        for name in ("../evil", "/absolute", "payload//item", "payload\\item"):
            with self.subTest(name=name):
                self.assertFalse(repositoryd.is_safe_member(name))

    @mock.patch.object(repositoryd, "verify_signature")
    def test_disabled_app_is_not_listed_from_existing_public_files(self, verifier):
        public = self.root / "public"
        target = public / "packages" / "test-app"
        target.mkdir(parents=True)
        archive = self.make_archive()
        (target / "package.fre3app").write_bytes(archive.read_bytes())
        pubs = {"test-publisher": {"public_key": "/keys/test-public.pem"}}
        self.assertEqual(repositoryd.collect(public, {}, pubs, {}), [])

    @mock.patch.object(repositoryd, "verify_signature")
    def test_same_publisher_and_serial_cannot_be_published_twice(self, verifier):
        public = self.root / "public"
        target = public / "packages" / "test-app"
        target.mkdir(parents=True)
        archive = self.make_archive()
        (target / "one.fre3app").write_bytes(archive.read_bytes())
        (target / "two.fre3app").write_bytes(archive.read_bytes())
        pubs = {"test-publisher": {"public_key": "/keys/test-public.pem"}}
        with self.assertRaisesRegex(repositoryd.RepositoryError, "duplicate published"):
            repositoryd.collect(public, {"test-app": self.app}, pubs,
                                {"test-publisher": self.fingerprint})

    @mock.patch.object(repositoryd, "verify_signature")
    def test_import_keeps_package_bytes_unchanged(self, verifier):
        data = self.root / "data"
        (data / "incoming").mkdir(parents=True)
        (data / "public").mkdir()
        origin = self.make_archive()
        original_hash = repositoryd.hash_file(origin)
        incoming = data / "incoming" / "test-app.fre3app"
        incoming.write_bytes(origin.read_bytes())
        pubs = {"test-publisher": {"public_key": "/keys/test-public.pem"}}
        apps = {"test-app": self.app}
        fingerprints = {"test-publisher": self.fingerprint}
        repositoryd.import_incoming(data, apps, pubs, fingerprints, [])
        self.assertFalse(incoming.exists())
        saved = list((data / "public" / "packages" / "test-app").glob("*.fre3app"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(repositoryd.hash_file(saved[0]), original_hash)
        self.assertTrue(saved[0].stat().st_mode & 0o004)
        collected = repositoryd.collect(data / "public", apps, pubs, fingerprints)
        self.assertEqual(collected[0]["name"], "test-app")


if __name__ == "__main__":
    unittest.main()
