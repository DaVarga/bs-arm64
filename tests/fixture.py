"""A fake device in a temp dir: HOME with Steam (reaper, user config), an ARM64 Proton whose wine,
wineserver and proton are stubs, a Wine prefix, built artifacts, a filled download cache and a
Beat Saber instance. Commands run through install/bs-arm64.sh, as BSManager runs them."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install/bs-arm64.sh"
PINS = dict(line.split("=", 1) for line in (ROOT / "versions.env").read_text().splitlines()
            if line and not line.startswith("#") and "=" in line)
PROTON_TAGS = PINS["PROTON_TAGS"].strip('"').split()

ARTIFACTS = ("lsteamclient_a64.dll", "wineopenxr_a64.dll", "steam_api64.dll", "openxr_loader.dll",
             "dxgi.dll", "d3d11.dll", "MonoPosixHelper.dll", "LIV_Bridge.dll",
             "ucrtbs64.dll", "vcruntime140.dll", "msvcp140.dll")

# Writes {"argv": [...], "env": {...}, "cwd": ...} to $BS_TEST_RECORD; for `proton run wineboot` creates the
# prefix like Proton does (unless BS_TEST_PROTON_FAILS is set).
FAKE_PROTON = """#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ["run", "wineboot"]:
    if not os.environ.get("BS_TEST_PROTON_FAILS"):
        os.makedirs(os.path.join(os.environ["STEAM_COMPAT_DATA_PATH"], "pfx/drive_c"))
    sys.exit(0)
with open(os.environ["BS_TEST_RECORD"], "a") as f:
    f.write(json.dumps({"argv": sys.argv, "env": dict(os.environ), "cwd": os.getcwd()}) + "\\n")
"""

# Steam's reaper: `reaper SteamLaunch AppId=<id> -- <command>`; records itself, then runs the command
FAKE_REAPER = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["BS_TEST_RECORD"], "a") as f:
    f.write(json.dumps({"argv": sys.argv, "reaper": True}) + "\\n")
command = sys.argv[sys.argv.index("--") + 1:]
os.execv(command[0], command)
"""

STEAM_USER = "76561198000000001"   # account id 39734273


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bs-arm64-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.steam = self.home / ".steam/steam"
        self.instance = self.root / "instance"
        self.artifacts = self.root / "artifacts"
        self.cache = self.root / "cache"
        self.prefix = self.root / "compatdata"
        self.proton = self.root / "proton"
        self.record = self.root / "record.jsonl"

        self.originals = {
            "Beat Saber.exe": b"original x64 player",
            "UnityPlayer.dll": b"original x64 engine",
            "UnityCrashHandler64.exe": b"original crash handler",
            "MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll": b"original mono",
            "vcruntime140.dll": b"original x64 runtime",
            "msvcp140.dll": b"original x64 C++ library",
        }
        for name, data in self.originals.items():
            self.write(self.instance / name, data)
        self.write(self.instance / "Beat Saber_Data/globalgamemanagers",
                   f'\0{PINS["UNITY_VERSION"]}\0 1.44.1_20239'.encode())
        self.write(self.prefix / "pfx/drive_c/windows/system32/ucrtbase.dll", b"prefix UCRT unchanged")
        self.write(self.prefix / "pfx/user.reg", b"prefix runtime settings unchanged")

        self.set_proton(PINS["PROTON_TAG"])
        for name in ("lsteamclient.so", "wineopenxr.so"):
            self.write(self.proton / "files/lib/wine/aarch64-unix" / name, b"unix half")
        for name in ("wine", "wineserver"):
            self.write_script(self.proton / "files/bin-arm64" / name, "#!/bin/sh\nexit 0\n")
        self.write_script(self.proton / "proton", FAKE_PROTON)
        self.write_script(self.steam / "steamrtarm64/reaper", FAKE_REAPER)
        self.write(self.steam / "config/loginusers.vdf",
                   f'"users"\n{{\n\t"{STEAM_USER}"\n\t{{\n\t\t"MostRecent"\t\t"1"\n\t}}\n}}\n'.encode())

        unity = self.cache / f'unity-{PINS["UNITY_VERSION"]}' / "Variations/win_arm64_player_nondevelopment_mono"
        for name in ("WindowsPlayer.exe", "UnityPlayer.dll", "UnityCrashHandler64.exe",
                     "MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll"):
            self.write(unity / name, b"ARM64 unity " + name.encode())
        self.write(self.cache / f'unity-openxr-{PINS["UNITY_OPENXR_VERSION"]}/UnityOpenXR.dll', b"ARM64 XR")
        for name in ARTIFACTS:
            self.write(self.artifacts / name, b"new artifact " + name.encode())

    # --- helpers ------------------------------------------------------------------------------

    @staticmethod
    def write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_script(self, path: Path, text: str) -> None:
        self.write(path, text.encode())
        path.chmod(0o755)

    def set_proton(self, build_tag: str) -> None:
        self.write(self.proton / "version", f"0 {build_tag}-arm64\n".encode())

    def set_foveation(self, on: bool) -> None:
        account = int(STEAM_USER) - 76561197960265728
        apps = '"620980" { "FDMEnable" "1" }' if on else ""
        self.write(self.steam / f"userdata/{account}/config/localconfig.vdf",
                   f'"UserLocalConfigStore" {{ "Software" {{ "Valve" {{ "Steam" {{ "apps" {{ {apps} }} }} }} }} }}'
                   .encode())

    def env(self) -> dict:
        env = dict(os.environ, HOME=str(self.home), BS_TEST_RECORD=str(self.record))
        for name in ("DISPLAY", "FDM_DEBUG", "XDG_CACHE_HOME"):
            env.pop(name, None)
        return env

    def run_cli(self, command: str, *extra: str, success: bool = True, paths: bool = True,
                env: dict | None = None) -> subprocess.CompletedProcess:
        """bash bs-arm64.sh <command> <instance> [--artifacts --cache --prefix --proton] <extra>"""
        args = ["bash", str(INSTALLER), command, str(self.instance)]
        if paths:
            args += ["--artifacts", str(self.artifacts), "--cache", str(self.cache),
                     "--prefix", str(self.prefix), "--proton", str(self.proton)]
        result = subprocess.run(args + list(extra), check=False, env=env or self.env(), capture_output=True, text=True,
                                timeout=45)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def run_installer(self, command: str, success: bool = True, mods: bool = False) -> str:
        result = self.run_cli(command, *([] if mods else ["--no-mods"]), success=success)
        return result.stdout + result.stderr

    def json_lines(self, result: subprocess.CompletedProcess) -> list[dict]:
        return [json.loads(line) for line in result.stdout.splitlines()]

    def recorded(self) -> list[dict]:
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    def assert_prefix_unchanged(self):
        self.assertEqual((self.prefix / "pfx/drive_c/windows/system32/ucrtbase.dll").read_bytes(),
                         b"prefix UCRT unchanged")
        self.assertEqual((self.prefix / "pfx/user.reg").read_bytes(), b"prefix runtime settings unchanged")

    def assert_uninstalled(self):
        for name, data in self.originals.items():
            self.assertEqual((self.instance / name).read_bytes(), data, name)
        self.assertFalse((self.instance / "ucrtbs64.dll").exists())
        self.assertFalse((self.instance / ".bs-arm64").exists())
        self.assert_prefix_unchanged()
