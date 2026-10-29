"""The parts we may not redistribute, downloaded from Unity's servers into the cache:
the Windows ARM64 player of the game's Unity version, and Unity's OpenXR plugin (ARM64)."""
import shutil
import struct
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import openxr_patch, unity_pkg
from .errors import Code, Error
from .output import out
from .pins import Pins

PLAYER_VARIATION = "Variations/win_arm64_player_nondevelopment_mono"
PLAYER_FILES = ("WindowsPlayer.exe", "UnityPlayer.dll", "UnityCrashHandler64.exe",
                "MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll")
OPENXR_MEMBER = "package/Runtime/universalwindows/arm64/UnityOpenXR.dll"


@dataclass(frozen=True)
class Fetched:
    player: Path     # dir with PLAYER_FILES
    openxr: Path     # patched UnityOpenXR.dll


def fetch(cache: Path, pins: Pins, unity_src: str | None = None,
          openxr_src: str | None = None) -> Fetched:
    """Fetch missing files; optionally read each package from a local path or HTTP(S) URL."""
    cache.mkdir(parents=True, exist_ok=True)
    player = cache / f"unity-{pins.unity_version}"
    if not (player / PLAYER_VARIATION / "UnityPlayer.dll").is_file():
        out.log(f"Unity {pins.unity_version} Windows ARM64 player (streams the ~500 MB package, keeps ~40 MB)")
        source = unity_src or (
            f"https://download.unity3d.com/download_unity/{pins.unity_changeset}/MacEditorTargetInstaller/"
            f"UnitySetup-Windows-Mono-Support-for-Editor-{pins.unity_version}.pkg")
        tmp = player.with_name(player.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with _open_source(source) as response:
            try:
                unity_pkg.extract(response, tmp, [f"{PLAYER_VARIATION}/{f}" for f in PLAYER_FILES], out.progress)
            except (ValueError, EOFError, OSError, struct.error) as e:
                raise Error(Code.DOWNLOAD_FAILED, f"reading {source} failed: {e}") from e
        missing = [f for f in PLAYER_FILES if not (tmp / PLAYER_VARIATION / f).is_file()]
        if missing:
            raise Error(Code.DOWNLOAD_FAILED, f"{source} has no {', '.join(missing)}")
        tmp.rename(player)

    openxr = cache / f"unity-openxr-{pins.unity_openxr_version}" / "UnityOpenXR.dll"
    if not openxr.is_file():
        out.log(f"Unity OpenXR {pins.unity_openxr_version} ARM64 plugin")
        source = openxr_src or (
            "https://download.packages.unity.com/com.unity.xr.openxr/-/"
            f"com.unity.xr.openxr-{pins.unity_openxr_version}.tgz")
        uwp_dll = None
        with _open_source(source) as response:
            try:
                with tarfile.open(fileobj=response, mode="r|gz") as tgz:
                    for member in tgz:
                        member_file = tgz.extractfile(member) if member.name == OPENXR_MEMBER else None
                        if member_file:
                            with member_file:
                                uwp_dll = member_file.read()
                            break
            except (tarfile.TarError, EOFError, OSError) as e:
                raise Error(Code.DOWNLOAD_FAILED, f"reading {source} failed: {e}") from e
        if uwp_dll is None:
            raise Error(Code.DOWNLOAD_FAILED, f"{source} has no {OPENXR_MEMBER}")
        try:
            patched = openxr_patch.patch(uwp_dll)
        except (ValueError, struct.error) as e:
            raise Error(Code.DOWNLOAD_FAILED, f"patching UnityOpenXR.dll from {source} failed: {e}") from e
        openxr.parent.mkdir(parents=True, exist_ok=True)
        openxr.with_suffix(".tmp").write_bytes(patched)
        openxr.with_suffix(".tmp").rename(openxr)

    out.log(f"fetched into {cache}")
    return Fetched(player=player / PLAYER_VARIATION, openxr=openxr)


def _open_source(source: str):
    if source.lower().startswith(("http://", "https://")):
        return _open(source)
    try:
        return Path(source).expanduser().open("rb")
    except OSError as e:
        raise Error(Code.DOWNLOAD_FAILED, f"opening package {source} failed: {e}") from e


def _open(url: str):
    try:
        return urllib.request.urlopen(url, timeout=60)
    except urllib.error.HTTPError as e:
        # Say where a redirect went: some networks get sent to a mirror without the file (issue #18).
        where = f" (redirected to {e.url})" if e.url and e.url != url else ""
        raise Error(Code.DOWNLOAD_FAILED, f"downloading {url} failed: HTTP {e.code} {e.reason}{where}") from e
    except (urllib.error.URLError, OSError) as e:
        raise Error(Code.DOWNLOAD_FAILED, f"downloading {url} failed: {e}") from e
