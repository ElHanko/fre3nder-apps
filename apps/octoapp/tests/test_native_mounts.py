"""Native wrapper mount fixtures; Docker and readelf are synthetic executables."""

import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PLATFORM = ROOT.parent / 'fre3nder'


class NativeMountTests(unittest.TestCase):
    def setUp(self):
        fixture = PLATFORM / 'tests/test_x2000_mounts.py'
        if not fixture.is_file():
            self.skipTest('coordinated platform mount fixtures are unavailable')
        self.fixtures = runpy.run_path(str(fixture))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.fixtures['make_project'](self.base)
        self.env = self.fixtures['docker_environment'](self.base)
        self.buildroot = self.project / 'local/production/work/x2000/buildroot-output-fre3nder'
        self.buildroot.mkdir(parents=True)
        (self.buildroot / 'Makefile').write_text('# fixture\n')
        readelf = self.buildroot / 'host/bin/mipsel-buildroot-linux-gnu-readelf'
        readelf.parent.mkdir(parents=True)
        readelf.write_text('#!/bin/sh\nprintf "%s\\n" "ELF32 little endian o32 mips32r2 nan2008" '
                           '"ISA: MIPS32r2" "FP ABI: Hard float (32-bit CPU, Any FPU)"\n')
        readelf.chmod(0o755)
        package = self.buildroot / 'build/python-pycryptodomex-3.21.0'
        extension = package / 'build/lib.fixture/Cryptodome/fixture.so'
        extension.parent.mkdir(parents=True)
        extension.write_bytes(b'not a real ELF')
        (package / 'LICENSE.rst').write_text('fixture license')
        copyright_file = package / 'Doc/LEGAL/COPYRIGHT.pycrypto'
        copyright_file.parent.mkdir(parents=True)
        copyright_file.write_text('fixture copyright')

    def run_native(self, buildroot=None):
        return subprocess.run([str(ROOT / 'apps/octoapp/scripts/build-octoapp-native'),
                               '--buildroot-output', str(buildroot or self.buildroot),
                               '--output', str(self.base / 'native-output')],
                              env=self.env, capture_output=True, text=True)

    def calls(self):
        path = Path(self.env['MOUNT_TEST_LOG'])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_native_targets_receive_only_sanitized_project_inputs(self):
        result = self.run_native()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.fixtures['check_mounts'](self, self.project, calls)
        runs = [call for call in calls if call['args'][0] == 'run']
        self.assertEqual([call['args'][-1] for call in runs],
                         ['python-pycryptodomex-source', 'python-pycryptodomex-build'])
        self.assertNotIn('--network', runs[0]['args'])
        self.assertIn('--network', runs[1]['args'])
        self.assertIn('none', runs[1]['args'])
        self.assertIn('NATIVE=PASS', result.stdout)

    def test_override_cannot_mount_the_whole_project_as_work(self):
        for name in ('buildroot-output-fre3nder', 'local/production/keys/apps/buildroot-output-fre3nder'):
            with self.subTest(name=name):
                broad = self.project / name
                shutil.copytree(self.buildroot, broad)
                result = self.run_native(broad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must not contain the project or production keys', result.stderr)
                self.assertEqual(self.calls(), [])

    def test_missing_snapshot_tool_has_no_full_project_fallback(self):
        (self.project / 'scripts/x2000-build-input-sha256').unlink()
        result = self.run_native()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('snapshot tool is missing', result.stderr)
        self.assertFalse(any(call['args'][0] == 'run' for call in self.calls()))


if __name__ == '__main__':
    unittest.main()
