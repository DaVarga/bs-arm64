"""status: an instance's state, for BSManager (--json).
doctor: versions and state, for a bug report.

Both only read. Anything that can't be found is "unknown"/None, never an error.
"""
import platform
import re
import subprocess
from pathlib import Path

from . import pins, steam
from .config import Setup
from .instance import Instance
from .pins import BS_APP_ID


def status(instance: Instance, setup: Setup) -> dict:
    """What BSManager needs to show the ARM64 tab and to launch. Keys are part of the API
    (pins.API_VERSION): add freely, but don't rename or remove."""
    engine = instance.engine_version()
    runtime_proton = setup.prefix.runtime_proton()
    installed = instance.is_installed()
    return {
        "api": pins.API_VERSION,
        "version": pins.version(),
        "gameVersion": instance.game_version(),
        "engine": engine,
        "engineSupported": engine == setup.pins.unity_version,
        "bsipa": instance.has_bsipa(),
        "installed": installed,
        "mods": installed and instance.mods_enabled(),
        "installedProton": instance.read_state("proton-version"),
        "protonBuild": setup.proton.build,
        "protonArm64": setup.proton.is_arm64(),
        "protonTested": setup.proton.is_tested(setup.pins.proton_tags),
        "prefixExists": setup.prefix.exists(),
        "runtimeProton": runtime_proton,
        # Launch works without running install again
        "ready": installed and runtime_proton == setup.proton.build,
    }


def doctor(instance: Instance | None, setup: Setup) -> dict[str, dict[str, str]]:
    """Sections of label -> value."""
    os_release = _os_release()
    sections = {
        "bs-arm64": {
            "version": pins.version(),
            "Python": platform.python_version(),
        },
        "System": {
            "OS": f"{os_release.get('PRETTY_NAME', 'unknown')} {os_release.get('VERSION_ID', '')}".strip(),
            "build": os_release.get("BUILD_ID", "unknown"),
            "variant": os_release.get("VARIANT_ID", "unknown"),
            "branch": _run("steamos-select-branch", "-c") or "unknown",
            "kernel": f"{platform.release()} ({platform.machine()})",
            **_packages(),
        },
        "Steam": {
            "client": steam.client_version(setup.steam_root),
            "reaper": "found" if steam.reaper(setup.steam_root) else "not found",
            "Beat Saber Foveated Rendering": "on" if steam.foveation_enabled(setup.steam_root, BS_APP_ID) else "off",
        },
        "Proton": {
            "path": str(setup.proton.path),
            "build": setup.proton.build,
            "ARM64": _yes(setup.proton.is_arm64()),
            "tested with this release": _yes(setup.proton.is_tested(setup.pins.proton_tags)),
        },
        "Wine prefix": {
            "path": str(setup.prefix.compatdata),
            "exists": _yes(setup.prefix.exists()),
            "bs-arm64 runtime set up for": setup.prefix.runtime_proton() or "none",
        },
    }
    if instance:
        engine = instance.engine_version() or "unknown"
        supported = engine == setup.pins.unity_version
        sections["Instance"] = {
            "path": str(instance.path),
            "Beat Saber": instance.game_version(),
            "Unity": f"{engine} ({'supported' if supported else 'not supported'})",
            "BSIPA": "installed" if instance.has_bsipa() else "not installed",
            "bs-arm64 installed": _yes(instance.is_installed()),
            "mods": _yes(instance.mods_enabled()) if instance.is_installed() else "-",
            "installed with Proton": instance.read_state("proton-version") or "-",
        }
    return sections


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _os_release() -> dict[str, str]:
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return {}
    return {k: v.strip('"') for k, v in re.findall(r"^(\w+)=(.*)$", text, re.MULTILINE)}


def _packages() -> dict[str, str]:
    """SteamVR and Mesa packages (SteamOS on the Frame ships them as pacman packages)."""
    listing = _run("pacman", "-Q") or ""
    found = {}
    for line in listing.splitlines():
        name, _, ver = line.partition(" ")
        if "steamvr" in name or "mesa" in name:
            found[name] = ver
    return found


def _run(*command: str) -> str | None:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
