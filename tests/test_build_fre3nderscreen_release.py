#!/usr/bin/env python3
"""Wrapper fixtures only: no target build, package construction, keys, or signing."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/build-fre3nderscreen-release"

FAKE_COMMAND = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with Path(os.environ["FIXTURE_CALLS"]).open("a") as log:
    log.write(json.dumps({"command": command, "args": sys.argv[1:],
                          "cwd": str(Path.cwd())}) + "\\n")
if command == "prepare-fre3nderscreen":
    assert sys.argv[1] == "--artifact" and len(sys.argv) == 3
    artifact = Path(sys.argv[2])
    assert artifact.is_dir()
    payload = Path("apps/fre3nderscreen/payload")
    assert not payload.exists(), "old payload was not removed"
    rc = int(os.environ.get("FIXTURE_PREPARE_RC", "0"))
    if (artifact / "mode").read_text() != "release":
        rc = 31
    if rc:
        sys.exit(rc)
    payload.mkdir()
    (payload / "new").write_text("imported fixture")
else:
    assert sys.argv[2] == "--key" and len(sys.argv) == 4
    rc = int(os.environ.get("FIXTURE_BUILD_RC", "0"))
    if rc:
        sys.exit(rc)
    output = Path(os.environ["FIXTURE_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    kind = os.environ.get("FIXTURE_OUTPUT_KIND", "file")
    if kind == "file":
        output.write_bytes(b"plain fixture bytes, not a package")
    elif kind == "symlink":
        output.symlink_to(Path(os.environ["FIXTURE_SENTINEL"]) / "keep")
    elif kind == "directory":
        output.mkdir()
    if kind != "empty":
        print(output)
'''


class ReleaseWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "recipe repo"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        self.wrapper = scripts / WRAPPER.name
        shutil.copyfile(WRAPPER, self.wrapper)
        self.wrapper.chmod(0o755)
        for name in ("prepare-fre3nderscreen", "build-fre3app"):
            command = scripts / name
            command.write_text(FAKE_COMMAND)
            command.chmod(0o755)
        self.recipe = self.repo / "apps/fre3nderscreen"
        self.recipe.mkdir(parents=True)
        (self.recipe / "manifest.toml.in").write_text("fixture manifest\n")
        self.payload = self.recipe / "payload"
        self.artifact = self.root / "artifact dir"
        self.artifact.mkdir()
        (self.artifact / "mode").write_text("release")
        self.key = self.root / "private key not read.pem"
        self.caller = self.root / "caller dir"
        self.caller.mkdir()
        self.log = self.root / "calls.jsonl"
        self.output = self.repo / "dist/custom output.fixture"
        self.sentinel = self.root / "outside"
        self.sentinel.mkdir()
        (self.sentinel / "keep").write_text("untouched")
        self.env = dict(os.environ, FIXTURE_CALLS=str(self.log),
                        FIXTURE_OUTPUT=str(self.output), FIXTURE_SENTINEL=str(self.sentinel))

    def run_wrapper(self, args=None, **env):
        if args is None:
            args = ["--artifact", str(self.artifact), "--key", str(self.key)]
        return subprocess.run([str(self.wrapper), *args], cwd=self.caller,
                              env=dict(self.env, **env), capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_required_options(self):
        for args, missing in ((["--key", str(self.key)], "--artifact"),
                              (["--artifact", str(self.artifact)], "--key")):
            with self.subTest(missing=missing):
                result = self.run_wrapper(args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing + " is required", result.stderr)
                self.assertEqual(self.calls(), [])

    def test_replaces_payload_and_preserves_outside_symlink_target(self):
        self.payload.mkdir()
        (self.payload / "old").write_text("old generated payload")
        (self.payload / "outside").symlink_to(self.sentinel, target_is_directory=True)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.payload.iterdir()), [self.payload / "new"])
        self.assertEqual((self.sentinel / "keep").read_text(), "untouched")

    def test_prepare_failure_stops_before_builder(self):
        result = self.run_wrapper(FIXTURE_PREPARE_RC="17")
        self.assertEqual(result.returncode, 17)
        self.assertEqual([call["command"] for call in self.calls()], ["prepare-fre3nderscreen"])
        self.assertNotIn("PASS", result.stdout)

    def test_development_artifact_is_rejected_by_importer(self):
        (self.artifact / "mode").write_text("development")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 31)
        self.assertEqual([call["command"] for call in self.calls()], ["prepare-fre3nderscreen"])

    def test_builder_failure_is_propagated(self):
        result = self.run_wrapper(FIXTURE_BUILD_RC="23")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(len(self.calls()), 2)
        self.assertNotIn("PASS", result.stdout)

    def test_pass_path_checksum_and_command_arguments(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        sha256 = hashlib.sha256(self.output.read_bytes()).hexdigest()
        self.assertIn("=== Fre3nderScreen release package: PASS ===", result.stdout)
        self.assertIn(f"Artifact: {self.artifact}\n", result.stdout)
        self.assertIn(f"Package:  {self.output}\n", result.stdout)
        self.assertIn(f"SHA256:   {sha256}\n", result.stdout)
        self.assertEqual(self.calls(), [
            {"command": "prepare-fre3nderscreen", "args": ["--artifact", str(self.artifact)],
             "cwd": str(self.repo)},
            {"command": "build-fre3app", "args": [str(self.recipe), "--key", str(self.key)],
             "cwd": str(self.repo)},
        ])
        self.assertFalse(self.key.exists())

    def test_relative_inputs_and_builder_output(self):
        result = self.run_wrapper(
            ["--artifact", "../artifact dir", "--key", "../private key not read.pem"],
            FIXTURE_OUTPUT="dist/different name.fixture",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(self.calls()[0]["args"][1]).resolve(), self.artifact)
        self.assertEqual(Path(self.calls()[1]["args"][2]).resolve(), self.key)
        self.assertIn(f"Package:  {self.repo}/dist/different name.fixture\n", result.stdout)

    def test_unexpected_payload_file_is_preserved(self):
        self.payload.write_text("unexpected file")
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.payload.read_text(), "unexpected file")
        self.assertEqual(self.calls(), [])

    def test_payload_symlinks_are_rejected(self):
        for target in (self.sentinel, self.root / "missing"):
            with self.subTest(target=target):
                self.payload.symlink_to(target, target_is_directory=True)
                result = self.run_wrapper()
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(self.payload.is_symlink())
                self.assertEqual(self.calls(), [])
                self.payload.unlink()
        self.assertTrue((self.sentinel / "keep").is_file())

    def test_symlinked_recipe_boundaries_are_rejected(self):
        for directory in (self.recipe, self.repo / "apps"):
            with self.subTest(directory=directory):
                moved = self.root / "moved"
                directory.rename(moved)
                directory.symlink_to(moved, target_is_directory=True)
                result = self.run_wrapper()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
                self.assertTrue(directory.is_symlink())
                directory.unlink()
                moved.rename(directory)

    def test_invalid_package_outputs_fail_closed(self):
        for kind in ("missing", "empty", "symlink", "directory"):
            with self.subTest(kind=kind):
                result = self.run_wrapper(FIXTURE_OUTPUT_KIND=kind)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("PASS", result.stdout)
                if self.output.is_symlink():
                    self.output.unlink()
                elif self.output.is_dir():
                    self.output.rmdir()


if __name__ == "__main__":
    unittest.main()
