# Architecture

## Starting point

Beat Saber 1.40.9 through 1.44.1 are Unity 6000.0.40f1 games, built with the Mono scripting backend
for Windows x64. Under Proton 11.0 (ARM64) the game's x64 code (`UnityPlayer.dll`, Mono's JIT output,
native plugins) runs through **FEX**, and that translated code takes most of the main thread's time:
the game is CPU-bound.

Unity ships a Windows ARM64 player for the same engine version. Game code is IL in `Managed/*.dll`,
and game data is engine-specific but not architecture-specific. So swapping the player binaries gives
a native ARM64 process that runs the unmodified game. A pure ARM64 process can't load x64 or ARM64EC
code, though: every native module the game touches needs a pure ARM64 version, and that is what this
project provides.

```
Beat Saber.exe (Unity ARM64 WindowsPlayer.exe)
├─ UnityPlayer.dll (ARM64) ── Mono (mono-2.0-bdwgc.dll ARM64) ── game IL (unchanged)
│    └─ MonoPosixHelper.dll ............ gzip for System.IO.Compression [built here]
├─ d3d11.dll / dxgi.dll ................ DXVK aarch64 [built here] ── winevulkan (Wine, ARM64X)
├─ Plugins/ARM64/steam_api64.dll ....... Steamworks flat API [written here]
│    └─ lsteamclient_a64.dll ........... Proton lsteamclient PE half, aarch64 [built here]
│         └─ lsteamclient.so ........... Proton's unix half (stock) ── Linux steamclient.so
├─ Plugins/ARM64/LIV_Bridge.dll ........ stub: no LIV capture [written here]
├─ Plugins/ARM64/UnityOpenXR.dll ....... Unity UWP ARM64 build, imports patched [patched here]
│    └─ openxr_loader.dll .............. Khronos loader, patched [built here]
│         └─ wineopenxr_a64.dll ........ Proton wineopenxr PE half, aarch64 [built here]
│              └─ wineopenxr.so ........ Proton's unix half (stock) ── SteamVR OpenXR
└─ vcruntime140/msvcp140/ucrtbs64 ...... private Wine ARM64 runtime (built)
```

## Components

### Unity ARM64 player

Downloaded from Unity's CDN (`UnitySetup-Windows-Mono-Support-for-Editor-6000.0.40f1.pkg`, the macOS
target-support package). [`unity_pkg.py`](../install/bs_arm64/unity_pkg.py) streams it and keeps four
files: `WindowsPlayer.exe` (→ `Beat Saber.exe`), `UnityPlayer.dll`, `UnityCrashHandler64.exe` and
`mono-2.0-bdwgc.dll`. The ARM64 player looks up native plugins in `Beat Saber_Data/Plugins/ARM64/`.

### Steam: `steam_api64.dll` + `lsteamclient_a64.dll`

Valve ships no Windows ARM64 `steam_api64.dll`, and Proton's `lsteamclient.dll` is ARM64EC only.

**lsteamclient_a64.dll** is Proton's lsteamclient Windows half (plain C, already handles
`__aarch64__`) built for pure ARM64 from the matching Proton tag. Its unix half is Proton's own
`lsteamclient.so`, through a symlink. It's named `_a64` so Wine can't pick Proton's ARM64EC DLL of
the same name, and marked as a Wine builtin so Wine loads its unix half.

