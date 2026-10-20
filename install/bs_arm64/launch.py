"""Start the game: the environment and command line Steam would use, plus what the ARM64 build needs."""
import os
import subprocess
from pathlib import Path

from . import steam
from .config import Setup
from .errors import Code, Error
from .instance import Instance
from .output import out
from .pins import BS_APP_ID

DETACHED_LOG = Path("/tmp/bs-arm64.log")


def launch(instance: Instance, setup: Setup, *, mods: bool, foveation: bool | None, debug: bool,
           detach: bool, game_args: list[str]) -> None:
    """Run the game in the foreground (this process becomes it, so a launcher sees when it exits),
    or with detach in the background with its output in DETACHED_LOG.
    foveation None: follow Steam's Foveated Rendering switch for Beat Saber."""
    if not instance.is_installed():
        raise Error(Code.NOT_INSTALLED, f"{instance.path} has no bs-arm64 install; run install first")
    # The prefix runtime links to the unix halves of the Proton it was installed with.
    built_for, proton = setup.prefix.runtime_proton(), setup.proton.build
    if built_for != proton:
        raise Error(Code.PROTON_CHANGED, f"Proton changed ({built_for or 'unknown'} -> {proton}); run install again")
    # Installed without mods: BSIPA's winhttp.dll (if any) is still the x64 one.
    mods = mods and instance.mods_enabled()
    if not mods:
        out.log("starting without mods")
    if foveation is None:
        foveation = steam.foveation_enabled(setup.steam_root, BS_APP_ID)
    if foveation:
        out.log("foveated rendering on")

    env = dict(os.environ, **launch_env(instance, setup, mods=mods, foveation=foveation, debug=debug))
    command = launch_command(instance, setup, game_args)
    if detach:
        out.log(f"launching {instance.path} (log: {DETACHED_LOG})")
        with DETACHED_LOG.open("wb") as log:
            child = subprocess.Popen(command, env=env, cwd=instance.path, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        out.log(f"pid {child.pid}")
    else:
        out.log(f"launching {instance.path}")
        os.chdir(instance.path)
        os.execve(command[0], command, env)


def launch_env(instance: Instance, setup: Setup, *, mods: bool, foveation: bool, debug: bool) -> dict[str, str]:
    """The variables we set; everything else is inherited."""
    env = {
        # Started outside a graphical session (e.g. over SSH): use the device's main X display.
        "DISPLAY": os.environ.get("DISPLAY") or ":0",
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
        "SteamAppId": BS_APP_ID, "SteamGameId": BS_APP_ID, "SteamOverlayGameId": BS_APP_ID,
        "STEAM_COMPAT_APP_ID": BS_APP_ID,
        "SteamEnv": "1",  # run in Steam's environment (BSManager #585: unicode song titles)
        "STEAM_COMPAT_DATA_PATH": str(setup.prefix.compatdata),
        "STEAM_COMPAT_INSTALL_PATH": str(instance.path),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(setup.steam_root),
        # Our Wine builtins (lsteamclient_a64, wineopenxr_a64)
        "WINEDLLPATH": str(setup.prefix.runtime),
        # Mod loader: BSIPA's Doorstop (winhttp.dll) in the game dir, else Wine's builtin.
        # Without mods, always the builtin, so Doorstop never loads.
        "WINEDLLOVERRIDES": "winhttp=n,b" if mods else "winhttp=b",
    }
    # Valve's foveated rendering (fdm_injection), enabled as Steam does for "Foveated Rendering".
    # FDM_DEBUG=enable,hi (or lo, med) in the environment picks a stronger or weaker preset.
    if foveation:
        env["FDM_DEBUG"] = os.environ.get("FDM_DEBUG") or "enable"
        env["VK_INSTANCE_LAYERS"] = "VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection"
    if debug:
        env.update(STEAMAPI_ARM64_LOG="1", XR_LOADER_DEBUG="all", DXVK_LOG_LEVEL="info",
                   WINEDEBUG="+loaddll,err,warn+openxr,warn+module,+debugstr")
    return env


def launch_command(instance: Instance, setup: Setup, game_args: list[str]) -> list[str]:
    """Proton running the game, under Steam's reaper if there is one (see steam.reaper)."""
    command = [str(setup.proton.path / "proton"), "run", str(instance.path / "Beat Saber.exe"), *game_args]
    reaper = steam.reaper(setup.steam_root)
    if reaper:
        command = [str(reaper), "SteamLaunch", f"AppId={BS_APP_ID}", "--", *command]
    return command
