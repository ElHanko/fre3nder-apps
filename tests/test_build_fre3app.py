#!/usr/bin/env python3
"""Host-side tests for deterministic `.fre3app` construction."""

import hashlib
import pathlib
import runpy
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build-fre3app"
DUMMY = ROOT / "apps/dummy"


class DisplayManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = pathlib.Path(self.temp.name)
        self.template = (DUMMY / "manifest.toml.in").read_text()
        self.render_manifest = runpy.run_path(str(BUILDER))["render_manifest"]

    def tearDown(self):
        self.temp.cleanup()

    def render(self, display="", autostart=True):
        text = self.template.replace(
            "autostart = true", f"autostart = {str(autostart).lower()}"
        ).replace("[signature]", f"{display}\n[signature]")
        (self.source / "manifest.toml.in").write_text(text)
        return tomllib.loads(
            self.render_manifest(self.source, "a" * 64).decode("utf-8")
        )

    def test_existing_recipes_have_no_display_capability(self):
        for name in ("dummy", "fluidd", "octoapp"):
            with self.subTest(name=name):
                source = ROOT / "apps" / name
                manifest = tomllib.loads(
                    self.render_manifest(source, "a" * 64).decode("utf-8")
                )
                self.assertNotIn("display", manifest)

    def test_display_frontend_api_one_requires_no_autostart(self):
        manifest = self.render("[display]\nfrontend = true\napi = 1", False)
        self.assertEqual(manifest["display"], {"frontend": True, "api": 1})

    def test_display_false_without_api_is_valid(self):
        self.assertEqual(
            self.render("[display]\nfrontend = false")["display"],
            {"frontend": False},
        )

    def test_invalid_display_contracts(self):
        cases = (
            ("[display]\nfrontend = \"true\"", False, "display capability"),
            ("[display]\nfrontend = 1", False, "display capability"),
            ("[display]\nfrontend = true", False, "display API"),
            ("[display]\nfrontend = true\napi = true", False, "display API"),
            ("[display]\nfrontend = true\napi = 2", False, "display API"),
            ("[display]\napi = 1", False, "requires display frontend"),
            (
                "[display]\nfrontend = false\napi = 1",
                False,
                "requires display frontend",
            ),
            ("[display]\nfrontend = true\napi = 1", True, "disable autostart"),
        )
        for display, autostart, error in cases:
            with self.subTest(display=display, autostart=autostart):
                with self.assertRaisesRegex(ValueError, error):
                    self.render(display, autostart)


class DevelopmentManifestPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = pathlib.Path(self.temp.name)
        self.template = (DUMMY / "manifest.toml.in").read_text()
        (self.source / "manifest.toml.in").write_text(self.template)
        self.render_manifest = runpy.run_path(str(BUILDER))["render_manifest"]
        self.fingerprint = "a" * 64

    def test_release_template_remains_unchanged(self):
        rendered = self.render_manifest(self.source, self.fingerprint).decode()
        self.assertEqual(rendered, self.template.replace("@PUBLISHER_FINGERPRINT@", self.fingerprint))
        self.assertEqual(tomllib.loads(rendered)["app"]["release_serial"], 1)

    def test_invalid_mode_combinations(self):
        version = "2026.1.14cd415-fre3nder.0.fd679a9"
        with self.assertRaisesRegex(ValueError, "--version requires --develop"):
            self.render_manifest(self.source, self.fingerprint, version=version)
        with self.assertRaisesRegex(ValueError, "requires a valid --version"):
            self.render_manifest(self.source, self.fingerprint, develop=True)

    def test_development_manifest_changes_only_app_version_and_serial(self):
        version = "2026.1.14cd415-fre3nder.0.fd679a9"
        rendered = self.render_manifest(self.source, self.fingerprint, develop=True, version=version)
        manifest = tomllib.loads(rendered.decode())
        release = tomllib.loads(self.render_manifest(self.source, self.fingerprint).decode())
        self.assertEqual(manifest["app"]["version"], version)
        self.assertEqual(manifest["app"]["release_serial"], 0)

        development_app = dict(manifest["app"])
        release_app = dict(release["app"])
        development_app.pop("version")
        development_app.pop("release_serial")
        release_app.pop("version")
        release_app.pop("release_serial")
        self.assertEqual(development_app, release_app)

        self.assertEqual({k: v for k, v in manifest.items() if k != "app"},
                         {k: v for k, v in release.items() if k != "app"})
        self.assertEqual((self.source / "manifest.toml.in").read_text(), self.template)

    def test_development_version_requires_marker_and_length_limit(self):
        for version in ("2026.1.14cd415", "", "x-fre3nder.0." + "a" * 128):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "valid --version"):
                    self.render_manifest(self.source, self.fingerprint, develop=True, version=version)

    def test_normal_build_rejects_template_serial_zero(self):
        (self.source / "manifest.toml.in").write_text(
            self.template.replace("release_serial = 1", "release_serial = 0")
        )
        with self.assertRaisesRegex(ValueError, "manifest release_serial is invalid"):
            self.render_manifest(self.source, self.fingerprint)

    def test_development_requires_unambiguous_app_fields(self):
        for text in (
            self.template.replace("[app]", "[app]\n[app]"),
            self.template.replace("version = \"1.0.0-fre3nder.1\"", ""),
            self.template.replace("release_serial = 1", ""),
        ):
            with self.subTest(text=text):
                (self.source / "manifest.toml.in").write_text(text)
                with self.assertRaises(ValueError):
                    self.render_manifest(
                        self.source, self.fingerprint, develop=True,
                        version="2026.1.14cd415-fre3nder.0.fd679a9",
                    )


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
