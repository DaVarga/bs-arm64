"""install / uninstall: fresh installs, upgrades from older releases, BSIPA fixes, the checks that
must fail before the instance is changed, and prefix creation."""
import shutil
import unittest

from fixture import PINS, PROTON_TAGS, Fixture


class InstallTests(Fixture):
    def test_fresh_reinstall_and_uninstall(self):
        self.run_installer("install")
        self.run_installer("install")
        for name in ("ucrtbs64.dll", "vcruntime140.dll", "msvcp140.dll"):
            self.assertEqual((self.instance / name).read_bytes(), (self.artifacts / name).read_bytes())
        added = (self.instance / ".bs-arm64/added").read_text().splitlines()
        self.assertEqual(added.count("ucrtbs64.dll"), 1)
        self.assert_prefix_unchanged()
        self.run_installer("uninstall")
        self.assert_uninstalled()

    def test_every_tested_proton_build_is_accepted(self):
        for tag in PROTON_TAGS:
            self.set_proton(tag)
            self.run_installer("install")
            self.assertEqual((self.prefix / "pfx/drive_c/bs-arm64/proton-version").read_text().strip(),
                             f"{tag}-arm64")

    def test_untested_proton_build_fails_before_changing_instance(self):
        self.write(self.proton / "version", b"0 GE-Proton11-7\n")
        self.assertIn("Proton is GE-Proton11-7", self.run_installer("install", success=False))
        self.assertFalse((self.instance / ".bs-arm64").exists())
        self.assert_prefix_unchanged()

    def test_other_unity_engine_fails_before_changing_instance(self):
        self.write(self.instance / "Beat Saber_Data/globalgamemanagers", b"\0" + b"2022.3.33f1\0 1.40.8_7400")
        self.assertIn("Unity 2022.3.33f1", self.run_installer("install", success=False))
        self.assertFalse((self.instance / ".bs-arm64").exists())
        self.assert_prefix_unchanged()

    def test_reinstall_after_an_installed_file_was_removed(self):
        self.run_installer("install")
        (self.instance / "vcruntime140.dll").unlink()
        self.run_installer("install")
        self.run_installer("uninstall")
        self.assert_uninstalled()

    def test_missing_runtime_fails_before_changing_instance(self):
        (self.artifacts / "ucrtbs64.dll").unlink()
        self.run_installer("install", success=False)
        self.assertEqual((self.instance / "Beat Saber.exe").read_bytes(), self.originals["Beat Saber.exe"])
        self.assertFalse((self.instance / ".bs-arm64").exists())

    def test_missing_prefix_is_created_with_proton(self):
        shutil.rmtree(self.prefix)
        self.assertIn("creating the Wine prefix", self.run_installer("install"))
        self.assertTrue((self.prefix / "pfx/drive_c/bs-arm64/proton-version").is_file())

    def test_failed_prefix_creation_fails_before_changing_instance(self):
        shutil.rmtree(self.prefix)
        env = dict(self.env(), BS_TEST_PROTON_FAILS="1")
        result = self.run_cli("install", "--no-mods", env=env, success=False)
        self.assertIn("could not create the Wine prefix", result.stderr)
        self.assertEqual((self.instance / "Beat Saber.exe").read_bytes(), self.originals["Beat Saber.exe"])
        self.assertFalse((self.instance / ".bs-arm64").exists())

    def test_not_a_beat_saber_folder(self):
        (self.instance / "Beat Saber_Data/globalgamemanagers").unlink()
        self.assertIn("not a Beat Saber folder", self.run_installer("install", success=False))

    def test_monomod_upgrade_reinstall_and_restore(self):
        for version in ("1.3.3+aa4a84749", "1.3.3-alpha.dev+aa4a84749"):
            with self.subTest(version=version):
                self.originals["winhttp.dll"] = b"original BSIPA Doorstop"
                self.originals["Libs/MonoMod.Core.dll"] = version.encode()
                for name in ("winhttp.dll", "Libs/MonoMod.Core.dll"):
                    self.write(self.instance / name, self.originals[name])
                self.write(self.artifacts / "winhttp.dll", b"ARM64 Doorstop")
                upstream = b"upstream MonoMod.Core " + PINS["MONOMOD_CORE_VERSION"].encode()
                self.write(self.artifacts / "MonoMod.Core.dll", upstream)
                self.run_installer("install", mods=True)
                self.assertEqual((self.instance / "Libs/MonoMod.Core.dll").read_bytes(), upstream)
                output = self.run_installer("install", mods=True)
                self.assertNotIn("leaving it unchanged", output)
                self.run_installer("install")
                self.assertEqual((self.instance / "Libs/MonoMod.Core.dll").read_bytes(), version.encode())
                self.run_installer("install", mods=True)
                self.run_installer("uninstall", mods=True)
                self.assert_uninstalled()

    def test_monomod_unrecognized_version_is_preserved(self):
        self.originals["winhttp.dll"] = b"original BSIPA Doorstop"
        self.originals["Libs/MonoMod.Core.dll"] = b"user MonoMod.Core 1.3.6"
        for name in ("winhttp.dll", "Libs/MonoMod.Core.dll"):
            self.write(self.instance / name, self.originals[name])
        self.write(self.artifacts / "winhttp.dll", b"ARM64 Doorstop")
        self.write(self.artifacts / "MonoMod.Core.dll", b"upstream MonoMod.Core 1.3.4")
        self.assertIn("leaving it unchanged", self.run_installer("install", mods=True))
        self.assertEqual((self.instance / "Libs/MonoMod.Core.dll").read_bytes(),
                         self.originals["Libs/MonoMod.Core.dll"])
        self.run_installer("uninstall", mods=True)
        self.assert_uninstalled()


if __name__ == "__main__":
    unittest.main()
