"""Offline checks for the minimal Doom recipe. Never builds or deploys."""

import importlib.machinery
import importlib.util
from unittest import mock
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "apps/doom/scripts/build-doom"
loader = importlib.machinery.SourceFileLoader("build_doom", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
build_doom = importlib.util.module_from_spec(spec)
loader.exec_module(build_doom)


class DoomRecipeTests(unittest.TestCase):
    def test_manifest_display_not_autostart(self):
        import tomllib
        manifest = tomllib.loads((ROOT / "apps/doom/manifest.toml.in").read_text())
        self.assertEqual(manifest["display"], {"frontend": True, "api": 1})
        self.assertEqual(manifest["target"]["arch"], "mipsel")
        self.assertFalse(manifest["runtime"]["autostart"])

    def test_staging_is_explicit_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            upstream = base / "upstream"
            source = upstream / "doomgeneric"
            source.mkdir(parents=True)
            (upstream / "LICENSE").write_text("GPLv2 test fixture")
            (source / "Makefile.linuxvt").write_text(
                "SRC_DOOM = doomgeneric.o doomgeneric_linuxvt.o i_video.o\n")
            (source / "doomgeneric.c").write_text("/* fixture */\n")
            (source / "doomgeneric.h").write_text("/* fixture */\n")
            stage = base / "staged"
            stage.mkdir()
            items = build_doom.stage_package(source, stage, with_wads=False)
            self.assertIn("doomgeneric_fre3nder.o", items)
            self.assertNotIn("doomgeneric_linuxvt.o", items)
            self.assertTrue((stage / "source/doomgeneric/doomgeneric_fre3nder.c").is_file())
            self.assertFalse(any(x.suffix.lower() == ".wad" for x in stage.rglob("*")))
            self.assertFalse(any(x.parts[-1] == "local" for x in stage.rglob("*")))

    def test_first_clone_checks_out_pinned_head(self):
        info = build_doom.upstream_info()
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory) / "upstream"
            source = repo / "doomgeneric"
            (repo / ".git").mkdir(parents=True)
            source.mkdir()
            (source / "Makefile.linuxvt").write_text("SRC_DOOM = doomgeneric_linuxvt.o\n")
            (repo / "LICENSE").write_text("GPLv2 test fixture\n")
            commands = []

            def fake_run(*args, cwd=None):
                commands.append(args)
                if args[:3] == ("git", "rev-parse", "HEAD"):
                    return info["commit"]
                return ""

            with mock.patch.object(build_doom, "run", side_effect=fake_run):
                self.assertEqual(build_doom.obtain_source(repo, info), source)
            self.assertIn(("git", "checkout", "--detach", info["commit"]), commands)
            self.assertFalse(any(cmd[:2] == ("git", "fetch") for cmd in commands))

    def test_wad_staging_included_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            iwads = root / "iwads"
            iwads.mkdir()
            first = b"IWAD" + (0).to_bytes(4, "little") * 2
            second = b"IWAD" + (1).to_bytes(4, "little") * 2
            (iwads / "DOOM.WAD").write_bytes(first)
            (iwads / "DOOM2.WAD").write_bytes(second)
            # This is not on the explicit allowlist and must be ignored.
            (iwads / "private.txt").write_text("private data")
            stage = root / "stage"
            stage.mkdir()
            included = build_doom.stage_private_iwads(iwads, stage)
            self.assertEqual(included, ["DOOM.WAD", "DOOM2.WAD"])
            self.assertEqual((stage / "payload/iwads/DOOM.WAD").read_bytes(), first)
            self.assertEqual((stage / "payload/iwads/DOOM2.WAD").read_bytes(), second)
            self.assertFalse((stage / "payload/iwads/private.txt").exists())

    def test_private_wad_staging_rejects_missing_invalid_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            iwads = root / "iwads"
            iwads.mkdir()
            stage = root / "stage"
            stage.mkdir()
            with self.assertRaisesRegex(ValueError, "no supported IWADs"):
                build_doom.stage_private_iwads(iwads, stage)
            (iwads / "DOOM.WAD").write_bytes(b"PWAD" + b"\0" * 8)
            with self.assertRaisesRegex(ValueError, "not an IWAD"):
                build_doom.stage_private_iwads(iwads, stage)
            (iwads / "DOOM.WAD").unlink()
            (iwads / "DOOM.WAD").symlink_to("absent.wad")
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                build_doom.stage_private_iwads(iwads, stage)

    def test_development_package_flags(self):
        stage = pathlib.Path("/tmp/fre3nder-stage")
        key = pathlib.Path("/tmp/development-signing-key.pem")
        cmd = build_doom.package_command(stage, key, None, True, None,
                                         with_wads=True)
        self.assertEqual(cmd[cmd.index("--version") + 1],
                         "0.1.0-fre3nder.0.1")
        self.assertIn("--develop", cmd)
        self.assertIn("with-wads-x2000.fre3app", cmd[-1])
        other = build_doom.package_command(stage, key, None, True,
                   "0.1.0-fre3nder.0.2", with_wads=False)
        self.assertEqual(other[other.index("--version") + 1],
                         "0.1.0-fre3nder.0.2")
        self.assertIn("without-wads-x2000.fre3app", other[-1])
        self.assertNotIn("--develop", build_doom.package_command(
            stage, key, None, False, None, with_wads=False))
        with self.assertRaisesRegex(ValueError, "requires --develop"):
            build_doom.package_command(stage, key, None, False,
                                       "0.1.0-fre3nder.0.2", with_wads=True)

    def test_upstream_pin(self):
        info = build_doom.upstream_info()
        self.assertEqual(len(info["commit"]), 40)
        self.assertEqual(info["source_subdirectory"], "doomgeneric")

    def test_prepare_only_stages_sources_without_a_key_or_real_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            app = base / "recipe"
            for name in ("manifest.toml.in", "service", "upstream.json", "licenses/UPSTREAM",
                         "src/doomgeneric_fre3nder.c"):
                target = app / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "apps/doom" / name, target)
            upstream = base / "upstream"
            source = upstream / "doomgeneric"
            source.mkdir(parents=True)
            (upstream / "LICENSE").write_text("GPL fixture\n")
            (source / "Makefile.linuxvt").write_text("SRC_DOOM = doomgeneric.o doomgeneric_linuxvt.o\n")
            (source / "doomgeneric.c").write_text("/* fixture */\n")
            buildroot = base / "buildroot"
            for name in ("gcc", "readelf"):
                tool = buildroot / "host/bin" / f"mipsel-buildroot-linux-gnu-{name}"
                tool.parent.mkdir(parents=True, exist_ok=True)
                tool.write_text("not an executable\n")
            output = base / "package"

            def fake_make(*args, **kwargs):
                self.assertEqual(args[0], "make")
                binary = next(arg.removeprefix("OUTPUT=") for arg in args if arg.startswith("OUTPUT="))
                pathlib.Path(binary).write_bytes(b"fixture binary")
                return ""

            with mock.patch.object(build_doom, "APP", app), \
                    mock.patch.object(build_doom, "ensure_git_ignore"), \
                    mock.patch.object(build_doom, "obtain_source", return_value=source), \
                    mock.patch.object(build_doom, "check_binary"), \
                    mock.patch.object(build_doom, "run", side_effect=fake_make) as run, \
                    mock.patch.object(sys, "argv", ["build-doom", "--prepare-only", "--without-wads",
                        "--buildroot-output", str(buildroot), "--package-output", str(output),
                        "--key", str(base / "nonexistent-key")]):
                self.assertEqual(build_doom.main(), 0)
                run.assert_called_once()
            self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}, {
                "manifest.toml.in", "service", "upstream.json", "licenses/UPSTREAM", "licenses/LICENSE.doomgeneric",
                "payload/bin/doom", "source/doomgeneric/Makefile.linuxvt", "source/doomgeneric/doomgeneric.c",
                "source/doomgeneric/doomgeneric_fre3nder.c",
            })




