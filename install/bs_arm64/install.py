"""install / uninstall: swap the x64 game files for ARM64 ones (with a backup), set up the prefix."""
import re
import sys

from .config import Setup
from .errors import Code, Error
from .fetch import fetch
from .instance import Instance
from .output import out

PLUGINS = "Beat Saber_Data/Plugins/ARM64"   # where the ARM64 player looks for native plugins

# Built by build.sh; every release has them.
ARTIFACTS = ("lsteamclient_a64.dll", "wineopenxr_a64.dll", "steam_api64.dll", "openxr_loader.dll",
             "dxgi.dll", "d3d11.dll", "MonoPosixHelper.dll", "LIV_Bridge.dll",
             "ucrtbs64.dll", "vcruntime140.dll", "msvcp140.dll")

# BSIPA's files we replace; uninstalling BSIPA removes them, so only restore them while present.
BSIPA_FILES = ("winhttp.dll", "Libs/MonoMod.Core.dll")


def install(instance: Instance, setup: Setup, mods: bool) -> None:
    pins, proton, prefix = setup.pins, setup.proton, setup.prefix
    # Everything that can fail is checked before the instance is changed.
    engine = instance.engine_version()
    if engine != pins.unity_version:
        raise Error(Code.UNSUPPORTED_ENGINE,
                    f"instance is Unity {engine or 'unknown'} (Beat Saber {instance.game_version()}); "
                    f"this runtime is built for Unity {pins.unity_version}")
    # lsteamclient_a64/wineopenxr_a64 talk to this Proton's unix libraries: only tested builds.
    if not proton.is_tested(pins.proton_tags):
        raise Error(Code.PROTON_UNTESTED,
                    f"Proton is {proton.build}, but this release was tested with {' '.join(pins.proton_tags)} "
                    "only; wait for a release that supports it")
    for name in ARTIFACTS:
        if not (setup.artifacts / name).is_file():
            raise Error(Code.ARTIFACT_MISSING,
                        f"{setup.artifacts / name} missing; run build.sh first (or pass --artifacts)")
    proton.require_arm64()
    if not prefix.exists():
        out.log(f"creating the Wine prefix in {prefix.compatdata}")
        proton.create_prefix(prefix.compatdata, setup.steam_root)
    prefix.wait_idle()
    fetched = fetch(setup.cache, pins)

    out.log(f"installing into {instance.path}")
    a = setup.artifacts
    # Unity engine (ARM64 player of the same Unity version the game was built with)
    instance.install_file(fetched.player / "WindowsPlayer.exe", "Beat Saber.exe")
    instance.install_file(fetched.player / "UnityPlayer.dll", "UnityPlayer.dll")
    instance.install_file(fetched.player / "UnityCrashHandler64.exe", "UnityCrashHandler64.exe")
    mono = "MonoBleedingEdge/EmbedRuntime"
    instance.install_file(fetched.player / mono / "mono-2.0-bdwgc.dll", f"{mono}/mono-2.0-bdwgc.dll")
    instance.install_file(a / "MonoPosixHelper.dll", f"{mono}/MonoPosixHelper.dll")
    # Graphics (app dir wins over the ARM64EC DXVK Proton puts in system32)
    instance.install_file(a / "dxgi.dll", "dxgi.dll")
    instance.install_file(a / "d3d11.dll", "d3d11.dll")
    # Private Wine CRT: the wrappers import ucrtbs64 instead of the shared ucrtbase.
    # No runtime registry overrides or Proton/prefix DLL replacement are needed.
    for name in ("ucrtbs64.dll", "vcruntime140.dll", "msvcp140.dll"):
        instance.install_file(a / name, name)
    # Native plugins, looked up by the ARM64 player in Plugins/ARM64
    instance.install_file(a / "steam_api64.dll", f"{PLUGINS}/steam_api64.dll")
    # The game's LIV SDK has an x64-only bridge; without this stub it throws every frame
    instance.install_file(a / "LIV_Bridge.dll", f"{PLUGINS}/LIV_Bridge.dll")
    instance.install_file(fetched.openxr, f"{PLUGINS}/UnityOpenXR.dll")
    instance.install_file(a / "openxr_loader.dll", f"{PLUGINS}/openxr_loader.dll")
    # UnityOpenXR (UWP build) loads the loader by bare name: must be next to the exe
    instance.install_file(a / "openxr_loader.dll", "openxr_loader.dll")

    if mods:
        _install_bsipa_fixes(instance, setup)
    else:
        _restore_bsipa_files(instance)
    instance.write_state("mods", "1" if mods else "0")
    prefix.setup_runtime(proton, setup.artifacts)
    instance.write_state("proton-version", proton.build)
    instance.write_state("installed", instance.game_version())
    out.log("done")
    if sys.stdout.isatty():  # run by hand, not from a launcher such as BSManager
        out.log(f"start with: bs-arm64.sh launch '{instance.path}'")


def uninstall(instance: Instance, setup: Setup) -> None:
    if not instance.is_installed():
        raise Error(Code.NOT_INSTALLED, f"{instance.path} has no bs-arm64 install")
    setup.prefix.wait_idle()
    out.log(f"restoring x64 files in {instance.path}")
    instance.restore_all(skip_missing=BSIPA_FILES)
    out.log(f"done (the prefix runtime in {setup.prefix.runtime} is left in place)")


def _install_bsipa_fixes(instance: Instance, setup: Setup) -> None:
    """BSIPA (mod loader) needs two ARM64 fixes; applied only when BSIPA is installed.
    Run install again after (re)installing BSIPA, since IPA.exe copies its x64 files back.
     - Doorstop (winhttp.dll): its x64 build can't load into the ARM64 player.
     - MonoMod.Core.dll: BSIPA's 1.3.3 has no Windows ARM64 ABI; upstream 1.3.4 fixes it."""
    if not instance.has_bsipa():
        return
    a, pins = setup.artifacts, setup.pins
    if not (a / "winhttp.dll").is_file():
        raise Error(Code.ARTIFACT_MISSING, f"BSIPA is installed but {a / 'winhttp.dll'} is missing; run build.sh")
    out.log("BSIPA found: installing the ARM64 Doorstop (winhttp.dll)")
    instance.swap_bsipa_file("winhttp.dll", a / "winhttp.dll")

    core = "Libs/MonoMod.Core.dll"
    if not (instance.path / core).is_file():
        return
    ours = a / "MonoMod.Core.dll"
    current = (instance.path / core).read_bytes()
    if ours.is_file() and current == ours.read_bytes():
        return
    # Only upgrade BSIPA's exact version (or our earlier patched build).
    if not re.search(pins.monomod_core_match.encode(), current):
        out.warn(f"{core} is not the recognized BSIPA MonoMod.Core 1.3.3; leaving it unchanged")
        return
    if not ours.is_file():
        raise Error(Code.ARTIFACT_MISSING, f"{ours} is missing; run build.sh monomod")
    out.log(f"BSIPA found: upgrading MonoMod.Core to upstream {pins.monomod_core_version}")
    instance.swap_bsipa_file(core, ours)


def _restore_bsipa_files(instance: Instance) -> None:
    """--no-mods after an install with mods: put BSIPA's own files back."""
    for rel in BSIPA_FILES:
        if instance.restore(rel):
            out.log(f"no mods: restoring BSIPA's {rel}")
