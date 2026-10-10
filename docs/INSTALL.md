# Installing and running

The easiest way is the ARM64 tab of the Steam Frame fork of BSManager
([DaVarga/bs-manager](https://github.com/DaVarga/bs-manager)), which runs this installer for you.
The rest of this page describes the installer itself.

The installer is `install/bs-arm64.sh`. It runs on the device (Steam Frame, SteamOS) and needs only
`bash`, `python3`, `curl`, `tar` and `bsdtar`, which ship with SteamOS. It also needs:

- a Beat Saber instance on **Unity 6000.0.40f1** (1.40.9 through 1.44.1), e.g. from BSManager
  (`~/.local/share/BSManager/BSInstances/1.44.1`). `install` reads the engine from
  `Beat Saber_Data/globalgamemanagers` and refuses other engines before changing anything.
- **Proton 11.0 (ARM64)**, the exact version the DLLs were built for
- the Wine prefix already created. The default is BSManager's shared prefix
  `~/.local/share/BSManager/SharedContent/compatdata`, which Proton creates the first time Beat Saber
  is launched from BSManager. Other games use their own prefixes, so launching them doesn't help.
  `install` checks that the prefix exists before copying files into the instance.
- the DLLs: either a **release tarball** (unpack it and run `./bs-arm64.sh` from inside it; it uses
  the DLLs next to it), or `out/` from `build.sh` (copy the whole repo to the device, or pass
  `--artifacts DIR`)

`install` checks that `<Proton dir>/version` is one of the Proton versions the release was tested with
(`PROTON_TAGS` in `versions.env`) and stops otherwise. After Steam updates Proton, run `install`
again.

Work on a **copy** of an instance. BSManager can duplicate instances.

## Commands

From a release, run `./bs-arm64.sh` in the unpacked folder instead of `install/bs-arm64.sh`.

```sh
install/bs-arm64.sh fetch                 # download Unity player and UnityOpenXR (cached)
install/bs-arm64.sh install   <instance>  # patch the instance and set up the prefix (runs fetch)
install/bs-arm64.sh launch    <instance>  # start it (log: /tmp/bs-arm64.log); --debug for verbose logs
install/bs-arm64.sh uninstall <instance>  # restore the x64 files
```

Options: `--artifacts DIR`, `--cache DIR` (default `~/.cache/bs-arm64`), `--prefix DIR`,
`--proton DIR`, `--no-mods` (see [Without mods](#without-mods)).

`fetch` streams the ~500 MB Unity package once and keeps about 40 MB.

## What `install` changes

In the instance (the originals go to `<instance>/.bs-arm64/backup/`, and added files are listed in
`.bs-arm64/added`):

| File | Replaced by |
|---|---|
| `Beat Saber.exe` | Unity ARM64 `WindowsPlayer.exe` |
| `UnityPlayer.dll`, `UnityCrashHandler64.exe` | Unity ARM64 |
| `MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll` | Unity ARM64 |
| `MonoBleedingEdge/EmbedRuntime/MonoPosixHelper.dll` | built (zlib helper) |
| `dxgi.dll`, `d3d11.dll` (new) | built (DXVK aarch64) |
| `ucrtbs64.dll`, `vcruntime140.dll`, `msvcp140.dll` | built, private Wine ARM64 C++ runtime with the upstream exception-handling fix |
| `openxr_loader.dll` (new, next to the exe) | built |
| `Beat Saber_Data/Plugins/ARM64/` (new) | `steam_api64.dll`, `LIV_Bridge.dll` (stub), `UnityOpenXR.dll` (patched), `openxr_loader.dll` |
| `winhttp.dll` (only if BSIPA is installed) | ARM64 Doorstop |
| `Libs/MonoMod.Core.dll` (BSIPA 4.3.7's MonoMod.Core 1.3.3 or an earlier bs-arm64 build) | unmodified upstream MonoMod.Core 1.3.4 |

The game data and `Managed/*.dll` are not touched. The x64 plugins stay in `Plugins/x86_64/`, where the
ARM64 player ignores them.

Reinstalling over an older bs-arm64 release replaces Microsoft's runtime DLLs with the private Wine
runtime. The installer removes the old `vcruntime140_1.dll` only if its install record owns that file;
pure ARM64 uses `__CxxFrameHandler3` and the game's ARM64 binaries do not import it. Original backups
are retained for uninstall. A user-owned, untracked `vcruntime140_1.dll` is left alone.

The private runtime is entirely in the instance: it does not replace the prefix's
`system32/ucrtbase.dll`, add runtime registry overrides, or change Proton or BSM launch settings.
Retail/x64 instances in the same prefix continue using their own runtime.

In the prefix:

| Item | Purpose |
|---|---|
| `pfx/drive_c/bs-arm64/aarch64-windows/{lsteamclient_a64,wineopenxr_a64}.dll` | Wine builtins, found through `WINEDLLPATH` |
| `pfx/drive_c/bs-arm64/aarch64-unix/*.so` | symlinks to Proton's `lsteamclient.so` / `wineopenxr.so` |
| `pfx/drive_c/bs-arm64/wineopenxr_a64.json` | OpenXR runtime manifest for ARM64 processes |
| `pfx/drive_c/bs-arm64/proton-version` | Proton version these must match |
| `HKLM\Software\Khronos\OpenXR\1` `ActiveRuntimeARM64` | read by our `openxr_loader.dll` before `ActiveRuntime` |

x64 games in the same prefix are unaffected: they ignore the ARM64 value and directory.

## Mods

Install BSIPA and mods as usual. BSManager works: its IPA run uses the x86 copy of `IPA.exe`.
Then run `install/bs-arm64.sh install <instance>` **again**, because `IPA.exe` puts its x64
`winhttp.dll` back. The installer replaces BSIPA's `winhttp.dll` and upgrades `Libs/MonoMod.Core.dll`, and
keeps backups. Mods that ship their own native x64 DLLs won't load their native parts.

Known issue: SiraUtil restarts the XR session at startup. If the headset goes into standby at that
moment (for example, it isn't being worn), Unity sometimes doesn't recreate its eye textures, and the
headset only shows a black window. Keep the headset on while the game starts, or restart the game.

### Without mods

```sh
install/bs-arm64.sh install <instance> --no-mods   # ARM64 engine only; BSIPA's files stay untouched
install/bs-arm64.sh launch  <instance> --no-mods   # start once without mods (instance installed with mods)
```

- `install --no-mods` installs only the ARM64 engine. BSIPA's `winhttp.dll` and
  `Libs/MonoMod.Core.dll` are left alone, or put back if an earlier install had replaced them. The
  choice is stored in `.bs-arm64/mods`, and such an instance always starts without mods. Run `install`
  without the option to turn mods back on.
- `launch --no-mods` starts the game vanilla this one time. It loads Wine's builtin `winhttp` instead
  of BSIPA's Doorstop, so BSIPA and every mod stay unloaded; the files aren't changed.

## Launching

`launch` runs `proton run "Beat Saber.exe"` with the usual Steam and Proton variables plus:

- `WINEDLLPATH=<prefix>/pfx/drive_c/bs-arm64`
- `DISABLE_VULKAN_FDM_INJECTION_LAYER=1`, or with `--foveation` Valve's foveated rendering:
  `FDM_DEBUG=enable` (keeps a preset you set, e.g. `FDM_DEBUG=enable,hi`) and
  `VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection`
- `WINEDLLOVERRIDES=winhttp=n,b`: BSIPA's Doorstop, if present
- `DISPLAY=:0` and `XDG_RUNTIME_DIR`, only if unset (e.g. started over SSH). Without a display, the
  player hangs silently right after start.

SteamVR must be running, which it always is in the Frame's game mode. SteamVR recognizes the game as
`steam.app.620980`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `instance is Unity 2022.3.33f1 (Beat Saber 1.40.8); this runtime is built for Unity 6000.0.40f1` | the game version runs on another Unity engine; it isn't supported |
| `[Steam] Not being able to initialize the platform` | `steam_api64.dll` not in `Plugins/ARM64`, or `WINEDLLPATH` missing; run `launch --debug` and look for `steam_api64(arm64)` lines |
| `DllNotFoundException: UnityOpenXR` | `Plugins/ARM64/UnityOpenXR.dll` missing, or msvcp140/vcruntime140 missing |
| `xrCreateInstance: XR_ERROR_RUNTIME_UNAVAILABLE` | registry value or JSON missing; `launch --debug` shows the loader's messages as `debugstr` lines |
| `xrCreateSession: XR_ERROR_VALIDATION_FAILURE` | WineD3D in use instead of DXVK: `dxgi.dll`/`d3d11.dll` not next to the exe, or `PROTON_USE_WINED3D` set |
| crash in `unityopenxr` / C++ exception handling on recenter | private runtime DLL missing or mixed with an older runtime; reinstall the matching release |
| back to menu with "Could not load readonly beatmap level data" | x64 `MonoPosixHelper.dll` still in place |
| BSIPA log: `Invalid installation; please buy the game` / no `Logs/` folder | a file named `*steam*` of 350 KB or more in the game folder or `Beat Saber_Data/Plugins` (BSIPA anti-piracy) |
| BSIPA log: `doesn't provide a default ABI` | x64/original `Libs/MonoMod.Core.dll`; run `install` again |
| black window in the headset with mods | see *Known issue* under Mods |
| game process idles at 0 % CPU, no `Player.log` | no X display; set `DISPLAY` (launch defaults to `:0`) |
| `launch` refuses: "Proton changed" | rebuild for the new Proton and reinstall (see BUILD.md) |

The game log is at `<prefix>/pfx/drive_c/users/steamuser/AppData/LocalLow/Hyperbolic Magnetism/Beat Saber/Player.log`.
SteamVR's per-session stats are in `~/.local/share/Steam/logs/vrcompositor.txt` (search for
`Cumulative stats for pid`).
