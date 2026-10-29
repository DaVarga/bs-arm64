"""Local and custom-URL Unity packages, using tiny archives and a local HTTP server."""
import functools
import gzip
import io
import shutil
import struct
import tarfile
import threading
import unittest
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from fixture import PINS, Fixture
from test_units import cpio, xar_pkg
from bs_arm64.fetch import OPENXR_MEMBER, PLAYER_FILES, PLAYER_VARIATION


def openxr_dll() -> bytes:
    """Minimal ARM64 PE with the UWP imports that the real patcher must rewrite."""
    data = bytearray(2048)
    pe, opt, raw = 0x80, 0x98, 0x200
    struct.pack_into("<I", data, 0x3C, pe)
    data[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<HH", data, pe + 4, 0xAA64, 1)
    struct.pack_into("<H", data, pe + 20, 240)
    struct.pack_into("<H", data, opt, 0x20B)
    struct.pack_into("<II", data, opt + 120, 0x1000, 80)
    struct.pack_into("<IIII", data, opt + 240 + 8, len(data) - raw, 0x1000, len(data) - raw, raw)
    for i, name in enumerate((b"MSVCP140_APP.dll", b"VCRUNTIME140_APP.dll",
                              b"api-ms-win-core-libraryloader-l2-1-0.dll")):
        name_off, thunk_off = 0x300 + i * 64, 0x400 + i * 16
        struct.pack_into("<IIIII", data, raw + i * 20, thunk_off - raw + 0x1000, 0, 0,
                         name_off - raw + 0x1000, 0)
        data[name_off:name_off + len(name)] = name
        if i == 2:
            struct.pack_into("<Q", data, thunk_off, 0x1300)
            data[0x502:0x502 + len(b"LoadPackagedLibrary")] = b"LoadPackagedLibrary"
    return bytes(data)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class FetchFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.player = self.cache / f'unity-{PINS["UNITY_VERSION"]}'
        shutil.rmtree(self.player)
        self.package = self.root / "downloads/Unity package.pkg"
        self.members = {f"./{PLAYER_VARIATION}/{name}": b"custom player " + name.encode()
                        for name in PLAYER_FILES}
        self.write_package()

    def write_package(self):
        self.write(self.package, xar_pkg(gzip.compress(cpio(self.members))))

    @contextmanager
    def server(self):
        handler = functools.partial(QuietHandler, directory=str(self.package.parent))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def assert_cached(self):
        for name in PLAYER_FILES:
            self.assertEqual((self.player / PLAYER_VARIATION / name).read_bytes(),
                             b"custom player " + name.encode())



class FetchTests(FetchFixture):
    def test_fetch_and_install_local_package(self):
        for command in ("fetch", "install"):
            with self.subTest(command=command):
                self.run_cli(command, "--unity-src", str(self.package), "--no-mods")
                self.assert_cached()
                if command == "install":
                    self.assertEqual((self.instance / "Beat Saber.exe").read_bytes(),
                                     b"custom player WindowsPlayer.exe")
                shutil.rmtree(self.player)
        self.assertTrue(self.package.is_file())  # the supplied package is never removed

    def test_fetch_and_install_custom_url(self):
        with self.server() as url:
            for command in ("fetch", "install"):
                with self.subTest(command=command):
                    self.run_cli(command, "--unity-src", url + "/Unity%20package.pkg", "--no-mods")
                    self.assert_cached()
                    shutil.rmtree(self.player)

    def test_home_relative_package(self):
        self.write(self.home / "Unity package.pkg", self.package.read_bytes())
        self.run_cli("fetch", "--unity-src", "~/Unity package.pkg")
        self.assert_cached()

    def test_cache_is_reused_without_opening_source(self):
        self.run_cli("fetch", "--unity-src", str(self.package))
        self.package.unlink()
        self.run_cli("fetch", "--unity-src", str(self.package))
        self.assert_cached()

    def test_missing_local_package_reports_json_error(self):
        self.package.unlink()
        result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
        error = self.json_lines(result)[-1]
        self.assertEqual(error["code"], "DOWNLOAD_FAILED")
        self.assertIn(str(self.package), error["message"])
        self.assertFalse(self.player.exists())

    def test_http_error_reports_custom_url(self):
        with self.server() as url:
            source = url + "/missing.pkg"
            result = self.run_cli("fetch", "--unity-src", source, "--json", success=False)
        error = self.json_lines(result)[-1]
        self.assertEqual(error["code"], "DOWNLOAD_FAILED")
        self.assertIn(source, error["message"])
        self.assertIn("404", error["message"])

    def test_invalid_archive_reports_error_without_caching(self):
        for data in (b"not a package" * 4, b"short"):
            with self.subTest(data=data):
                self.package.write_bytes(data)
                result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
                self.assertEqual(self.json_lines(result)[-1]["code"], "DOWNLOAD_FAILED")
                self.assertFalse(self.player.exists())

    def test_incomplete_archive_can_be_retried(self):
        missing = f"./{PLAYER_VARIATION}/{PLAYER_FILES[-1]}"
        content = self.members.pop(missing)
        self.write_package()
        result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
        error = self.json_lines(result)[-1]
        self.assertEqual(error["code"], "DOWNLOAD_FAILED")
        self.assertIn(PLAYER_FILES[-1], error["message"])
        self.assertFalse(self.player.exists())
        self.members[missing] = content
        self.write_package()
        self.run_cli("fetch", "--unity-src", str(self.package))
        self.assert_cached()


class OpenXRFetchTests(FetchFixture):
    def setUp(self):
        super().setUp()
        self.openxr = self.cache / f'unity-openxr-{PINS["UNITY_OPENXR_VERSION"]}/UnityOpenXR.dll'
        self.openxr.unlink()
        self.xr_package = self.package.parent / "OpenXR package.tgz"
        self.write_openxr_package()

    def write_openxr_package(self, member=OPENXR_MEMBER, dll=None):
        data = openxr_dll() if dll is None else dll
        with tarfile.open(self.xr_package, "w:gz") as archive:
            info = tarfile.TarInfo(member)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    def run_cli(self, command, *extra, **kwargs):
        # Both sources are local unless the test explicitly exercises an OpenXR URL.
        if "--openxr-src" not in extra:
            extra = (*extra, "--openxr-src", str(self.xr_package))
        return super().run_cli(command, *extra, **kwargs)

    def assert_patched(self):
        data = self.openxr.read_bytes()
        for name in (b"msvcp140.dll", b"vcruntime140.dll", b"kernel32.dll", b"LoadLibraryW"):
            self.assertIn(name, data)
        for name in (b"MSVCP140_APP.dll", b"VCRUNTIME140_APP.dll", b"LoadPackagedLibrary"):
            self.assertNotIn(name, data)

    def test_both_local_sources_fetch_and_install(self):
        self.run_cli("fetch", "--unity-src", str(self.package))
        self.assert_cached()
        self.assert_patched()
        shutil.rmtree(self.player)
        self.openxr.unlink()
        self.run_cli("install", "--unity-src", str(self.package), "--no-mods")
        self.assert_patched()
        self.assertEqual((self.instance / "Beat Saber_Data/Plugins/ARM64/UnityOpenXR.dll").read_bytes(),
                         self.openxr.read_bytes())

    def test_openxr_custom_url(self):
        with self.server() as url:
            for command in ("fetch", "install"):
                with self.subTest(command=command):
                    self.run_cli(command, "--unity-src", str(self.package),
                                 "--openxr-src", url + "/OpenXR%20package.tgz", "--no-mods")
                    self.assert_patched()
                    self.openxr.unlink()

    def test_openxr_cache_is_reused(self):
        self.run_cli("fetch", "--unity-src", str(self.package))
        self.xr_package.unlink()
        self.run_cli("fetch", "--unity-src", str(self.package))
        self.assert_patched()

    def test_openxr_missing_local_source(self):
        self.xr_package.unlink()
        result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
        error = self.json_lines(result)[-1]
        self.assertEqual(error["code"], "DOWNLOAD_FAILED")
        self.assertIn(str(self.xr_package), error["message"])
        self.assertFalse(self.openxr.exists())

    def test_openxr_bad_archive(self):
        self.xr_package.write_bytes(b"invalid archive")
        result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
        self.assertEqual(self.json_lines(result)[-1]["code"], "DOWNLOAD_FAILED")
        self.assertFalse(self.openxr.exists())

    def test_openxr_missing_member(self):
        self.write_openxr_package(member="package/wrong.dll")
        result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
        error = self.json_lines(result)[-1]
        self.assertEqual(error["code"], "DOWNLOAD_FAILED")
        self.assertIn(OPENXR_MEMBER, error["message"])
        self.assertFalse(self.openxr.exists())

    def test_openxr_invalid_dll(self):
        self.write_openxr_package(dll=b"not a DLL")
        result = self.run_cli("fetch", "--unity-src", str(self.package), "--json", success=False)
        error = self.json_lines(result)[-1]
        self.assertEqual(error["code"], "DOWNLOAD_FAILED")
        self.assertIn("patching UnityOpenXR.dll", error["message"])
        self.assertFalse(self.openxr.exists())


if __name__ == "__main__":
    unittest.main()