class DoomServiceTests(unittest.TestCase):
    def test_missing_iwad_fails_and_uninstall_preserves_data(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            runtime = base / "runtime"
            binary = runtime / "payload/bin/doom"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            data = base / "data"
            env = dict(os.environ,
                       FRE3NDER_APP_RUNTIME_DIR=str(runtime),
                       FRE3NDER_APP_DATA_DIR=str(data),
                       FRE3NDER_DISPLAY_API="1",
                       FRE3NDER_DISPLAY_VT="/dev/tty7",
                       FRE3NDER_DISPLAY_FRAMEBUFFER="/dev/fb0",
                       FRE3NDER_DISPLAY_INPUT="/dev/input/event0")
            service = str(ROOT / "apps/doom/service")
            subprocess.run([service, "install"], env=env, check=True)
            wad = data / "iwads/DOOM.WAD"
            wad.write_bytes(b"example private contents")
            subprocess.run([service, "uninstall"], env=env, check=True)
            self.assertEqual(wad.read_bytes(), b"example private contents")
            wad.unlink()
            missing = subprocess.run([service, "start"], env=env, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing readable IWAD", missing.stderr)

# Exercise the service's IWAD resolution without starting the real Doom engine.
class DoomWadSelectionTests(unittest.TestCase):
    def test_bundled_iwad_and_persistent_override(self):
        import os
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            runtime = root / "runtime"
            binary = runtime / "payload/bin/doom"
            binary.parent.mkdir(parents=True)
            data = root / "data"
            binary.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$@" > "$FRE3NDER_APP_DATA_DIR/arguments"\n'
                'exit 0\n'
            )
            binary.chmod(0o755)
            bundled = runtime / "payload/iwads/DOOM.WAD"
            bundled.parent.mkdir(parents=True)
            bundled.write_bytes(b"IWAD" + b"\\0" * 8)
            env = dict(os.environ,
                       FRE3NDER_APP_RUNTIME_DIR=str(runtime),
                       FRE3NDER_APP_DATA_DIR=str(data),
                       FRE3NDER_DISPLAY_API="1",
                       FRE3NDER_DISPLAY_VT="/dev/tty7",
                       FRE3NDER_DISPLAY_FRAMEBUFFER="/dev/fb0",
                       FRE3NDER_DISPLAY_INPUT="/dev/input/event0")
            service = str(ROOT / "apps/doom/service")
            subprocess.run([service, "install"], env=env, check=True)
            # Fake program terminates immediately. A failed health check is
            # expected, but its argument file proves the selected IWAD path.
            subprocess.run([service, "start"], env=env, capture_output=True)
            selected = (data / "arguments").read_text().splitlines()
            self.assertEqual(selected[selected.index("-iwad") + 1], str(bundled))
            private = data / "iwads/DOOM.WAD"
            private.write_bytes(b"IWAD" + b"\\0" * 8)
            (data / "arguments").unlink()
            subprocess.run([service, "start"], env=env, capture_output=True)
            selected = (data / "arguments").read_text().splitlines()
            self.assertEqual(selected[selected.index("-iwad") + 1], str(private))
if __name__ == "__main__":
    unittest.main()