**steam_api64.dll** is a new implementation of the Steamworks SDK 1.61 flat API
([src/steam-api](../src/steam-api)): [`gen.py`](../src/steam-api/gen.py) generates the interface
wrappers from the SDK headers, using lsteamclient's vtable layouts. It also serves games built
against older SDKs (1.40.9–1.40.13 use SDK 1.57): it exports their entry points and hands out its own
interface versions when a game asks for older ones. It stays below 350 KB (see
[Mods](#mods-bsipa)).

It also carries the workaround for
[UPSTREAM #4](UPSTREAM.md#4-wine-user-callbacks-write-fpsr-into-fpcr-on-arm64)
([`fpcr_fix.cpp`](../src/steam-api/fpcr_fix.cpp)), because it's the one DLL of ours every launch
loads. `STEAMAPI_ARM64_LOG=1` logs init and the interface mapping to stderr.

### OpenXR

**UnityOpenXR.dll.** Unity's OpenXR package (1.14.3, the version the game ships) has an ARM64 build
only for UWP. [`openxr_patch.py`](../install/bs_arm64/openxr_patch.py) rewrites three imports so it
loads in a desktop process. It loads `openxr_loader.dll` by bare name, so a copy sits next to the exe.

**openxr_loader.dll.** Khronos publishes no desktop ARM64 loader, so we build 1.1.45 (the game's
version) with llvm-mingw. [The patch](../patches/openxr-loader) makes it read
`HKLM\Software\Khronos\OpenXR\1\ActiveRuntimeARM64` before `ActiveRuntime`: Proton's `ActiveRuntime`
points at the ARM64EC wineopenxr, and Proton rewrites it on every launch.

**wineopenxr_a64.dll** is Proton's wineopenxr Windows half built for pure ARM64, like lsteamclient,
with Proton's `wineopenxr.so` as its unix half.

### Graphics: DXVK

Proton's DXVK is ARM64EC, and Wine's own `d3d11` (WineD3D) has no DXVK interop, which wineopenxr needs
to share D3D11 textures with Vulkan. We build DXVK at Proton's commit for aarch64; `dxgi.dll` and
`d3d11.dll` go next to the exe.

[patches/dxvk](../patches/dxvk) adds one optimization for the Frame's tiled GPU: when a multisampled
pass resolves inside the pass, DXVK no longer stores the multisampled color and depth that nothing
reads. If a later pass does load one of them (Screen Distortion does), DXVK stores that target again
from then on. `BS_ARM64_KEEP_MSAA=1` restores DXVK's behavior.

### MonoPosixHelper.dll

Beat Saber reads its gzip-compressed beatmaps through `GZipStream`, which Unity's Mono implements in
`MonoPosixHelper.dll`. Unity's ARM64 player doesn't ship one; without it, maps don't start. We build
Mono's `zlib-helper.c` with zlib ([src/monoposixhelper](../src/monoposixhelper)).

### LIV_Bridge.dll

The game's LIV SDK (mixed reality capture) calls `LIV_Bridge`, which only exists for x64. Without it
every frame threw an exception that BSIPA logged. [The stub](../src/liv-bridge/liv_bridge.c) exports
the same functions and reports "no capture".

### Private Wine C++ runtime

`UnityOpenXR` throws and catches a C++ exception when the tracking origin changes (recenter, headset
put on), and Proton's ARM64 C++ exception handling crashes on it
([UPSTREAM #2](UPSTREAM.md#2-wine-arm64-c-exception-handling)). We build Wine's `vcruntime140.dll`
and `msvcp140.dll` with a private UCRT, `ucrtbs64.dll`, from the matching Proton source with the
upstream fix backported ([patches/wine](../patches/wine)). They live beside the ARM64 exe and leave
the prefix's shared runtime untouched.

## Mods (BSIPA)

BSIPA works once two of its pieces are replaced; the installer does this when it finds BSIPA:

- **Doorstop (`winhttp.dll`)**, BSIPA's injector, is x64 only. We build its source for ARM64
  ([src/doorstop](../src/doorstop)). `launch` sets `WINEDLLOVERRIDES=winhttp=n,b` so it's used.
- **MonoMod.Core** 1.3.3 (in BSIPA 4.3.7) has no Windows ARM64 ABI, so Harmony can't patch anything.
  The installer swaps in unmodified upstream 1.3.4 ([UPSTREAM #1](UPSTREAM.md#1-monomod-no-default-abi-on-windows-arm64)).

BSIPA refuses to load if a file named `*steam*` of 350 KB or more is in the game folder or
`Beat Saber_Data/Plugins` (its anti-piracy check). So `lsteamclient_a64.dll` lives in the prefix
(`C:\bs-arm64\aarch64-windows`), and `build.sh` fails if `steam_api64.dll` grows to 350 KB.

## Wine prefix and launch environment

The installer ([install/bs_arm64](../install/bs_arm64)) adds `C:\bs-arm64` to the prefix: the two
Wine builtins, symlinks to Proton's unix halves, the OpenXR runtime JSON, and `proton-version`, the
Proton build the halves must match. It sets the registry value `ActiveRuntimeARM64` to that JSON.
The full list is in [INSTALL](INSTALL.md#what-install-changes).

`launch` adds `WINEDLLPATH=<prefix>/pfx/drive_c/bs-arm64` and the foveation variables (below) to the
usual Proton and Steam variables, and starts Proton under Steam's `reaper`, as Steam does: that's how
Steam knows a VR game is running. Without it, the Frame's non-VR frame limiter applies.

The Windows halves of lsteamclient and wineopenxr must match Proton's unix halves exactly, so
`launch` refuses to start if Proton was updated after install. Rebuild for the new Proton and
reinstall.

## Foveated rendering: Valve's fdm_injection

SteamOS ships Valve's foveated rendering as one library with two halves: an implicit OpenXR layer,
and a Vulkan layer that attaches the density map to the eye passes (DXVK's Vulkan device, so it works
for ARM64 as for x64). With a game's Foveated Rendering switch on, Steam turns it on with
`FDM_DEBUG=enable` and `VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection`; without
them the layer stays inactive.

`bs-arm64.sh launch` does the same, following Beat Saber's switch (`FDMEnable` in Steam's
`localconfig.vdf`); `--foveation` / `--no-foveation` override it. `FDM_DEBUG` also takes a preset:
`enable,lo`, `enable,med`, `enable,hi` (strongest).
