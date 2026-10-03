#!/usr/bin/env python3
"""Exercise fresh installs, legacy runtime upgrades and uninstall without Wine/downloads."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'install/bs-arm64.sh'
PINS = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines()
            if line and not line.startswith('#') and '=' in line)


class InstallerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bs-arm64-install-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.instance = self.root / 'instance'
        self.artifacts = self.root / 'artifacts'
        self.cache = self.root / 'cache'
        self.prefix = self.root / 'compatdata'
        self.proton = self.root / 'proton'
        self.originals = {
            'Beat Saber.exe': b'original x64 player',
            'UnityPlayer.dll': b'original x64 engine',
            'UnityCrashHandler64.exe': b'original crash handler',
            'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll': b'original mono',
            'vcruntime140.dll': b'original x64 runtime',
            'msvcp140.dll': b'original x64 C++ library',
        }
        for name, data in self.originals.items():
            self.write(self.instance / name, data)
        self.write(self.instance / 'Beat Saber_Data/globalgamemanagers', b'1.44.1_20239')
        self.write(self.prefix / 'pfx/drive_c/windows/system32/ucrtbase.dll', b'prefix UCRT unchanged')
        self.write(self.prefix / 'pfx/user.reg', b'prefix runtime settings unchanged')
        self.write(self.proton / 'version', f'0 {PINS["PROTON_TAG"]}-arm64\n'.encode())
        for name in ('lsteamclient.so', 'wineopenxr.so'):
            self.write(self.proton / 'files/lib/wine/aarch64-unix' / name, b'unix half')
        for name in ('wine', 'wineserver'):
            p = self.proton / 'files/bin-arm64' / name
            self.write(p, b'#!/bin/sh\nexit 0\n')
            p.chmod(0o755)
        unity = self.cache / f'unity-{PINS["UNITY_VERSION"]}' / 'Variations/win_arm64_player_nondevelopment_mono'
        for name in ('WindowsPlayer.exe', 'UnityPlayer.dll', 'UnityCrashHandler64.exe',
                     'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll'):
            self.write(unity / name, b'ARM64 unity ' + name.encode())
        self.write(self.cache / f'unity-openxr-{PINS["UNITY_OPENXR_VERSION"]}/UnityOpenXR.dll', b'ARM64 XR')
        for name in ('lsteamclient_a64.dll', 'wineopenxr_a64.dll', 'steam_api64.dll',
                     'openxr_loader.dll', 'dxgi.dll', 'd3d11.dll', 'MonoPosixHelper.dll',
                     'LIV_Bridge.dll', 'ucrtbs64.dll', 'vcruntime140.dll', 'msvcp140.dll'):
            self.write(self.artifacts / name, b'new artifact ' + name.encode())
        # Any attempted download is a failure: no VC redistributable cache is supplied.
        self.bin = self.root / 'bin'
        self.write(self.bin / 'curl', b'#!/bin/sh\necho unexpected download >&2\nexit 99\n')
        (self.bin / 'curl').chmod(0o755)

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run_installer(self, command, success=True, mods=False):
        env = os.environ.copy()
        env['PATH'] = str(self.bin) + ':' + env['PATH']
        result = subprocess.run(['bash', str(INSTALLER), command, str(self.instance),
                                 '--artifacts', str(self.artifacts), '--cache', str(self.cache),
                                '--prefix', str(self.prefix), '--proton', str(self.proton)] +
                                ([] if mods else ['--no-mods']),
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=45)
        self.assertEqual(result.returncode == 0, success, result.stdout)
        return result.stdout

    def assert_prefix_unchanged(self):
        self.assertEqual((self.prefix / 'pfx/drive_c/windows/system32/ucrtbase.dll').read_bytes(),
                         b'prefix UCRT unchanged')
        self.assertEqual((self.prefix / 'pfx/user.reg').read_bytes(), b'prefix runtime settings unchanged')

    def assert_uninstalled(self):
        for name, data in self.originals.items():
            self.assertEqual((self.instance / name).read_bytes(), data, name)
        self.assertFalse((self.instance / 'ucrtbs64.dll').exists())
        self.assertFalse((self.instance / '.bs-arm64').exists())
        self.assert_prefix_unchanged()

    def test_fresh_reinstall_and_uninstall(self):
        self.run_installer('install')
        self.run_installer('install')
        for name in ('ucrtbs64.dll', 'vcruntime140.dll', 'msvcp140.dll'):
            self.assertEqual((self.instance / name).read_bytes(), (self.artifacts / name).read_bytes())
        added = (self.instance / '.bs-arm64/added').read_text().splitlines()
        self.assertEqual(added.count('ucrtbs64.dll'), 1)
        self.assert_prefix_unchanged()
        self.run_installer('uninstall')
        self.assert_uninstalled()

    def test_upgrade_retires_legacy_added_runtime(self):
        self.run_installer('install')
        state = self.instance / '.bs-arm64'
        self.write(self.instance / 'vcruntime140_1.dll', b'Microsoft ARM64 runtime')
        with (state / 'added').open('a') as f:
            f.write('vcruntime140_1.dll\n')
        # Legacy installs used Microsoft's runtime at the two existing runtime paths.
        for name in ('vcruntime140.dll', 'msvcp140.dll'):
            self.write(self.instance / name, b'Microsoft ARM64 runtime')
        self.run_installer('install')
        self.assertFalse((self.instance / 'vcruntime140_1.dll').exists())
        self.run_installer('uninstall')
        self.assert_uninstalled()

    def test_upgrade_keeps_original_runtime_backup(self):
        self.run_installer('install')
        state = self.instance / '.bs-arm64'
        self.write(state / 'backup/vcruntime140_1.dll', b'original user runtime')
        self.write(self.instance / 'vcruntime140_1.dll', b'Microsoft ARM64 runtime')
        # An installed file may have been removed before a reinstall.
        (self.instance / 'vcruntime140.dll').unlink()
        self.run_installer('install')
        self.run_installer('uninstall')
        self.assert_uninstalled()
        self.assertEqual((self.instance / 'vcruntime140_1.dll').read_bytes(), b'original user runtime')

    def test_untracked_runtime_is_preserved(self):
        self.write(self.instance / 'vcruntime140_1.dll', b'user file')
        self.run_installer('install')
        self.assertEqual((self.instance / 'vcruntime140_1.dll').read_bytes(), b'user file')
        self.run_installer('uninstall')
        self.assert_uninstalled()
        self.assertEqual((self.instance / 'vcruntime140_1.dll').read_bytes(), b'user file')

    def test_missing_runtime_fails_before_changing_instance(self):
        (self.artifacts / 'ucrtbs64.dll').unlink()
        self.run_installer('install', success=False)
        self.assertEqual((self.instance / 'Beat Saber.exe').read_bytes(), self.originals['Beat Saber.exe'])
        self.assertFalse((self.instance / '.bs-arm64').exists())

    def test_missing_prefix_fails_before_changing_instance(self):
        import shutil
        shutil.rmtree(self.prefix)
        self.run_installer('install', success=False)
        self.assertEqual((self.instance / 'Beat Saber.exe').read_bytes(), self.originals['Beat Saber.exe'])
        self.assertFalse((self.instance / '.bs-arm64').exists())

    def test_monomod_upgrade_reinstall_and_restore(self):
        for version in ('1.3.3+aa4a84749', '1.3.3-alpha.dev+aa4a84749'):
            with self.subTest(version=version):
                self.originals['winhttp.dll'] = b'original BSIPA Doorstop'
                self.originals['Libs/MonoMod.Core.dll'] = version.encode()
                for name in ('winhttp.dll', 'Libs/MonoMod.Core.dll'):
                    self.write(self.instance / name, self.originals[name])
                self.write(self.artifacts / 'winhttp.dll', b'ARM64 Doorstop')
                upstream = b'upstream MonoMod.Core 1.3.4'
                self.write(self.artifacts / 'MonoMod.Core.dll', upstream)
                self.run_installer('install', mods=True)
                self.assertEqual((self.instance / 'Libs/MonoMod.Core.dll').read_bytes(), upstream)
                output = self.run_installer('install', mods=True)
                self.assertNotIn('leaving it unchanged', output)
                self.run_installer('install')
                self.assertEqual((self.instance / 'Libs/MonoMod.Core.dll').read_bytes(), version.encode())
                self.run_installer('install', mods=True)
                self.run_installer('uninstall', mods=True)
                self.assert_uninstalled()

    def test_monomod_unrecognized_version_is_preserved(self):
        self.originals['winhttp.dll'] = b'original BSIPA Doorstop'
        self.originals['Libs/MonoMod.Core.dll'] = b'user MonoMod.Core 1.3.6'
        for name in ('winhttp.dll', 'Libs/MonoMod.Core.dll'):
            self.write(self.instance / name, self.originals[name])
        self.write(self.artifacts / 'winhttp.dll', b'ARM64 Doorstop')
        self.write(self.artifacts / 'MonoMod.Core.dll', b'upstream MonoMod.Core 1.3.4')
        self.run_installer('install', mods=True)
        self.assertEqual((self.instance / 'Libs/MonoMod.Core.dll').read_bytes(), self.originals['Libs/MonoMod.Core.dll'])
        self.run_installer('uninstall', mods=True)
        self.assert_uninstalled()


if __name__ == '__main__':
    unittest.main()
