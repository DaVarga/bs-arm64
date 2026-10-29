# Installing and running

A launcher can run this installer for you (e.g. the ARM64 tab of the Steam Frame fork of
[BSManager](https://github.com/DaVarga/bs-manager)). This page describes the installer itself.

The installer is `install/bs-arm64.sh`, a small wrapper around the Python package
[`install/bs_arm64`](../install/bs_arm64) (standard library only). It runs on the device (Steam Frame,
SteamOS) and needs only `python3`, which ships with SteamOS. It also needs:

- an **instance**: the folder of a Beat Saber install, the one that contains `Beat Saber.exe` and
  `Beat Saber_Data/`, e.g. `~/.local/share/BSManager/BSInstances/1.44.1`. The commands below take it
  as `<instance>`. It must be a game version on **Unity 6000.0.40f1** (1.40.9 through 1.44.1);
  `install` reads the engine from `Beat Saber_Data/globalgamemanagers` and refuses other engines
  before changing anything.
- **Proton 11.0 (ARM64)**, the exact version the DLLs were built for
- a Wine prefix (`--prefix`, the folder Proton gets as `STEAM_COMPAT_DATA_PATH`). The default is
  `~/.local/share/BSManager/SharedContent/compatdata`. If it doesn't exist yet, `install` has Proton
  create it (`proton run wineboot`), as Proton does on a game's first start.
- the DLLs: either a **release tarball** (unpack it and run `./bs-arm64.sh` from inside it; it uses
  the DLLs next to it), or `out/` from `build.sh` (copy the whole repo to the device, or pass
  `--artifacts DIR`)

`install` checks that `<Proton dir>/version` is one of the Proton versions the release was tested with
(`PROTON_TAGS` in `versions.env`) and stops otherwise. After Steam updates Proton, run `install`
again.

Work on a **copy** of an instance, not on the one Steam updates.

## Commands

From a release, run `./bs-arm64.sh` in the unpacked folder instead of `install/bs-arm64.sh`.

```sh
install/bs-arm64.sh fetch                 # download Unity player and UnityOpenXR (cached)
install/bs-arm64.sh install   <instance>  # patch the instance and set up the prefix (runs fetch)
install/bs-arm64.sh launch    <instance>  # start it; --detach to return at once, --debug for verbose logs
install/bs-arm64.sh uninstall <instance>  # restore the x64 files
install/bs-arm64.sh status    <instance>  # the instance's state (--json for launchers)
install/bs-arm64.sh doctor   [<instance>] # versions and state, for a bug report
```

Options: `--artifacts DIR`, `--cache DIR` (default `~/.cache/bs-arm64`), `--prefix DIR`,
`--proton DIR`, `--no-mods` (see [Without mods](#without-mods)), `--json`. `--help` lists them all.

`fetch` streams the ~500 MB Unity package once and keeps about 40 MB.

If Unity's download URL does not work on your connection, pass `--unity-src PATH_OR_URL` to
`fetch` or `install` to read a local package or stream a custom HTTP(S) URL:

```sh
install/bs-arm64.sh fetch --unity-src ~/Downloads/UnitySetup-Windows-Mono-Support-for-Editor-6000.0.40f1.pkg
install/bs-arm64.sh fetch --unity-src 'https://example.com/UnitySetup-Windows-Mono-Support-for-Editor-6000.0.40f1.pkg'
install/bs-arm64.sh install <instance> --unity-src /path/to/unity.pkg
```

Use the **Windows Mono support package for Unity 6000.0.40f1**, matching `UNITY_VERSION` in
`versions.env`. Keep the `.pkg` packed; the installer extracts only the required ARM64 player files
into the usual cache. Existing cached files are reused even when `--unity-src` is supplied.
Use `--openxr-src PATH_OR_URL` to supply the separate Unity OpenXR `.tgz` package, matching
`UNITY_OPENXR_VERSION` in `versions.env` (currently 1.14.3). The installer extracts and patches its
ARM64 DLL as usual. A custom URL also works, e.g.
`--openxr-src https://example.com/com.unity.xr.openxr-1.14.3.tgz`. Each option defaults to Unity's download URL when omitted, and each package
is fetched only if its extracted files are missing from the cache.

With both packages supplied locally, `fetch` and `install` need no downloads:

```sh
install/bs-arm64.sh fetch --unity-src /path/to/unity.pkg --openxr-src /path/to/com.unity.xr.openxr-1.14.3.tgz
install/bs-arm64.sh install <instance> --unity-src /path/to/unity.pkg --openxr-src /path/to/com.unity.xr.openxr-1.14.3.tgz
```

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

The private runtime is entirely in the instance: it does not replace the prefix's
`system32/ucrtbase.dll`, add runtime registry overrides, or change Proton or launcher settings.
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

Install BSIPA and mods with your mod manager. Then run `install/bs-arm64.sh install <instance>` **again**, because `IPA.exe` puts its x64
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

`launch` runs `reaper SteamLaunch AppId=620980 -- proton run "Beat Saber.exe" [<game arguments>]`,
as Steam does, in the foreground; with `--detach` it returns at once and the output goes to
`/tmp/bs-arm64.log`. Arguments after `--` go to the game. Steam's `reaper` tells Steam that Beat Saber
is running. Without it, Steam treats the game as a non-VR app: the Frame's non-VR frame limiter
applies, and the desktop window shows in the VR overlay (issue #14).

It sets the usual Steam and Proton variables plus:

- `WINEDLLPATH=<prefix>/pfx/drive_c/bs-arm64`
- Valve's foveated rendering when Beat Saber's **Foveated Rendering** switch in Steam is on (read from
  Steam's `localconfig.vdf`): `FDM_DEBUG=enable` (keeps a preset you set, e.g. `FDM_DEBUG=enable,hi`)
  and `VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection`. `--foveation` /
  `--no-foveation` override the switch.
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
| capped at a fraction of the refresh rate (e.g. 40 FPS at 120 Hz) | the Frame's non-VR frame limiter: the game wasn't started under Steam's `reaper` (launcher without `bs-arm64.sh launch`) |

For a bug report, paste the output of `bs-arm64.sh doctor <instance>`.

The game log is at `<prefix>/pfx/drive_c/users/steamuser/AppData/LocalLow/Hyperbolic Magnetism/Beat Saber/Player.log`.
SteamVR's per-session stats are in `~/.local/share/Steam/logs/vrcompositor.txt` (search for
`Cumulative stats for pid`).

## For launchers

A launcher calls the installer instead of duplicating its logic:

- `install`, `uninstall`: exit code 0 on success. Without `--json`, progress lines go to stdout as
  `==> ...` and the error to stderr as `error: ...` (older launchers read that).
- `--json` on any command: one JSON object per line on stdout, `{"type": "log" | "warning" |
  "progress" | "result" | "error", ...}`. Errors carry a stable `code`
  ([`errors.py`](../install/bs_arm64/errors.py)).
- `status <instance> --json`: a `result` with the instance's state (`installed`, `mods`, `ready`,
  Proton builds, ...; see [`report.py`](../install/bs_arm64/report.py)). `api` is the interface version:
  keys are only added, never renamed or removed, without raising it.
- `launch <instance> [-- <game arguments>]` runs in the foreground, so the launcher sees when the game
  exits. User launch options that wrap `%command%` wrap this command.
- The files in `<instance>/.bs-arm64/` (`installed`, `mods`, `proton-version`) and
  `<prefix>/pfx/drive_c/bs-arm64/proton-version` stay as they are, for launchers that read them.
