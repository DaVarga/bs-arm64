"""The Wine prefix (BSManager's shared compatdata): our runtime dir, the registry value, and
the Windows programs running in it."""
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import Code, Error
from .output import out
from .proton import Proton

# Inside the prefix: C:\bs-arm64, the WINEDLLPATH for our Wine builtins
RUNTIME_DIR = "drive_c/bs-arm64"

# Lets openxr_loader.dll find wineopenxr_a64 (see setup_runtime)
OPENXR_RUNTIME_JSON = r"""{
   "file_format_version": "1.0.0",
   "runtime": {
      "library_path": "C:\\bs-arm64\\aarch64-windows\\wineopenxr_a64.dll"
   }
}
"""


@dataclass(frozen=True)
class Prefix:
    compatdata: Path          # STEAM_COMPAT_DATA_PATH

    @property
    def pfx(self) -> Path:    # WINEPREFIX
        return self.compatdata / "pfx"

    @property
    def runtime(self) -> Path:
        return self.pfx / RUNTIME_DIR

    def exists(self) -> bool:
        return (self.pfx / "drive_c").is_dir()

    def runtime_proton(self) -> str | None:
        """Proton build the runtime dir was set up for: it links to that Proton's unix libraries."""
        try:
            return (self.runtime / "proton-version").read_text().strip()
        except OSError:
            return None

    def running_programs(self) -> dict[int, str]:
        """PID -> program name of the processes in this prefix (Proton sets WINEPREFIX to "<pfx>/")."""
        wanted = {f"WINEPREFIX={self.pfx}".encode(), f"WINEPREFIX={self.pfx}/".encode()}
        programs = {}
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if wanted & set((proc / "environ").read_bytes().split(b"\0")):
                    # "C:\windows\system32\services.exe" -> "services.exe"
                    argv0 = (proc / "cmdline").read_bytes().split(b"\0")[0].decode(errors="replace")
                    programs[int(proc.name)] = argv0.replace("\\", "/").rsplit("/", 1)[-1]
            except OSError:
                continue
        return programs

    def wait_idle(self, timeout: float = 30) -> None:
        """Wait for the programs in the prefix to exit: the game, a process left hanging by an earlier
        launch, or Wine's helpers that linger for a few seconds after BSManager ran IPA.exe.
        Installing would then replace files in use, and `wineserver -w` would wait forever."""
        end = time.monotonic() + timeout
        programs = self.running_programs()
        if programs:
            out.log("waiting for Windows programs in the Wine prefix to exit")
        while programs and time.monotonic() < end:
            time.sleep(1)
            programs = self.running_programs()
        if programs:
            names = ", ".join(sorted(set(programs.values()))) or "unknown"
            raise Error(Code.PREFIX_BUSY, f"still running in {self.pfx}: {names}; close it "
                                          "(if nothing is open, restart the device) and try again")

    def setup_runtime(self, proton: Proton, artifacts: Path) -> None:
        """C:\\bs-arm64 with our Wine builtins, and the registry value that selects our OpenXR runtime."""
        out.log(f"prefix runtime in {self.runtime}")
        windows_dir, unix_dir = self.runtime / "aarch64-windows", self.runtime / "aarch64-unix"
        windows_dir.mkdir(parents=True, exist_ok=True)
        unix_dir.mkdir(parents=True, exist_ok=True)
        for name in ("lsteamclient_a64", "wineopenxr_a64"):
            (windows_dir / f"{name}.dll").write_bytes((artifacts / f"{name}.dll").read_bytes())
            # The Windows halves are built from this Proton's source; reuse its unix halves.
            link = unix_dir / f"{name}.so"
            link.unlink(missing_ok=True)
            link.symlink_to(proton.unix_lib_dir / f"{name.removesuffix('_a64')}.so")
        (self.runtime / "wineopenxr_a64.json").write_text(OPENXR_RUNTIME_JSON)
        (self.runtime / "proton-version").write_text(proton.build + "\n")

        # Our openxr_loader.dll prefers ActiveRuntimeARM64 over Proton's ActiveRuntime
        # (which points at the ARM64EC wineopenxr a pure ARM64 process cannot load).
        out.log(r"registry: HKLM\Software\Khronos\OpenXR\1 ActiveRuntimeARM64")
        if not proton.run_wine("wine", self.pfx, "reg", "add", r"HKLM\Software\Khronos\OpenXR\1",
                               "/v", "ActiveRuntimeARM64", "/t", "REG_SZ",
                               "/d", r"C:\bs-arm64\wineopenxr_a64.json", "/f", timeout=180):
            raise Error(Code.PREFIX_FAILED, "setting the OpenXR runtime in the Wine prefix failed or timed out")
        if not proton.run_wine("wineserver", self.pfx, "-w", timeout=60):
            raise Error(Code.PREFIX_FAILED, f"Wine in {self.pfx} did not shut down; restart the device and try again")
