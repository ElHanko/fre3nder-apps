#!/usr/bin/env python3
"""Development wrapper fixtures; no keys, packages, builds or signing."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/build-fre3nderscreen-development"
SOURCE_RELEASE = "2026.2.14cd415"
APPS_COMMIT = "4796448"
FAKE_COMMAND = f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import runpy
import sys
import tomllib

command = Path(sys.argv[0]).name
with Path(os.environ["FIXTURE_LOG"]).open("a") as log:
    log.write(json.dumps({"command": command, "args": sys.argv[1:]}) + "\\n")
if command == "prepare-fre3nderscreen":
    assert sys.argv[1:3] == ["--develop", "--artifact"]
    rc = int(os.environ.get("FIXTURE_PREPARE_RC", "0"))
    if rc:
        sys.exit(rc)
    artifact = Path(sys.argv[3])
    if (artifact / "mode").read_text() != "development":
        sys.exit(31)
    payload = Path.cwd() / "apps/fre3nderscreen/payload"
    assert not payload.exists()
    payload.mkdir()
    (payload / "artifact-manifest.json").write_bytes((artifact / "artifact-manifest.json").read_bytes())
else:
    assert sys.argv[4:6] == ["--develop", "--version"]
    rc = int(os.environ.get("FIXTURE_BUILD_RC", "0"))
    if rc:
        sys.exit(rc)
    # Use only the real in-memory manifest renderer, never build() or signing.
    builder = runpy.run_path(os.environ["FIXTURE_REAL_BUILDER"])
    app = tomllib.loads(builder["render_manifest"](Path(sys.argv[1]), "a" * 64,
                        develop=True, version=sys.argv[6]).decode())["app"]
    Path(os.environ["FIXTURE_APP"]).write_text(json.dumps(app))
    output = Path(os.environ["FIXTURE_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    kind = os.environ.get("FIXTURE_OUTPUT_KIND", "file")
    if kind == "file":
        output.write_bytes(b"plain fixture bytes, not a package")
    elif kind == "symlink":
        output.symlink_to(os.environ["FIXTURE_OUTSIDE"])
    elif kind == "directory":
        output.mkdir()
    if kind != "empty":
        print(output)
    if kind == "multiple":
        print(output)
'''

FAKE_GIT = f"#!{sys.executable}\n" + '''
import os
import sys

args = sys.argv[3:]
if args == ["rev-parse", "--short=7", "HEAD"]:
    print("4796448")
else:
    assert args in (["diff", "--quiet", "--"], ["diff", "--cached", "--quiet", "--"])
    state = "staged" if "--cached" in args else "unstaged"
    sys.exit(1 if os.environ.get("FIXTURE_DIRTY") == state else 0)
'''


class DevelopmentWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "apps repo"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        self.wrapper = scripts / WRAPPER.name
        shutil.copyfile(WRAPPER, self.wrapper)
        self.wrapper.chmod(0o755)
        for name in ("prepare-fre3nderscreen", "build-fre3app"):
            path = scripts / name
            path.write_text(FAKE_COMMAND)
            path.chmod(0o755)
        self.recipe = self.repo / "apps/fre3nderscreen"
        self.recipe.mkdir(parents=True)
        shutil.copyfile(ROOT / "apps/fre3nderscreen/manifest.toml.in", self.recipe / "manifest.toml.in")
        self.payload = self.recipe / "payload"
        self.artifact = self.root / "artifact dir"
        self.artifact.mkdir()
        (self.artifact / "mode").write_text("development")
        (self.artifact / "artifact-manifest.json").write_text(json.dumps({"source": {"release": SOURCE_RELEASE}}))
        self.key = self.root / "key path not read.pem"
        self.output = self.repo / "dist/custom output.fixture"
        self.log = self.root / "calls.jsonl"
        self.app = self.root / "app.json"
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "keep").write_text("untouched")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        git = self.bin / "git"
        git.write_text(FAKE_GIT)
        git.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        FIXTURE_LOG=str(self.log), FIXTURE_OUTPUT=str(self.output), FIXTURE_APP=str(self.app),
                        FIXTURE_REAL_BUILDER=str(ROOT / "scripts/build-fre3app"), FIXTURE_OUTSIDE=str(self.outside))

    def run_wrapper(self, args=None, **env):
        if args is None:
            args = ["--artifact", str(self.artifact), "--key", str(self.key)]
        return subprocess.run([str(self.wrapper), *args], cwd=self.root,
                              env=dict(self.env, **env), capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_development_version_serial_path_and_checksum(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        version = SOURCE_RELEASE + "-fre3nder.0." + APPS_COMMIT
        self.assertEqual(self.calls(), [
            {"command": "prepare-fre3nderscreen", "args": ["--develop", "--artifact", str(self.artifact)]},
            {"command": "build-fre3app", "args": [str(self.recipe), "--key", str(self.key), "--develop", "--version", version]},
        ])
        app = json.loads(self.app.read_text())
        self.assertEqual(app["version"], version)
        self.assertEqual(app["release_serial"], 0)
        self.assertIn("=== Fre3nderScreen development package: PASS ===", result.stdout)
        self.assertEqual(result.stdout.count("Package:  "), 1)
        self.assertIn(f"Package:  {self.output}\n", result.stdout)
        self.assertIn("SHA256:   " + hashlib.sha256(self.output.read_bytes()).hexdigest() + "\n", result.stdout)
        self.assertFalse(self.key.exists())

    def test_release_artifact_is_rejected_before_packaging(self):
        (self.artifact / "mode").write_text("release")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 31)
        self.assertEqual(len(self.calls()), 1)
        self.assertNotIn("PASS", result.stdout)

    def test_required_options(self):
        for args in (["--key", str(self.key)], ["--artifact", str(self.artifact)], ["--develop"]):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_wrapper(args).returncode, 0)
                self.assertEqual(self.calls(), [])

    def test_tracked_dirty_stops_before_cleanup_and_import(self):
        self.payload.mkdir()
        (self.payload / "keep").write_text("old payload")
        for state in ("staged", "unstaged"):
            with self.subTest(state=state):
                result = self.run_wrapper(FIXTURE_DIRTY=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("tracked worktree changes", result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual((self.payload / "keep").read_text(), "old payload")

    def test_untracked_output_and_existing_payload_are_allowed(self):
        (self.repo / "untracked.fixture").write_text("untracked")
        self.payload.mkdir()
        (self.payload / "old").write_text("old")
        (self.payload / "outside").symlink_to(self.outside, target_is_directory=True)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.payload.iterdir()), [self.payload / "artifact-manifest.json"])
        self.assertEqual((self.outside / "keep").read_text(), "untouched")

    def test_unsafe_payload_and_recipe_boundary_are_preserved(self):
        self.payload.write_text("unexpected")
        self.assertNotEqual(self.run_wrapper().returncode, 0)
        self.assertEqual(self.payload.read_text(), "unexpected")
        self.payload.unlink()
        for path in (self.payload, self.recipe, self.repo / "apps"):
            with self.subTest(path=path):
                saved = self.root / "saved"
                existed = path.exists()
                if existed:
                    path.rename(saved)
                path.symlink_to(saved if existed else self.outside, target_is_directory=True)
                self.assertNotEqual(self.run_wrapper().returncode, 0)
                self.assertEqual(self.calls(), [])
                self.assertTrue(path.is_symlink())
                path.unlink()
                if existed:
                    saved.rename(path)

    def test_child_errors_never_report_pass(self):
        for env, rc, count in (({"FIXTURE_PREPARE_RC": "17"}, 17, 1),
                               ({"FIXTURE_BUILD_RC": "23"}, 23, 2)):
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(**env)
                self.assertEqual(result.returncode, rc)
                self.assertEqual(len(self.calls()), count)
                self.assertNotIn("PASS", result.stdout)

    def test_invalid_package_output_has_no_pass(self):
        for kind in ("missing", "empty", "multiple", "symlink", "directory"):
            with self.subTest(kind=kind):
                result = self.run_wrapper(FIXTURE_OUTPUT_KIND=kind)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("PASS", result.stdout)
                if self.output.is_dir() and not self.output.is_symlink():
                    self.output.rmdir()
                else:
                    self.output.unlink(missing_ok=True)

    def test_relative_arguments_and_builder_path_are_normalized(self):
        result = self.run_wrapper(["--artifact", "artifact dir", "--key", "key path not read.pem"],
                                  FIXTURE_OUTPUT="dist/relative.fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Package:  {self.repo}/dist/relative.fixture\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
