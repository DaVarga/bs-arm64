"""A Proton build: its version, its wine binaries, and creating a prefix with it."""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import Code, Error


@dataclass(frozen=True)
class Proton:
    path: Path

    @property
    def build(self) -> str:
        """E.g. "proton-11.0-2c-arm64", from the "version" file ("<timestamp> <build>")."""
        try:
            return (self.path / "version").read_text().split()[1]
        except (OSError, IndexError):
            return "unknown"

    @property
    def unix_lib_dir(self) -> Path:
        return self.path / "files/lib/wine/aarch64-unix"

    def is_arm64(self) -> bool:
        return (self.unix_lib_dir / "lsteamclient.so").is_file()

    def is_tested(self, tags: tuple[str, ...]) -> bool:
        """Proton's build "proton-11.0-2c-arm64" belongs to the tag "proton-11.0-2c"."""
        return any(self.build == tag or self.build.startswith(f"{tag}-") for tag in tags)

    def require_arm64(self) -> None:
        if not self.is_arm64():
            raise Error(Code.PROTON_NOT_ARM64, f"{self.path} is not an ARM64 Proton")

    def run_wine(self, program: str, pfx: Path, *args: str, timeout: int) -> bool:
        """Run "wine" or "wineserver" in a prefix, quietly. False if it failed or ran out of time:
        a hanging wine must end in an error message, not a stuck installer."""
        bin_dir = self.path / "files/bin-arm64"
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}",
                   WINEPREFIX=str(pfx), WINEDEBUG="-all")
        try:
            return subprocess.run([str(bin_dir / program), *args], check=False, env=env, timeout=timeout,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def create_prefix(self, compatdata: Path, steam_root: Path) -> None:
        """Let Proton set up compatdata/pfx as it does on a game's first start.

        `proton run` creates or updates the prefix before it starts the program; wineboot
        itself returns at once. This is the prefix a launch from BSManager would have made.
        """
        compatdata.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, STEAM_COMPAT_DATA_PATH=str(compatdata),
                   STEAM_COMPAT_CLIENT_INSTALL_PATH=str(steam_root))
        try:
            subprocess.run([str(self.path / "proton"), "run", "wineboot"], check=False, env=env, timeout=300,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass  # checked below
        if not (compatdata / "pfx/drive_c").is_dir():
            raise Error(Code.PREFIX_FAILED, f"Proton could not create the Wine prefix in {compatdata}")
