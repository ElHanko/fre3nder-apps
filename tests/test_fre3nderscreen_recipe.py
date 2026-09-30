#!/usr/bin/env python3
"""Host checks for the Fre3nderScreen recipe; no cross build or signing."""

import json
import hashlib
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import textwrap
import time
import tomllib
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "apps/fre3nderscreen"
SERVICE = RECIPE / "service"
IMPORTER = ROOT / "scripts/prepare-fre3nderscreen"


class RecipeTests(unittest.TestCase):
    def test_manifest(self):
        builder = runpy.run_path(str(ROOT / "scripts/build-fre3app"))
        manifest = tomllib.loads(
            builder["render_manifest"](RECIPE, "a" * 64).decode("utf-8")
        )
        self.assertEqual(manifest["display"], {"frontend": True, "api": 1})
        self.assertEqual(manifest["runtime"], {"service": "service", "autostart": False})
        self.assertEqual(manifest["app"]["version"], "2026.1.1-fre3nder.1")
        self.assertEqual(manifest["app"]["release_serial"], 1)

    def test_payload_layout_and_modes(self):
        builder = runpy.run_path(str(ROOT / "scripts/build-fre3app"))
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "modes.zip"
            builder["write_zip"](fixture, {
                "service": b"#!/bin/sh\n",
                "payload/bin/fre3nderscreen": b"binary",
                "payload/themes/blue.json": b"{}",
            })
            with zipfile.ZipFile(fixture) as archive:
                modes = {
                    info.filename: (info.external_attr >> 16) & 0o777
                    for info in archive.infolist()
                }
        self.assertEqual(modes["service"], 0o755)
        self.assertEqual(modes["payload/bin/fre3nderscreen"], 0o755)
        self.assertEqual(modes["payload/themes/blue.json"], 0o644)
        payload = RECIPE / "payload"
        if payload.exists():
            expected = {
                "bin/fre3nderscreen",
                "artifact-manifest.json",
                "defaults/fre3nderscreen.json",
                *(f"themes/{name}.json" for name in ("blue", "green", "pink", "purple", "red", "yellow")),
            }
            actual = {path.relative_to(payload).as_posix() for path in payload.rglob("*") if path.is_file()}
            self.assertEqual(actual, expected)
        self.assertEqual(
            subprocess.run(
                ["git", "check-ignore", "-q", "apps/fre3nderscreen/payload/bin/fre3nderscreen"],
                cwd=ROOT,
            ).returncode,
            0,
        )
        default = json.loads((RECIPE / "defaults/fre3nderscreen.json").read_text())
        self.assertEqual(default["log_path"], "logs/fre3nderscreen.log")

    def test_import_release_and_reject_development_or_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "app"
            (artifact / "bin").mkdir(parents=True)
            (artifact / "themes").mkdir()
            (artifact / "licenses").mkdir()
            (artifact / "bin/fre3nderscreen").write_bytes(b"fixture binary")
            for name in ("blue", "green", "pink", "purple", "red", "yellow"):
                (artifact / "themes" / f"{name}.json").write_text("{}\n")
            for path in (RECIPE / "licenses").iterdir():
                if path.name != "UPSTREAM":
                    (artifact / "licenses" / path.name).write_bytes(path.read_bytes())
            files = {
                path.relative_to(artifact).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in artifact.rglob("*") if path.is_file()
            }
            manifest = {
                "schema": 1,
                "artifact": "fre3nderscreen-x2000-app",
                "artifact_mode": "release",
                "source": {
                    "repository": "https://example.org/fre3nderscreen.git",
                    "release": "2026.1.1",
                    "commit": "a" * 40,
                    "license": "GPL-3.0-only",
                },
                "submodules": {"lvgl": {"commit": "b" * 40, "license": "MIT"}},
                "abi": {"arch": "mipsel", "isa": "mips32r2", "float_abi": "hard", "nan": "nan2008", "linkage": "static"},
                "build_input_sha256": "c" * 64,
                "files": files,
            }

            def write_metadata():
                (artifact / "artifact-manifest.json").write_text(json.dumps(manifest) + "\n")
                (artifact / "SHA256SUMS").write_text("".join(
                    f"{hashlib.sha256((artifact / name).read_bytes()).hexdigest()}  {name}\n"
                    for name in sorted((*files, "artifact-manifest.json"))
                ))

            def import_artifact(output):
                return subprocess.run(
                    [sys.executable, str(IMPORTER), "--artifact", str(artifact), "--output", str(output)],
                    capture_output=True, text=True,
                )

            write_metadata()
            payload = root / "payload"
            self.assertEqual(import_artifact(payload).returncode, 0)
            self.assertEqual((payload / "bin/fre3nderscreen").read_bytes(), b"fixture binary")
            self.assertEqual(json.loads((payload / "artifact-manifest.json").read_text())["artifact_mode"], "release")
            self.assertEqual(import_artifact(payload).returncode, 1)
            manifest["artifact_mode"] = "development"
            write_metadata()
            rejected = root / "rejected"
            self.assertNotEqual(import_artifact(rejected).returncode, 0)
            self.assertFalse(rejected.exists())
            manifest["artifact_mode"] = "release"
            write_metadata()
            (artifact / "bin/fre3nderscreen").write_bytes(b"corrupted")
            self.assertNotEqual(import_artifact(rejected).returncode, 0)
            self.assertFalse(rejected.exists())

    def test_service_has_no_privileged_or_old_component_commands(self):
        service = SERVICE.read_text()
        self.assertNotRegex(service, r"\b(chown|chmod|mount|mknod|modprobe|sudo|pkexec)\b")
        self.assertNotIn("/opt/fre3nder/fre3nderscreen", service)
        self.assertNotIn("/home/fre3nder/.fre3nder/fre3nderscreen", service)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.data = self.root / "data"
        binary = self.runtime / "payload/bin/fre3nderscreen"
        binary.parent.mkdir(parents=True)
        (self.runtime / "payload/themes").mkdir()
        (self.runtime / "payload/defaults").mkdir()
        (self.runtime / "payload/defaults/fre3nderscreen.json").write_bytes(
            (RECIPE / "defaults/fre3nderscreen.json").read_bytes()
        )
        binary.write_text(
            f"#!{sys.executable}\n" + textwrap.dedent("""
                import json
                import os
                from pathlib import Path
                import signal
                import sys
                import time

                data = Path(os.environ["FRE3NDER_APP_DATA_DIR"])
                names = (
                    "FRE3NDERSCREEN_FRAMEBUFFER", "FRE3NDERSCREEN_INPUT",
                    "FRE3NDERSCREEN_BACKLIGHT_POWER", "FRE3NDERSCREEN_BEEPER_INPUT",
                    "FRE3NDERSCREEN_CONFIG", "FRE3NDERSCREEN_THEME_DIR",
                )
                with (data / "starts.jsonl").open("a") as output:
                    output.write(json.dumps({name: os.environ.get(name) for name in names}) + "\\n")
                signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
                while True:
                    time.sleep(0.1)
            """)
        )
        binary.chmod(0o755)
        self.env = dict(
            os.environ,
            FRE3NDER_APP_RUNTIME_DIR=str(self.runtime),
            FRE3NDER_APP_DATA_DIR=str(self.data),
            FRE3NDER_DISPLAY_API="1",
            FRE3NDER_DISPLAY_FRAMEBUFFER="/test/fb",
            FRE3NDER_DISPLAY_INPUT="/test/input",
            FRE3NDER_DISPLAY_BACKLIGHT_POWER="",
            FRE3NDER_DISPLAY_BEEPER="",
        )
        self.addCleanup(self.cleanup_process)

    def cleanup_process(self):
        pid_file = self.data / "fre3nderscreen.pid"
        if pid_file.exists():
            self.action("stop")

    def action(self, name, env=None):
        return subprocess.run(
            [str(SERVICE), name], env=env or self.env, capture_output=True, text=True
        )

    def wait_for_start(self):
        started = self.data / "starts.jsonl"
        for _ in range(50):
            if started.exists() and started.stat().st_size:
                return
            time.sleep(0.02)
        self.fail("mock Fre3nderScreen did not start")

    def test_lifecycle_mapping_and_idempotent_start(self):
        for action in ("install", "update", "restore"):
            self.assertEqual(self.action(action).returncode, 0)
        self.assertEqual(self.action("start").returncode, 0)
        self.wait_for_start()
        self.assertEqual(self.action("status").returncode, 0)
        self.assertEqual(self.action("start").returncode, 0)
        values = (self.data / "starts.jsonl").read_text().splitlines()
        self.assertEqual(len(values), 1)
        passed = json.loads(values[0])
        self.assertEqual(passed["FRE3NDERSCREEN_FRAMEBUFFER"], "/test/fb")
        self.assertEqual(passed["FRE3NDERSCREEN_INPUT"], "/test/input")
        self.assertEqual(passed["FRE3NDERSCREEN_BACKLIGHT_POWER"], "")
        self.assertEqual(passed["FRE3NDERSCREEN_BEEPER_INPUT"], "")
        self.assertEqual(passed["FRE3NDERSCREEN_CONFIG"], str(self.data / "fre3nderscreen.json"))
        self.assertEqual(passed["FRE3NDERSCREEN_THEME_DIR"], str(self.runtime / "payload/themes"))
        self.assertEqual(self.action("stop").returncode, 0)
        self.assertEqual(self.action("status").returncode, 1)
        self.assertEqual(self.action("uninstall").returncode, 0)
        self.assertTrue((self.data / "fre3nderscreen.json").exists())

    def test_missing_display_inputs_fail(self):
        for name in ("FRE3NDER_DISPLAY_API", "FRE3NDER_DISPLAY_FRAMEBUFFER", "FRE3NDER_DISPLAY_INPUT"):
            with self.subTest(name=name):
                env = self.env.copy()
                env.pop(name)
                self.assertEqual(self.action("start", env).returncode, 1)
                env[name] = ""
                self.assertEqual(self.action("start", env).returncode, 1)
        self.assertFalse((self.data / "fre3nderscreen.pid").exists())

    def test_optional_display_paths_are_forwarded(self):
        env = self.env.copy()
        env["FRE3NDER_DISPLAY_BACKLIGHT_POWER"] = "/test/backlight"
        env["FRE3NDER_DISPLAY_BEEPER"] = "/test/beeper"
        self.assertEqual(self.action("start", env).returncode, 0)
        self.wait_for_start()
        passed = json.loads((self.data / "starts.jsonl").read_text().splitlines()[0])
        self.assertEqual(passed["FRE3NDERSCREEN_BACKLIGHT_POWER"], "/test/backlight")
        self.assertEqual(passed["FRE3NDERSCREEN_BEEPER_INPUT"], "/test/beeper")

    def test_existing_config_is_preserved(self):
        self.data.mkdir()
        config = self.data / "fre3nderscreen.json"
        config.write_text('{"theme":"red"}\n')
        for action in ("install", "update", "restore"):
            self.assertEqual(self.action(action).returncode, 0)
            self.assertEqual(config.read_text(), '{"theme":"red"}\n')

    def test_stale_pid_does_not_kill_another_process(self):
        unrelated = subprocess.Popen(["sleep", "30"])
        def cleanup_unrelated():
            if unrelated.poll() is None:
                unrelated.kill()
            unrelated.wait()
        self.addCleanup(cleanup_unrelated)
        self.data.mkdir()
        (self.data / "fre3nderscreen.pid").write_text(f"{unrelated.pid}\n")
        self.assertEqual(self.action("stop").returncode, 0)
        self.assertIsNone(unrelated.poll())
        self.assertEqual(self.action("start").returncode, 0)
        self.wait_for_start()
        self.assertEqual(self.action("status").returncode, 0)
        self.assertNotEqual(int((self.data / "fre3nderscreen.pid").read_text()), unrelated.pid)


if __name__ == "__main__":
    unittest.main()
