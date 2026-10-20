"""A Beat Saber folder (e.g. a BSManager instance): its versions, and the record of what we changed.

The record lives in <instance>/.bs-arm64/ (BSManager reads installed, mods and proton-version):
  backup/<path>    the original file for every file we replaced
  added            files we added (one relative path per line), removed on uninstall
  installed        Beat Saber version at install time; present = installed
  mods             1 = installed with the BSIPA fixes, 0 = without mods
  proton-version   Proton build the instance was installed with
"""
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

STATE_DIR = ".bs-arm64"
GAME_DATA = "Beat Saber_Data/globalgamemanagers"

# Unity's build string, e.g. "1.44.1_20239" (as BSManager reads it), and engine, e.g. "6000.0.40f1"
_GAME_VERSION = re.compile(rb"[0-9]+\.[0-9]+\.[0-9]+_[0-9]+")
_ENGINE_VERSION = re.compile(rb"[0-9]{4}\.[0-9]+\.[0-9]+f[0-9]+")


@dataclass(frozen=True)
class Instance:
    path: Path

    @property
    def state(self) -> Path:
        return self.path / STATE_DIR

    @property
    def backup(self) -> Path:
        return self.state / "backup"

    def is_beat_saber(self) -> bool:
        return (self.path / GAME_DATA).is_file()

    def _game_data(self) -> bytes:
        try:
            return (self.path / GAME_DATA).read_bytes()
        except OSError:
            return b""

    def game_version(self) -> str:
        """E.g. "1.44.1". BeatSaberVersion.txt only exists after the game or BSIPA ran once."""
        match = _GAME_VERSION.search(self._game_data())
        if match:
            return match.group().decode().split("_")[0]
        return self.read_file("BeatSaberVersion.txt").split("_")[0] or "unknown"

    def engine_version(self) -> str | None:
        """Unity engine the game was built with. The native runtime (player, mono, plugins) is
        engine-specific, not Beat Saber-version specific, so this is what install checks."""
        match = _ENGINE_VERSION.search(self._game_data())
        return match.group().decode() if match else None

    def has_bsipa(self) -> bool:
        """BSIPA's Doorstop (winhttp.dll) is the mod loader's entry point."""
        return (self.path / "winhttp.dll").is_file()

    def read_file(self, rel: str) -> str:
        try:
            return (self.path / rel).read_text().strip()
        except OSError:
            return ""

    # --- install record ---------------------------------------------------------------------

    def is_installed(self) -> bool:
        return (self.state / "installed").is_file()

    def read_state(self, name: str) -> str | None:
        try:
            return (self.state / name).read_text().strip()
        except OSError:
            return None

    def write_state(self, name: str, value: str) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / name).write_text(value + "\n")

    def mods_enabled(self) -> bool:
        """Installed with mod support; an install from before the "mods" record had it."""
        return self.read_state("mods") != "0"

    def added(self) -> list[str]:
        return [line for line in (self.read_state("added") or "").splitlines() if line]

    def _set_added(self, files: list[str]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "added").write_text("".join(f"{f}\n" for f in files))

    # --- changing files ----------------------------------------------------------------------

    def install_file(self, src: Path, rel: str) -> None:
        """Put src at rel. The first time, back up the original, or record the file as ours."""
        dst, bak = self.path / rel, self.backup / rel
        added = self.added()
        if rel not in added and not bak.exists():
            if dst.exists():
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, bak)
            else:
                self._set_added([*added, rel])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def swap_bsipa_file(self, rel: str, src: Path) -> None:
        """Replace one of BSIPA's files. Keeps the first backup: that's BSIPA's original, not an
        earlier build of ours."""
        dst = self.path / rel
        if dst.read_bytes() == src.read_bytes():
            return
        if not (self.backup / rel).exists():
            (self.backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, self.backup / rel)
        shutil.copyfile(src, dst)

    def restore(self, rel: str) -> bool:
        """Copy the backup of rel back if it differs. True if it did."""
        bak, dst = self.backup / rel, self.path / rel
        if bak.is_file() and dst.is_file() and bak.read_bytes() != dst.read_bytes():
            shutil.copy2(bak, dst)
            return True
        return False

    def restore_all(self, skip_missing: tuple[str, ...]) -> None:
        """Uninstall: copy every backup back, remove the files we added, drop the record.
        Files in skip_missing are only restored while they still exist (BSIPA's own files:
        uninstalling BSIPA removes them)."""
        if self.backup.is_dir():
            for bak in sorted(p for p in self.backup.rglob("*") if p.is_file()):
                rel = bak.relative_to(self.backup).as_posix()
                if rel in skip_missing and not (self.path / rel).exists():
                    continue
                (self.path / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bak, self.path / rel)
        for rel in self.added():
            (self.path / rel).unlink(missing_ok=True)
        try:
            (self.path / "Beat Saber_Data/Plugins/ARM64").rmdir()
        except OSError:
            pass
        shutil.rmtree(self.state)
