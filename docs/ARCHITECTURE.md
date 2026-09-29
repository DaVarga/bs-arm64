# Architecture

## Starting point

Beat Saber 1.44.1 is a Unity 6000.0.40f1 game, built with the Mono scripting backend for Windows x64.
The Steam Frame runs it through Proton 11.0 (ARM64), in these steps:

1. Wine's own code (ntdll, kernel32, …) is ARM64/ARM64X.
2. The game's x64 code (`UnityPlayer.dll`, Mono's JIT output, every native plugin) runs through
   **FEX** as ARM64EC.
3. Proton's game-facing modules (DXVK, lsteamclient, wineopenxr) are **ARM64EC** builds, so an x64
   process can load them.

A perf profile of gameplay showed that the main thread spends 83–87% of its time in
FEX-translated code (`[anon:FEXMemJIT]`). The game is CPU-bound, and rendering resolution barely matters.

Unity ships a Windows ARM64 player for the same engine version (module "Windows Build Support (Mono)",
variation `win_arm64_player_nondevelopment_mono`). Game code is IL in `Managed/*.dll` and game data is
engine-version specific but architecture independent. So swapping the player binaries gives a native
ARM64 process that runs the unmodified game data and assemblies.

A pure ARM64 process can't load x64 or ARM64EC code. Every native module the game touches needs a
pure ARM64 version, and that is what this project provides.

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
└─ vcruntime140/msvcp140 ............... Microsoft ARM64 runtime (downloaded)
```

## Components

### Unity ARM64 player

Source: `UnitySetup-Windows-Mono-Support-for-Editor-6000.0.40f1.pkg`, from Unity's CDN (the macOS
target-support package; it contains every Windows player variation).
[`tools/unity_pkg_extract.py`](../tools/unity_pkg_extract.py) streams the xar → gzip → cpio chain
and keeps only four files:

- `WindowsPlayer.exe` → `Beat Saber.exe`
- `UnityPlayer.dll`
- `UnityCrashHandler64.exe`
- `MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll`

The ARM64 player looks up native plugins in `Beat Saber_Data/Plugins/ARM64/`, not `Plugins/x86_64/`.

### Steam: `steam_api64.dll` + `lsteamclient_a64.dll`

Valve ships no Windows ARM64 `steam_api64.dll`. Proton's `lsteamclient.dll`, which is what
`steam_api` normally loads as `steamclient64.dll`, is ARM64EC only.

**lsteamclient_a64.dll.** Proton's lsteamclient is split in two halves:

- A Windows half: thunks that marshal every interface call into a parameter struct.
- A unix half, `lsteamclient.so`, which calls the native Linux `steamclient.so`.

The two halves talk through Wine's unix-call interface (`__wine_unix_call`). The Windows half is plain C
and already handles `__aarch64__`, so we build it from the Proton tag matching the installed
Proton. The compiler is llvm-mingw's `aarch64-w64-mingw32-clang`, using Wine's headers and a tiny
`winecrt0` shim. The unix half is reused as is.

Callbacks are polled (`steamclient_next_callback`), so no unix→PE calls are needed.

We name it `lsteamclient_a64` so Wine can't pick Proton's ARM64EC `lsteamclient.dll`, which comes
first in Wine's DLL search path. Its unix half is a symlink, `lsteamclient_a64.so` → Proton's
`lsteamclient.so`. Wine only loads a unix half for DLLs it treats as *builtin*, so we:

- stamp the "Wine builtin DLL" marker into the DOS header,
- put the DLL in `$WINEDLLPATH/aarch64-windows/` and the symlink in `$WINEDLLPATH/aarch64-unix/`,
- have `steam_api64.dll` load that file by its full path.

Loading by full path is what makes it work: Wine resolves a builtin through `WINEDLLPATH` only after
it finds a builtin-marked file on the normal search path, or one given by path.

**steam_api64.dll.** This is a new implementation of the Steamworks SDK 1.61 flat API. It
exports all 1,089 symbols of the real DLL.

- **Interface wrappers.** [`gen.py`](../src/steam-api/gen.py) generates 946 `SteamAPI_ISteamX_Method`
  wrappers from `steam_api_flat.h`. Each one calls into the interface's vtable. Vtable indices come
  from lsteamclient's own vtable definitions for the interface versions of SDK 1.61. Overloads are
  resolved through `STEAM_FLAT_NAME` and MSVC's reversed overload order. All 879 indices that can be
  checked match the offsets disassembled from the real x64 `steam_api64.dll`.
- **Struct returns.** Methods that return a struct (`CSteamID`, `SteamIPAddress_t`, …) take a hidden
  `_ret` pointer after `this` in lsteamclient. The generator detects them and wraps them.
- **Core** ([`steam_api_core.cpp`](../src/steam-api/steam_api_core.cpp)):
  - init: `SteamInternal_SteamAPI_Init` → `CreateInterface("SteamClient021")` → pipe → global user →
    interface version check
  - `SteamInternal_ContextInit`, `FindOrCreateUserInterface`
  - manual dispatch, mapped to lsteamclient's `Steam_BGetCallback`, `Steam_FreeLastCallback` and
    `Steam_GetAPICallResult`
  - the legacy `CCallback`/`CCallResult` dispatch, using the MSVC vtable layout
  - shutdown
  - game-server entry points, which are stubbed
- **Helpers** ([`steam_api_helpers.cpp`](../src/steam-api/steam_api_helpers.cpp)):
  - the flat accessors (`SteamAPI_SteamUser_v023`, …)
  - `SteamNetworkingIPAddr`/`Identity`/`servernetadr_t` helpers
  - `ISteamNetworkingUtils` inline convenience methods
- **ABI rule.** This DLL is compiled with the Itanium C++ ABI (mingw). It never makes a C++ virtual call.
  All calls into Steam objects go through typed function pointers taken from the MSVC-layout
  vtables.

Env var `STEAMAPI_ARM64_LOG=1` logs init to stderr.

`steam_api64.dll` looks for `lsteamclient_a64.dll` in this order:
1. the name in `STEAMAPI_ARM64_CLIENT_DLL`
2. next to itself
3. `C:\bs-arm64\aarch64-windows\`, the installer's location
4. the normal DLL search path

### OpenXR

**UnityOpenXR.dll.** The Unity OpenXR package (1.14.3, the version the game ships, byte-identical)
contains an ARM64 build only for UWP. [`patch_unityopenxr.py`](../src/unityopenxr/patch_unityopenxr.py)
rewrites three imports so it loads in a desktop process:

- `MSVCP140_APP` → `msvcp140`
- `VCRUNTIME140_APP` → `vcruntime140`
- `api-ms-win-core-libraryloader-l2-1-0!LoadPackagedLibrary` → `kernel32!LoadLibraryW`. Wine's
  `LoadPackagedLibrary` is a stub. The extra `reserved` argument is harmless under the ARM64
  calling convention.

The UWP build loads `openxr_loader.dll` by bare name, so a copy must sit next to the exe.

**openxr_loader.dll.** Khronos publishes no desktop ARM64 loader, so we build 1.1.45 (the game's
version) with llvm-mingw. [Patches](../patches/openxr-loader/0001-wine-arm64-runtime-discovery.patch):

- **Registry lookup.** The loader reads `HKLM\Software\Khronos\OpenXR\1\ActiveRuntimeARM64` before
  `ActiveRuntime`. Proton's `ActiveRuntime` points at the ARM64EC wineopenxr, and Proton rewrites that
  value on every launch.
- **Env override.** The override variable is named `XR_RUNTIME_JSON_ARM64` and isn't dropped for
  "elevated" processes. Every Wine process looks elevated to the loader.
- **MinGW build fixes.** CMake gets the MinGW export fix (`.def` file, static runtime, no `lib`
  prefix) and a missing `<iterator>` include.

**wineopenxr_a64.dll.** This is Proton's wineopenxr Windows half built for pure aarch64, the same way
as lsteamclient. It imports `winevulkan` (ARM64X in Proton) and `dxgi`. Its unix half is a symlink to
Proton's `wineopenxr.so`.

The runtime JSON (`C:\bs-arm64\wineopenxr_a64.json`) points at the DLL by path. The builtin marker
makes Wine resolve it through `WINEDLLPATH` by name, so the name must not be `wineopenxr.dll`.

Building wineopenxr needs Wine's IDL-generated headers (`d3d11.h`, …) and `wine/vulkan.h`. Those come
from Wine's own `widl` and `make_vulkan`, run on the pinned Wine commit.

### Graphics: DXVK

Proton's DXVK in `lib/wine/dxvk/aarch64-windows` is ARM64EC, and Wine's own `d3d11`/`dxgi` (WineD3D)
are ARM64X. WineD3D can boot the game, but it has no DXVK interop, and wineopenxr needs that interop to
share D3D11 textures with Vulkan. `xrCreateSession` then fails with `XR_ERROR_VALIDATION_FAILURE`.

We build DXVK at Proton's commit for aarch64 (DXVK's `DXVK_ARCH_ARM64` code path; x86 intrinsics are
guarded). Only two missing-include fixes for libc++ are needed. `dxgi.dll` and `d3d11.dll` go next to
the exe. The app directory wins over the ARM64EC DXVK that Proton copies into `system32`.

One optimization for the Frame's tiled GPU
([patches/dxvk/0003-discard-resolved-msaa.patch](../patches/dxvk/0003-discard-resolved-msaa.patch)):
Beat Saber draws the whole scene in one pass, 2160×2160 with 2 layers (both eyes) and 2× MSAA, and
resolves it inside the pass. DXVK then still stored the multisampled color and depth to memory, about
150 MB per frame that nothing reads. The patch stores them as `DONT_CARE` when a multisampled pass has a
resolve. `BS_ARM64_KEEP_MSAA=1` restores DXVK's behavior.

With **Screen Distortion** on, Unity resolves the scene for the effect and then keeps drawing on the
multisampled target, so a later pass loads what we discarded. That showed stale images (frozen
menu, ghost sabers) in v0.1.6.
[patches/dxvk/0005-keep-loaded-msaa-targets.patch](../patches/dxvk/0005-keep-loaded-msaa-targets.patch)
remembers which targets were discarded. When a pass loads one of them, DXVK stores that target again
from then on and logs `MSAA: … storing it from now on`. At most one frame shows stale contents.
Without Screen Distortion nothing loads them, and the saving stays.

Foveated rendering is Valve's `fdm_injection` layer, see
[Foveated rendering](#foveated-rendering-valves-fdm_injection).

### MonoPosixHelper.dll

Beat Saber stores beatmaps gzip-compressed and reads them with `System.IO.Compression.GZipStream`.
Unity's Mono implements that via P/Invoke into `MonoPosixHelper.dll` (`CreateZStream`, …). Unity's
ARM64 player doesn't ship one, and the leftover x64 one can't load. The failure is swallowed:
`ReadAllTextFromData` returns null, and the game reports "Could not load readonly beatmap level data"
and returns to the menu.

We build Mono's `support/zlib-helper.c` (Unity's fork) with zlib 1.3.1 and a minimal glib shim
([src/monoposixhelper](../src/monoposixhelper)).

### LIV_Bridge.dll

The game includes the LIV SDK (mixed reality capture). `LIV.dll` P/Invokes `LIV_Bridge`, which
only exists as `Plugins/x86_64/LIV_Bridge.dll`. On ARM64 every call threw `DllNotFoundException`,
about once per frame, and BSIPA logged each one. That cost about 0.6 ms of CPU per frame.

[src/liv-bridge/liv_bridge.c](../src/liv-bridge/liv_bridge.c) exports the same 31 functions, and
each returns 0. `LivCaptureIsActive()` is then false, and the SDK stays idle.

### Microsoft VC++ runtime

`UnityOpenXR` throws and catches a C++ exception when the tracking origin changes (recenter, headset
put on). Wine's ARM64 `__CxxFrameHandler3` (in ucrtbase) dereferences NULL on this MSVC-compiled
code, and the game crashes.

Microsoft's own ARM64 `vcruntime140.dll`/`msvcp140.dll`/`vcruntime140_1.dll`, placed next to the exe,
fix it. They're taken from `vc_redist.arm64.exe` by
[`tools/vcredist_extract.py`](../tools/vcredist_extract.py), which carves the cabinets and unpacks
them with bsdtar.

Fixing Wine's ARM64 C++ EH would remove this dependency (see FINDINGS).

## Mods (BSIPA)

BSIPA works on the ARM64 build once two of its native/low-level pieces are replaced. The
installer does this automatically when it finds BSIPA in the instance (`winhttp.dll`).

**Doorstop (`winhttp.dll`).** BSIPA injects itself through its fork of Unity Doorstop: a `winhttp.dll`
proxy in the game folder. It hooks `GetProcAddress` in `UnityPlayer.dll`'s import table and loads
`IPA.Injector.dll` when Mono initialises. The ARM64 `UnityPlayer.dll` imports `GetProcAddress`,
`GetMessageA`/`PeekMessageA` and `WINHTTP.dll` exactly like x64, so the hooks work unchanged. Only
the binary is x64. We build BSIPA's Doorstop source for ARM64. Its MSVC-specific parts are handled
by [src/doorstop](../src/doorstop):
- **Mini CRT:** Doorstop brings its own, which is renamed so it doesn't clash with the mingw headers.
- **winhttp forwarding stubs:** they're generated as explicit `adrp/add/ldr/br x16` jumps, instead
  of relying on MSVC turning a C call into a tail jump.

`launch` sets `WINEDLLOVERRIDES=winhttp=n,b` so the proxy in the game folder is used.

**MonoMod.Core (Harmony).** Harmony 2.x patches methods through MonoMod.Core 1.3.3, which already has
an ARM64 detour backend. Its `WindowsSystem` only defines the default calling convention for x86 and
x64, so on Windows ARM64 it throws `Cannot use Mono system, because the underlying system doesn't
provide a default ABI!`.

[The fix](../patches/monomod/0001-windows-arm64-default-abi.patch) gives Windows ARM64 the same ABI
description MonoMod uses on Linux and macOS ARM64. For Mono's own code, Windows ARM64 follows
AAPCS64: `this` in x0, the return buffer in x8, and the same type classification.

We rebuild MonoMod.Core from the exact commit BSIPA ships (`1.3.3+aa4a84749`, net452) with that
change. The assembly identity (version, unsigned, references) is unchanged, so Harmony binds to it as
is. The installer only replaces a `Libs/MonoMod.Core.dll` of that exact version. This belongs
upstream in MonoMod.

**BSIPA's anti-piracy check.** `AntiPiracy.IsInvalid` refuses to load if any file whose name
contains "steam" is 350 KB or larger in the game folder or `Beat Saber_Data/Plugins`. That heuristic
catches Steam emulators. Our DLLs are not emulators: they go through the real Steam client and its
ownership check. We keep them out of the heuristic's range legitimately:
- `lsteamclient_a64.dll` lives only in the prefix runtime directory, `C:\bs-arm64\aarch64-windows`.
  `steam_api64.dll` looks for it there.
- `steam_api64.dll` is 91 KB: no C++ runtime, `-Os`, stripped. The real x64 one is 319 KB.
  `build.sh` fails if it grows to 350 KB.

## Wine prefix and launch environment

The installer ([install/bs-arm64.sh](../install/bs-arm64.sh)) adds these to the prefix:

- `pfx/drive_c/bs-arm64/` (`C:\bs-arm64`), used as `WINEDLLPATH`:
  - `aarch64-windows/lsteamclient_a64.dll`, `aarch64-windows/wineopenxr_a64.dll`
  - `aarch64-unix/lsteamclient_a64.so`, `aarch64-unix/wineopenxr_a64.so`: symlinks into Proton
  - `wineopenxr_a64.json`
  - `proton-version`: the Proton build the halves must match
- registry: `HKLM\Software\Khronos\OpenXR\1` `ActiveRuntimeARM64` = `C:\bs-arm64\wineopenxr_a64.json`

An install from 0.2.0 or older also removes the old eye-tracking layer
(`XrApiLayer_bs_arm64_gaze`) and its registry entry.

The launch environment adds only `WINEDLLPATH=<prefix>/pfx/drive_c/bs-arm64` and the variables for
Valve's foveated rendering layer (below) to the usual Proton and Steam variables.

## Foveated rendering: Valve's fdm_injection

SteamOS ships Valve's foveated rendering as one library, `libVkLayer_VALVE_fdm_injection.so`, with two
halves:
- an **implicit OpenXR layer** (`XR_APILAYER_VALVE_fdm_injection`), active in every OpenXR app unless
  `DISABLE_VULKAN_FDM_INJECTION_LAYER` is set. It watches the swapchains and gets the eye-tracked
  foveation state from SteamVR.
- an **explicit Vulkan layer** (`VK_LAYER_VALVE_fdm_injection`), which attaches a fragment density map
  to the eye passes. Here that's DXVK's Vulkan device, so it works for the ARM64 build as for x64.

With Beat Saber's **Foveated Rendering** switch on, Steam starts the game with
`FDM_DEBUG=enable` and `VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection`. Outside
Steam neither is set, only the OpenXR half loads, and `vkCreateDevice` spins forever. So every launch
needs one of:

| Want | Environment |
|---|---|
| foveated rendering | `FDM_DEBUG=enable` + `VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection` |
| none | `DISABLE_VULKAN_FDM_INJECTION_LAYER=1` |

The OpenXR loader only checks whether `DISABLE_VULKAN_FDM_INJECTION_LAYER` exists, so an empty value
still disables it. `bs-arm64.sh launch` sets the second row, or the first with `--foveation`.

`FDM_DEBUG` is a flag list (`FDM_DEBUG=help` prints it): `enable`; presets `lo`, `med`, `hi`
(`hi` is the strongest foveation, the default is about `lo`); `zero` (zero density outside the view);
`disable_offsets`, `disable_layered`, `yflip`, `debug`. `VK_LAYER_VALVE_rpo` is a second Valve layer
Steam loads with it. The layer logs to stderr (`fdm_injection: created fdm views for size …`).

Up to 0.2.0, bs-arm64 had its own foveated rendering in DXVK plus an OpenXR layer for the eye data.
Valve's layer was faster (FINDINGS), so it was removed.

The loader's `XR_RUNTIME_JSON_ARM64` override did not take effect in our tests, even though other
variables such as `DXVK_LOG_LEVEL` reach the game. The cause hasn't been investigated, so the
registry value is what's actually used.

The Windows halves of lsteamclient and wineopenxr must match Proton's unix halves exactly: the
parameter structs and call numbers are generated per Proton version. `launch` refuses to start if
Proton was updated after install. Rebuild from the new Proton tag and reinstall.
