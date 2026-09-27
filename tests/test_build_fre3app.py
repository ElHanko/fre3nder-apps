#!/usr/bin/env python3
"""Host-side tests for deterministic `.fre3app` construction."""

import hashlib
import pathlib
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build-fre3app"
DUMMY = ROOT / "apps/dummy"


class BuildFre3AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.private = self.root / "private.pem"
        self.public = self.root / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", self.private],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", self.private, "-pubout", "-out", self.public],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def tearDown(self):
        self.temp.cleanup()

    def build(self, output):
        return subprocess.run(
            [
                str(BUILDER),
                str(DUMMY),
                "--key",
                str(self.private),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_build_is_reproducible(self):
        first = self.root / "a.fre3app"
        second = self.root / "b.fre3app"

        r1 = self.build(first)
        r2 = self.build(second)

        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(
            hashlib.sha256(first.read_bytes()).digest(),
            hashlib.sha256(second.read_bytes()).digest(),
        )

    def test_package_signature_and_manifest_are_valid(self):
        package = self.root / "dummy.fre3app"
        result = self.build(package)
        self.assertEqual(result.returncode, 0, result.stderr)

        with zipfile.ZipFile(package, "r") as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertIn("manifest.toml", names)
            self.assertIn("service", names)
            self.assertIn("SHA256SUMS", names)
            self.assertIn("SHA256SUMS.sig", names)

            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

            manifest = tomllib.loads(
                archive.read("manifest.toml").decode("utf-8")
            )
            sums = archive.read("SHA256SUMS")
            signature = archive.read("SHA256SUMS.sig")

        der = subprocess.run(
            [
                "openssl",
                "pkey",
                "-pubin",
                "-in",
                self.public,
                "-outform",
                "DER",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
        fingerprint = hashlib.sha256(der).hexdigest()
        self.assertEqual(
            manifest["publisher"]["key_fingerprint"],
            fingerprint,
        )

        sums_path = self.root / "SHA256SUMS"
        sig_path = self.root / "SHA256SUMS.sig"
        sums_path.write_bytes(sums)
        sig_path.write_bytes(signature)

        verify = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-rawin",
                "-pubin",
                "-inkey",
                self.public,
                "-in",
                sums_path,
                "-sigfile",
                sig_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self.assertEqual(verify.returncode, 0)

    def test_autostart_false_is_supported(self):
        source = self.root / "dummy-no-autostart"
        shutil.copytree(DUMMY, source)

        manifest = source / "manifest.toml.in"
        text = manifest.read_text()
        manifest.write_text(
            text.replace(
                "autostart = true",
                "autostart = false",
            )
        )

        package = self.root / "no-autostart.fre3app"
        result = subprocess.run(
            [
                str(BUILDER),
                str(source),
                "--key",
                str(self.private),
                "--output",
                str(package),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

        with zipfile.ZipFile(package, "r") as archive:
            built_manifest = tomllib.loads(
                archive.read("manifest.toml").decode("utf-8")
            )

        self.assertIs(
            built_manifest["runtime"]["autostart"],
            False,
        )

    def test_service_interpreter_is_not_restricted(self):
        source = self.root / "dummy-python-service"
        shutil.copytree(DUMMY, source)

        (source / "service").write_text(
            "#!/usr/bin/python3\n"
            "raise SystemExit(0)\n"
        )

        package = self.root / "python-service.fre3app"
        result = subprocess.run(
            [
                str(BUILDER),
                str(source),
                "--key",
                str(self.private),
                "--output",
                str(package),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_key_is_never_copied_into_package(self):
        package = self.root / "dummy.fre3app"
        result = self.build(package)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(package, "r") as archive:
            payload = b"".join(
                archive.read(name)
                for name in archive.namelist()
            )
        self.assertNotIn(b"PRIVATE KEY", payload)


if __name__ == "__main__":
    unittest.main()
