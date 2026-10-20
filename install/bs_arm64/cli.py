"""Command line. Every command takes --json: one JSON object per line on stdout
({"type": "log"|"warning"|"progress"|"result"|"error", ...}); exit code 0 = success."""
import argparse
import json
import sys
from pathlib import Path

from . import pins
from .config import DEFAULT_CACHE, DEFAULT_PREFIX, DEFAULT_PROTON, Setup
from .errors import Code, Error
from .fetch import fetch
from .install import install, uninstall
from .instance import Instance
from .launch import launch
from .output import out
from .report import doctor, status

DESCRIPTION = """\
Turn a Beat Saber install on Unity 6000.0.40f1 (1.40.9-1.44.1) into a native ARM64 build and run it
on ARM64 Proton (e.g. the Steam Frame)."""

EPILOG = f"""\
commands:
  fetch                 download the parts we may not redistribute (Unity's ARM64 player and
                        OpenXR plugin) from Unity's servers; install does this too
  install <instance>    back up the x64 files and install the ARM64 ones; set up the Wine prefix
                        (created with Proton if it doesn't exist yet). With BSIPA installed, also
                        its ARM64 fixes, unless --no-mods. Run again after (re)installing BSIPA.
  uninstall <instance>  restore the x64 files from the backup
  launch <instance> [-- <game arguments>]
                        start the game through Proton (under Steam's reaper, so Steam sees a VR game)
  status <instance>     the instance's state (for launchers: --json)
  doctor [<instance>]   versions and state, for a bug report

defaults:
  --artifacts  this script's directory in a release, else ../out (build.sh output)
  --cache      {DEFAULT_CACHE}
  --prefix     {DEFAULT_PREFIX} (BSManager's)
  --proton     {DEFAULT_PROTON}

examples:
  bs-arm64.sh install ~/.local/share/BSManager/BSInstances/1.44.1-arm64
  bs-arm64.sh launch ~/.local/share/BSManager/BSInstances/1.44.1-arm64 --detach
  bs-arm64.sh doctor ~/.local/share/BSManager/BSInstances/1.44.1-arm64"""

COMMANDS = ("fetch", "install", "uninstall", "launch", "status", "doctor")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bs-arm64.sh", description=DESCRIPTION, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"bs-arm64 {pins.version()} (api {pins.API_VERSION})")
    p.add_argument("command", choices=COMMANDS, metavar="command")
    p.add_argument("instance", nargs="?", type=Path, help="Beat Saber folder, e.g. a BSManager instance")
    p.add_argument("--json", action="store_true", help="machine-readable output, one JSON object per line")
    p.add_argument("--no-mods", action="store_true",
                   help="install: without the BSIPA fixes (the game always starts without mods); "
                        "launch: start without mods this time")
    p.add_argument("--foveation", action=argparse.BooleanOptionalAction, default=None,
                   help="launch: SteamVR's foveated rendering on/off (default: Steam's Foveated Rendering "
                        "switch for Beat Saber); FDM_DEBUG=enable,hi (or lo, med) picks the strength")
    p.add_argument("--detach", action="store_true",
                   help="launch: return at once, game output in /tmp/bs-arm64.log")
    p.add_argument("--debug", action="store_true", help="launch: Wine, DXVK, OpenXR and Steam API logging")
    for name in ("artifacts", "cache", "prefix", "proton"):
        p.add_argument(f"--{name}", type=Path, metavar="DIR")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Everything after "--" goes to the game
    game_args: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, game_args = argv[:split], argv[split + 1:]
    if not argv:
        parser().print_help()
        return 1
    args = parser().parse_args(argv)
    out.json = args.json
    try:
        run(args, game_args)
    except Error as e:
        out.error(e)
        return 1
    return 0


def run(args: argparse.Namespace, game_args: list[str]) -> None:
    setup = Setup.create(args.artifacts, args.cache, args.prefix, args.proton)
    if args.command == "fetch":
        fetch(setup.cache, setup.pins)
        return
    if args.command == "doctor":
        sections = doctor(_instance(args) if args.instance else None, setup)
        if out.json:
            out.result(sections)
        else:
            print(json.dumps(sections, indent=2))
        return

    instance = _instance(args)
    if args.command == "install":
        install(instance, setup, mods=not args.no_mods)
    elif args.command == "uninstall":
        uninstall(instance, setup)
    elif args.command == "launch":
        launch(instance, setup, mods=not args.no_mods, foveation=args.foveation, debug=args.debug,
               detach=args.detach, game_args=game_args)
    elif args.command == "status":
        out.result(status(instance, setup))


def _instance(args: argparse.Namespace) -> Instance:
    """The instance argument, checked."""
    if args.instance is None:
        raise Error(Code.NOT_AN_INSTANCE, f"usage: {args.command} <Beat Saber instance dir>")
    instance = Instance(args.instance.expanduser().resolve())
    if not instance.is_beat_saber():
        raise Error(Code.NOT_AN_INSTANCE,
                    f"{args.instance} is not a Beat Saber folder (no Beat Saber_Data/globalgamemanagers)")
    return instance
