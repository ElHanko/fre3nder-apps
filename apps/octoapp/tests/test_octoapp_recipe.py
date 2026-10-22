#!/usr/bin/env python3
"""Host-only OctoApp recipe checks; no network, target build, or signing key."""

import importlib.machinery
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "apps/octoapp"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class OctoAppRecipeTests(unittest.TestCase):
    def setUp(self):
        self.prepare = load(
            "prepare_octoapp_test",
            ROOT / "apps/octoapp/scripts/prepare-octoapp",
        )

    def test_pinned_manifest_and_upstream(self):
        manifest = tomllib.loads((SOURCE / "manifest.toml.in").read_text())
        self.assertEqual(
            manifest["app"],
            {
                "name": "octoapp",
                "version": "3.2.4-fre3nder.4",
                "release_serial": 4,
            },
        )
        self.assertEqual(manifest["runtime"]["autostart"], True)

        upstream = json.loads((SOURCE / "upstream.json").read_text())
        self.assertEqual(upstream["version"], "3.2.4")
        self.assertEqual(
            upstream["commit"],
            "f6d0cc21aefe77e54aa8e8674c65e911bed1a55e",
        )
        self.assertEqual(upstream["license"], "AGPL-3.0-or-later")

    def test_service_keeps_dependencies_and_updates_isolated(self):
        service = (SOURCE / "service").read_text()
        self.assertIn("include-system-site-packages = false", service)
        self.assertNotIn("OCTOAPP_DISABLE_SYSTEM_CONFIG", service)
        prepare = (ROOT / "apps/octoapp/scripts/prepare-octoapp").read_text()
        self.assertEqual(
            prepare.count(
                'system_config = destination / "moonraker_octoapp/systemconfigmanager.py"'
            ),
            1,
        )
        self.assertEqual(prepare.count("system_config.unlink()"), 1)
        self.assertNotIn(
            '(destination / "moonraker_octoapp/systemconfigmanager.py").unlink()',
            prepare,
        )
        self.assertIn('"ConfigFolder": str(state)', service)
        for forbidden in (
            "pip install",
            "git clone",
            "systemctl",
            "apt install",
            "opkg install",
            "moonraker.asvc",
            "update_manager",
        ):
            self.assertNotIn(forbidden, service)

    def test_fre3nder_patch_removes_upstream_system_writes(self):
        patch = (
            SOURCE / "patches/0001-fre3nder-disable-system-config.patch"
        ).read_text()
        self.assertNotIn("OCTOAPP_DISABLE_SYSTEM_CONFIG", patch)
        self.assertIn(
            "-from .systemconfigmanager import SystemConfigManager",
            patch,
        )
        self.assertIn(
            "-                SystemConfigManager.EnsureUpdateManagerFilesSetup",
            patch,
        )
        self.assertIn(
            "-            SystemConfigManager.EnsureAllowedServicesFile",
            patch,
        )
        self.assertIn("moonraker_octoapp/moonrakerclient.py", patch)
        self.assertIn("configured moonraker.conf path", patch)

    def test_fre3nder_patch_is_valid_unified_diff(self):
        patch = SOURCE / "patches/0001-fre3nder-disable-system-config.patch"
        result = subprocess.run(
            ["git", "apply", "--numstat", str(patch)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("moonraker_octoapp/moonrakerhost.py", result.stdout)

    def test_requirements_exclude_native_and_non_klipper_optional_packages(self):
        requirements = [
            line.strip()
            for line in (SOURCE / "requirements.in").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        joined = "\n".join(requirements)
        for expected in (
            "octowebsocket_client",
            "octoflatbuffers==24.3.27",
            "requests",
            "httpx",
            "qrcode",
        ):
            self.assertIn(expected, joined)
        for excluded in ("pillow", "pycryptodome", "paho-mqtt", "pybind11"):
            self.assertNotIn(excluded, joined.lower())

    def test_host_tools_do_not_depend_on_system_pip(self):
        lock_script = (ROOT / "apps/octoapp/scripts/lock-octoapp").read_text()
        prepare_script = (ROOT / "apps/octoapp/scripts/prepare-octoapp").read_text()
        self.assertIn('PIP_VERSION = "26.2.1"', lock_script)
        self.assertIn("PIP_SHA256 =", lock_script)
        self.assertIn('env["PYTHONPATH"]', lock_script)
        self.assertNotIn('"pip",\n        "--isolated"', prepare_script)
        self.assertIn("download_locked_wheel", prepare_script)

    def test_lock_manifest_matches_recipe_when_present(self):
        lock_path = SOURCE / "python-wheels.json"
        if not lock_path.exists():
            self.skipTest("run apps/octoapp/scripts/lock-octoapp before final validation")
        upstream = json.loads((SOURCE / "upstream.json").read_text())
        lock = json.loads(lock_path.read_text())
        self.assertEqual(
            lock["resolver"],
            {
                "name": "pip",
                "version": "26.2.1",
                "wheel_sha256": "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
            },
        )
        self.prepare.validate_inputs(upstream, lock)
        self.assertGreater(len(lock["wheels"]), 5)

    def test_dependency_tree_hash_is_deterministic_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a/one.py").write_text("one\n")
            (root / "two.txt").write_text("two\n")
            first = self.prepare.dependency_tree_hash(root)
            second = self.prepare.dependency_tree_hash(root)
            self.assertEqual(first, second)
            (root / "two.txt").write_text("changed\n")
            self.assertNotEqual(first, self.prepare.dependency_tree_hash(root))

    def test_universal_lock_cannot_replace_native_dependencies(self):
        upstream = json.loads((SOURCE / 'upstream.json').read_text())
        lock = json.loads((SOURCE / 'python-wheels.json').read_text())
        for name in ('pillow', 'pycryptodome', 'pycryptodomex'):
            selected = dict(lock, wheels=[dict(lock['wheels'][0], name=name)])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'native bundles'):
                self.prepare.validate_inputs(upstream, selected)

    def test_package_source_keeps_integration_files_without_recipe_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "package"

            def payload(destination, buildroot_output, **kwargs):
                destination.mkdir()
                (destination / "runtime.json").write_text('{"fixture":true}\n')

            with mock.patch.object(self.prepare, "prepare", side_effect=payload), \
                    mock.patch.object(sys, "argv", ["prepare-octoapp", "--buildroot-output", "unused-fixture",
                                                   "--output", str(output)]):
                self.assertEqual(self.prepare.main(), 0)
            self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}, {
                "manifest.toml.in", "service", "upstream.json", "python-wheels.json", "requirements.in",
                "native-deps.json", "patches/0001-fre3nder-disable-system-config.patch",
                "licenses/UPSTREAM", "licenses/LICENSE.octoflatbuffers", "payload/runtime.json",
            })

    def test_dependency_copy_excludes_caches_and_optional_selftests(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            (source / "__pycache__").mkdir(parents=True)
            (source / "module.py").write_text("# fixture\n")
            (source / "module.pyc").write_bytes(b"cache")
            (source / "__pycache__/module.cpython-312.pyc").write_bytes(b"cache")
            (source / "SelfTest").mkdir()
            (source / "SelfTest/key.pem").write_bytes(b"-----BEGIN " + b"PRIVATE KEY-----")
            output = Path(tmp) / "output"
            self.prepare.copy_tree_checked(source, output, exclude=("SelfTest",))
            self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()},
                             {"module.py"})

    def test_selected_source_lock_and_requirements_are_used_and_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            recipe = base / 'recipe'
            for name in ('manifest.toml.in', 'service', *self.prepare.PACKAGE_FILES):
                target = recipe / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SOURCE / name, target)
            patch = recipe / 'patches/0001-fre3nder-disable-system-config.patch'
            patch.write_text('diff --git a/moonraker_octoapp/moonrakerhost.py b/moonraker_octoapp/moonrakerhost.py\n'
                             '--- a/moonraker_octoapp/moonrakerhost.py\n+++ b/moonraker_octoapp/moonrakerhost.py\n'
                             '@@ -1 +1 @@\n-SystemConfigManager\n+# integration fixture\n')
            source = base / 'source'
            for name, data in {
                'pyproject.toml': '[project]\nname="OctoApp"\nversion="9.0.0"\n',
                'LICENSE': 'AGPL fixture\n', 'octoapp/__init__.py': '', 'linux_host/__init__.py': '',
                'moonraker_octoapp/moonrakerhost.py': 'SystemConfigManager\n',
                'moonraker_octoapp/moonrakerclient.py': '# fixture\n',
                'moonraker_octoapp/systemconfigmanager.py': '# removed\n',
                '.gitignore': 'ignored-private.txt\n',
            }.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            subprocess.run(['git', 'init', '-q', source], check=True)
            subprocess.run(['git', '-C', source, 'add', '.'], check=True)
            subprocess.run(['git', '-C', source, '-c', 'user.name=Fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            commit = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
            (source / 'ignored-private.txt').write_text('excluded local fixture')
            upstream = json.loads((SOURCE / 'upstream.json').read_text())
            upstream.update(version='9.0.0', commit=commit)
            wheels = base / 'wheels'
            wheels.mkdir()
            filename = 'testdep-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheels / filename, 'w') as archive:
                archive.writestr('testdep/__init__.py', '# fixture\n')
            lock = {'schema': 1, 'target': {'python': '3.12', 'platform': 'any', 'implementation': 'py', 'abi': 'none'},
                    'requirements': ['testdep==1.0'], 'wheels': [{'name': 'testdep', 'version': '1.0',
                    'filename': filename, 'sha256': hashlib.sha256((wheels / filename).read_bytes()).hexdigest()}]}
            selected_upstream, selected_lock, requirements = [base / name for name in ('upstream.json', 'lock.json', 'requirements.in')]
            selected_upstream.write_text(json.dumps(upstream))
            selected_lock.write_text(json.dumps(lock))
            requirements.write_text('testdep==1.0\n')
            snapshots = {p: p.read_bytes() for p in (*recipe.rglob('*'), selected_upstream, selected_lock, requirements) if p.is_file()}
            output = base / 'package'
            args = ['prepare-octoapp', '--source', str(source), '--wheel-dir', str(wheels),
                    '--buildroot-output', str(base / 'unused-buildroot'), '--upstream', str(selected_upstream),
                    '--lock', str(selected_lock), '--requirements', str(requirements), '--output', str(output)]
            with mock.patch.object(self.prepare, 'SOURCE', recipe), mock.patch.object(self.prepare, 'PATCH', patch), \
                    mock.patch.object(self.prepare, 'stage_pillow'), mock.patch.object(self.prepare, 'stage_pycryptodomex'), \
                    mock.patch.object(sys, 'argv', args):
                self.assertEqual(self.prepare.main(), 0)
                for name, path in (('upstream.json', selected_upstream), ('python-wheels.json', selected_lock), ('requirements.in', requirements)):
                    self.assertEqual((output / name).read_bytes(), path.read_bytes())
                meta = json.loads((output / 'payload/runtime.json').read_text())
                self.assertEqual((meta['app_version'], meta['upstream_commit']), ('9.0.0', commit))
                self.assertFalse((output / 'payload/app/moonraker_octoapp/systemconfigmanager.py').exists())
                self.assertEqual(snapshots, {p: p.read_bytes() for p in snapshots})
                good_stage = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
                for bad_upstream, bad_lock in (
                    (dict(upstream, commit='0' * 40), lock),
                    (dict(upstream, version='8.0.0'), lock),
                    (dict(upstream, project='other'), lock),
                    (upstream, dict(lock, requirements=['different==1.0'])),
                    (upstream, dict(lock, wheels=[dict(lock['wheels'][0], sha256='0' * 64)])),
                    (upstream, dict(lock, target={'python': '3.13'})),
                ):
                    selected_upstream.write_text(json.dumps(bad_upstream))
                    selected_lock.write_text(json.dumps(bad_lock))
                    self.assertEqual(self.prepare.main(), 1)
                    self.assertEqual(good_stage, {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()})
                selected_upstream.write_text(json.dumps(upstream))
                selected_lock.write_text(json.dumps(lock))
                patch.write_text(patch.read_text().replace('-SystemConfigManager', '-incompatible source'))
                self.assertEqual(self.prepare.main(), 1)
                self.assertEqual(good_stage, {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()})

    def test_runtime_accepts_selected_version_and_rejects_inconsistent_metadata(self):
        code = (SOURCE / 'service').read_text().split("<<'PY'\n", 1)[1].split('\ndef valid_payload', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / 'runtime'
            app = runtime / 'payload/app'
            app.mkdir(parents=True)
            upstream = json.loads((SOURCE / 'upstream.json').read_text())
            upstream.update(version='9.0.0', commit='b' * 40)
            (runtime / 'upstream.json').write_text(json.dumps(upstream))
            (app / 'pyproject.toml').write_text('[project]\nname="OctoApp"\nversion="9.0.0"\n')
            meta = {'app_version': '9.0.0', 'upstream_commit': 'b' * 40,
                    'python': '3.12', 'dependency_tree_sha256': 'a' * 64}
            path = runtime / 'payload/runtime.json'
            path.write_text(json.dumps(meta))
            with mock.patch.dict(os.environ, FRE3NDER_APP_RUNTIME_DIR=str(runtime), FRE3NDER_APP_DATA_DIR=str(Path(tmp) / 'data')):
                namespace = {}
                exec(compile(code, str(SOURCE / 'service'), 'exec'), namespace)
            self.assertEqual(namespace['metadata'](), meta)
            for fields in ({'app_version': '3.2.4'}, {'upstream_commit': 'c' * 40}, {'python': '3.13'}):
                path.write_text(json.dumps(dict(meta, **fields)))
                with self.assertRaises(SystemExit):
                    namespace['metadata']()


if __name__ == "__main__":
    unittest.main()
