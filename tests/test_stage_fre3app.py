"""Offline package-source fixtures; no production inputs or signing keys."""

from pathlib import Path
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
staging = runpy.run_path(str(ROOT / "scripts/stage_fre3app.py"))
package_stage = staging["package_stage"]


class PackageSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.recipe = self.root / "recipe"
        shutil.copytree(ROOT / "apps/dummy", self.recipe)
        self.output = self.root / "package"

    def prepare(self, files=()):
        with package_stage(self.recipe, self.output, files=files) as stage:
            shutil.copytree(self.recipe / "payload", stage / "payload", symlinks=True)

    def members(self):
        return {p.relative_to(self.output).as_posix() for p in self.output.rglob("*") if p.is_file()}

    def test_only_explicit_files_and_payload_are_copied(self):
        for name in ("scripts/tool", "tests/test_recipe.py", "local/private.txt",
                     "__pycache__/recipe.pyc", ".git/config", "README.md", ".env",
                     "licenses/not-selected.txt", "private.pem"):
            path = self.recipe / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("excluded fixture")
        (self.recipe / "licenses/required.txt").write_bytes(b"license\r\n")
        (self.recipe / "upstream.json").write_text('{"commit":"fixture"}\n')
        self.prepare(("licenses/required.txt", "upstream.json"))
        self.assertEqual(self.members(), {
            "manifest.toml.in", "service", "payload/message.txt",
            "licenses/required.txt", "upstream.json",
        })
        for name in self.members():
            self.assertEqual((self.output / name).read_bytes(), (self.recipe / name).read_bytes())

    def test_dummy_cli_needs_no_signing_tools_or_key(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/stage_fre3app.py"), str(self.recipe), "--output", str(self.output)],
            env=dict(os.environ, PATH=""), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.members(), {"manifest.toml.in", "service", "payload/message.txt"})

    def test_private_key_header_mentioned_in_source_is_not_key_material(self):
        path = self.recipe / "payload/key.py"
        path.write_bytes(b'The file starts with "-----BEGIN ' + b'RSA PRIVATE KEY-----".\n')
        self.prepare()
        self.assertEqual((self.output / "payload/key.py").read_bytes(), path.read_bytes())

    def test_failed_preparation_preserves_previous_source(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "fixture failure"):
            with package_stage(self.recipe, self.output):
                raise ValueError("fixture failure")
        self.assertEqual(self.members(), {"manifest.toml.in", "service", "payload/message.txt"})

    def test_selected_input_snapshot_is_staged_without_changing_recipe(self):
        original = b'{"commit":"maintained"}\n'
        selected = b'{"commit":"selected"}\n'
        (self.recipe / 'upstream.json').write_bytes(original)
        with package_stage(self.recipe, self.output, files=('upstream.json',),
                           overrides={'upstream.json': selected}) as stage:
            shutil.copytree(self.recipe / 'payload', stage / 'payload')
        self.assertEqual((self.output / 'upstream.json').read_bytes(), selected)
        self.assertEqual((self.recipe / 'upstream.json').read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'explicitly selected'):
            with package_stage(self.recipe, self.output, overrides={'service': b'changed'}):
                self.fail('undeclared override accepted')

    def test_output_cannot_replace_or_contain_inputs(self):
        self.prepare()
        for protected in (self.output / 'input.json', self.root):
            with self.subTest(protected=protected), self.assertRaisesRegex(ValueError, 'build inputs'):
                with package_stage(self.recipe, self.output, protected=(protected,)):
                    self.fail('overlapping output accepted')
        self.assertTrue((self.output / 'payload/message.txt').is_file())

    def test_private_key_snapshot_is_rejected_without_replacing_output(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'private key'):
            with package_stage(self.recipe, self.output, files=('upstream.json',),
                               overrides={'upstream.json': b'-----BEGIN ' + b'PRIVATE KEY-----\n'}) as stage:
                (stage / 'payload').mkdir()
        self.assertEqual(self.members(), {'manifest.toml.in', 'service', 'payload/message.txt'})

    def test_replacement_failure_restores_previous_source(self):
        self.prepare()
        with mock.patch.object(staging["os"], "replace", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertTrue((self.output / "payload/message.txt").is_file())

    def test_payload_cache_symlink_and_private_key_are_rejected(self):
        self.prepare()
        for name, kind in (("__pycache__/code.pyc", "cache"),
                           ("linked", "symlink"), ("private.pem", "key")):
            with self.subTest(kind=kind):
                path = self.recipe / "payload" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if kind == "symlink":
                    path.symlink_to(self.recipe / "service")
                else:
                    path.write_bytes(b"-----BEGIN " + b"PRIVATE KEY-----" if kind == "key" else b"cache")
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertEqual(self.members(), {"manifest.toml.in", "service", "payload/message.txt"})
                path.unlink()
                if kind == "cache":
                    path.parent.rmdir()

    def test_unsafe_recipe_members_and_destinations_are_rejected(self):
        for name in ("../outside", "/absolute", "nested//name", "nested\\name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.prepare((name,))
        (self.recipe / "licenses").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare(("licenses/file",))
        self.output.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare()
        self.output.unlink()
        self.output = self.recipe / "generated"
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
