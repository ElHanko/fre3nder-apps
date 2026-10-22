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
from unittest import mock
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
        with self.assertRaisesRegex(ValueError, "requires both --version and --release-serial"):
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


class StableManifestPolicyTests(unittest.TestCase):
    setUp = DevelopmentManifestPolicyTests.setUp

    def test_stable_override_changes_only_version_and_serial(self):
        release = tomllib.loads(self.render_manifest(self.source, self.fingerprint).decode())
        selected = tomllib.loads(self.render_manifest(
            self.source, self.fingerprint, version='2.0.0-fre3nder.5', release_serial=5).decode())
        release['app'].update(version='2.0.0-fre3nder.5', release_serial=5)
        self.assertEqual(selected, release)
        self.assertEqual((self.source / 'manifest.toml.in').read_text(), self.template)

    def test_invalid_stable_and_development_combinations(self):
        for options in (
            {'release_serial': 5}, {'version': '2.0'},
            {'version': '2.0', 'release_serial': 0},
            {'version': '2.0', 'release_serial': -1},
            {'version': '2.0', 'release_serial': True},
            {'version': '', 'release_serial': 5},
            {'version': 'x' * 129, 'release_serial': 5},
            {'version': 'bad\nversion', 'release_serial': 5},
            {'develop': True, 'version': '2-fre3nder.0.1', 'release_serial': 5},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.render_manifest(self.source, self.fingerprint, **options)


class PackageMetadataTests(unittest.TestCase):
    """Exercise archive construction with simulated crypto, without any keys."""

    def setUp(self):
        self.module = runpy.run_path(str(BUILDER))
        self.build = self.module['build']
        self.globals = self.build.__globals__
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = pathlib.Path(temp.name) / 'fixture.fre3app'

    def signature(self, *args):
        self.assertEqual(args[:3], ('pkeyutl', '-sign', '-rawin'))
        self.assertEqual(args[args.index('-inkey') + 1], 'unused-key')
        pathlib.Path(args[args.index('-out') + 1]).write_bytes(b'x' * 64)

    def package(self, **options):
        with mock.patch.dict(self.globals, publisher_fingerprint=lambda key: 'a' * 64,
                             openssl=self.signature):
            self.build(DUMMY, pathlib.Path('unused-key'), self.output, **options)
        with zipfile.ZipFile(self.output) as archive:
            manifest = tomllib.loads(archive.read('manifest.toml').decode())
            sums = archive.read('SHA256SUMS').decode().splitlines()
            self.assertEqual(archive.read('SHA256SUMS.sig'), b'x' * 64)
            for line in sums:
                digest, name = line.split('  ')
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
        return manifest

    def test_default_bytes_match_pre_override_builder(self):
        self.package()
        # Golden produced by 15ef264 with the same fixed fingerprint/signature.
        self.assertEqual(hashlib.sha256(self.output.read_bytes()).hexdigest(),
                         'f0c3e282958fdaea4d6bab2e684bf37992fc97a97a97d89e4be311cc6ed7da27')

    def test_stable_and_development_archives_use_selected_metadata(self):
        manifest = self.package(version='2.0-fre3nder.5', release_serial=5)
        self.assertEqual(manifest['app']['version'], '2.0-fre3nder.5')
        self.assertEqual(manifest['app']['release_serial'], 5)
        manifest = self.package(develop=True, version='2.0-fre3nder.0.1')
        self.assertEqual(manifest['app']['release_serial'], 0)

    def test_cli_forwards_release_metadata(self):
        with mock.patch.dict(self.module['main'].__globals__, build=mock.Mock(return_value=self.output)), \
                mock.patch('sys.argv', ['build-fre3app', str(DUMMY), '--key', 'unused-key',
                                      '--version', '2.0', '--release-serial', '5']):
            self.assertEqual(self.module['main'](), 0)
            self.module['main'].__globals__['build'].assert_called_once_with(
                DUMMY, pathlib.Path('unused-key'), None, False, '2.0', 5)

    def test_invalid_mode_is_rejected_before_key_access(self):
        with mock.patch.dict(self.globals, publisher_fingerprint=mock.Mock(side_effect=AssertionError('key accessed'))):
            with self.assertRaises(ValueError):
                self.build(DUMMY, pathlib.Path('unused-key'), self.output, version='incomplete')

    def test_unsafe_override_versions_are_rejected_before_key_access(self):
        for version in ('1/2', '1\\2', '1 2', '../escape', '/absolute',
                        '1/../../escape', '1\t2', '1\n2', '.1', '-1', '_1', '1.ä'):
            for develop in (False, True):
                selected = version + '-fre3nder.0.1' if develop else version
                options = {'develop': develop, 'version': selected}
                if not develop:
                    options['release_serial'] = 5
                with self.subTest(version=selected, develop=develop), \
                        mock.patch.dict(self.globals, publisher_fingerprint=mock.Mock(
                            side_effect=AssertionError('key accessed'))):
                    with self.assertRaises(ValueError):
                        self.build(DUMMY, pathlib.Path('unused-key'), self.output, **options)
                    self.globals['publisher_fingerprint'].assert_not_called()
                    self.assertFalse(self.output.exists())

    def test_unsafe_template_versions_are_rejected_before_key_access(self):
        import json
        source = self.output.parent / 'source'
        source.mkdir()
        template = (DUMMY / 'manifest.toml.in').read_text()
        for version in ('1/2', '1\\2', '1 2', '../escape', '/absolute', '1/../../escape'):
            (source / 'manifest.toml.in').write_text(template.replace(
                '"1.0.0-fre3nder.1"', json.dumps(version)))
            with self.subTest(version=version), \
                    mock.patch.dict(self.globals, publisher_fingerprint=mock.Mock(
                        side_effect=AssertionError('key accessed'))):
                with self.assertRaisesRegex(ValueError, 'version is invalid'):
                    self.build(source, pathlib.Path('unused-key'), self.output)
                self.globals['publisher_fingerprint'].assert_not_called()

    def test_repository_version_characters_are_accepted(self):
        for options in ({'version': 'A1.2+local_build-fre3nder.5', 'release_serial': 5},
                        {'version': 'A1.2+local_build-fre3nder.0.1', 'develop': True}):
            with self.subTest(options=options):
                self.assertEqual(self.package(**options)['app']['version'], options['version'])


class BuildFre3AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.private = self.root / "private.pem"
        self.public = self.root / "public.pem"
        self.source = self.root / "package-source"
        package_stage = runpy.run_path(str(ROOT / "scripts/stage_fre3app.py"))["package_stage"]
        with package_stage(DUMMY, self.source) as stage:
            shutil.copytree(DUMMY / "payload", stage / "payload")
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
                str(self.source),
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

    def test_staging_preserves_existing_package_bytes(self):
        staged = self.root / "staged.fre3app"
        original = self.root / "original.fre3app"
        result = self.build(staged)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            [str(BUILDER), str(DUMMY), "--key", str(self.private), "--output", str(original)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(staged.read_bytes(), original.read_bytes())

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
