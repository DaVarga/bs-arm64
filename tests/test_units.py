"""Unit tests for the parsers: Steam's VDF files and Unity's .pkg (xar + gzip + cpio) format."""
import gzip
import io
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "install"))

from bs_arm64 import steam, unity_pkg


class VdfTests(unittest.TestCase):
    def test_nested_values_escapes_and_comments(self):
        text = r'''
        // comment
        "Root"
        {
            "name"   "a \"quoted\" \\ value"
            "child" { "Key" "1" }
            bare    value
        }'''
        self.assertEqual(steam.parse_vdf(text),
                         {"Root": {"name": 'a "quoted" \\ value', "child": {"Key": "1"}, "bare": "value"}})

    def test_lookup_ignores_case(self):
        tree = steam.parse_vdf('"UserLocalConfigStore" { "software" { "valve" { "steam" { "Apps" { "1" { "x" "y" } } } } } }')
        self.assertEqual(steam._path(tree, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", "1", "X"), "y")


class SteamUserTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, rel: str, text: str) -> None:
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def test_most_recent_user_flag_wins(self):
        self.write("config/loginusers.vdf", '"users" { "76561197960265729" { "Timestamp" "9" } '
                                            '"76561197960265730" { "MostRecent" "1" "Timestamp" "1" } }')
        self.assertEqual(steam._most_recent_user(self.root), "2")

    def test_else_newest_timestamp(self):
        self.write("config/loginusers.vdf", '"users" { "76561197960265729" { "Timestamp" "9" } '
                                            '"76561197960265730" { "Timestamp" "1" } }')
        self.assertEqual(steam._most_recent_user(self.root), "1")

    def test_foveation_switch(self):
        self.write("config/loginusers.vdf", '"users" { "76561197960265729" { "MostRecent" "1" } }')
        self.assertFalse(steam.foveation_enabled(self.root, "620980"))
        self.write("userdata/1/config/localconfig.vdf",
                   '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "620980" { "FDMEnable" "1" } } } } } }')
        self.assertTrue(steam.foveation_enabled(self.root, "620980"))

    def test_nothing_there(self):
        self.assertFalse(steam.foveation_enabled(self.root, "620980"))
        self.assertEqual(steam.client_version(self.root), "unknown")
        self.assertIsNone(steam.reaper(self.root))


def cpio(members: dict[str, bytes]) -> bytes:
    """odc cpio archive of regular files."""
    data = b""
    for name, content in [*members.items(), ("TRAILER!!!", b"")]:
        encoded = name.encode() + b"\0"
        mode = 0 if name == "TRAILER!!!" else 0o100644
        # magic, dev, ino, mode, uid, gid, nlink, rdev, mtime, namesize, filesize
        data += (b"070707" + b"000000" * 2 + b"%06o" % mode + b"000000" * 4 + b"0" * 11
                 + b"%06o" % len(encoded) + b"%011o" % len(content) + encoded + content)
    return data


def xar_pkg(payload: bytes) -> bytes:
    """xar archive with one raw-stored "Payload" entry, like Unity's .pkg."""
    heap_prefix = b"other entry data"
    toc = (f"<xar><toc><file><name>Payload</name><data><offset>{len(heap_prefix)}</offset>"
           f"<length>{len(payload)}</length><encoding style='application/octet-stream'/></data></file>"
           f"</toc></xar>").encode()
    toc_z = zlib.compress(toc)
    header = struct.pack(">4sHHQQI", b"xar!", 28, 1, len(toc_z), len(toc), 1)
    return header + toc_z + heap_prefix + payload


class UnityPkgTests(unittest.TestCase):
    def test_extracts_only_the_wanted_files(self):
        payload = gzip.compress(cpio({"./Variations/a/UnityPlayer.dll": b"player", "./Variations/b/x.dll": b"x"}))
        progress = []
        with tempfile.TemporaryDirectory() as tmp:
            got = unity_pkg.extract(io.BytesIO(xar_pkg(payload)), Path(tmp), ["Variations/a/"],
                                    lambda done, total: progress.append((done, total)))
            self.assertEqual(got, ["Variations/a/UnityPlayer.dll"])
            self.assertEqual((Path(tmp) / "Variations/a/UnityPlayer.dll").read_bytes(), b"player")
            self.assertFalse((Path(tmp) / "Variations/b").exists())
        self.assertEqual(progress[-1], (len(payload), len(payload)))

    def test_not_a_pkg(self):
        with self.assertRaises(ValueError), tempfile.TemporaryDirectory() as tmp:
            unity_pkg.extract(io.BytesIO(b"<html>404 Not Found</html>" + b"\0" * 32), Path(tmp), ["x"])


if __name__ == "__main__":
    unittest.main()
