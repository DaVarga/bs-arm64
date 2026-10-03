# Licensing and redistribution

Licenses, source origins, and redistribution boundaries for the repository and release packages.

## What this repository contains

Only original code, patches, and scripts. It holds **no** third-party binaries, and no third-party
source except what the build downloads from upstream.

| Path | Origin | License |
|---|---|---|
| `src/steam-api/*` | original; generates code from Steamworks SDK headers **at build time**, taken from the Proton checkout | MIT |
| `src/unityopenxr/patch_unityopenxr.py`, `tools/*`, `install/*`, `build.sh` | original | MIT |
| `src/monoposixhelper/glib.h`, `config.h` | original shim | MIT |
| `patches/openxr-loader/*` | changes to the Khronos OpenXR-SDK | Apache-2.0 (upstream) |
| `patches/dxvk/*` | changes to DXVK | zlib (upstream) |
| `patches/wine/*` | upstream exception fix + changes to build the private runtime | LGPL-2.1+ (Wine) |
| `src/doorstop/*` | build glue + stub generator for BSIPA's Doorstop | MIT (Doorstop itself: CC0) |

The Steamworks SDK headers aren't copied into this repo. The build reads them from Proton's public
repository, which carries them in `lsteamclient/steamworks_sdk_*`. `sdk_inline_impl.inc` and
`flat_generated.cpp` are generated into `obj/` and are not committed.

## What the build produces (`out/`)

| File | Built from | License |
|---|---|---|
| `lsteamclient_a64.dll`, `wineopenxr_a64.dll` | Proton sources + Wine (`winecrt0`) | LGPL-2.1+ (Wine/Proton), BSD-3 for some Proton parts; see Proton's `LICENSE` |
| `ucrtbs64.dll`, `vcruntime140.dll`, `msvcp140.dll` | pinned Proton Wine + `patches/wine`; private runtime statically includes musl | LGPL-2.1+ (Wine); musl MIT notices in `licenses/musl-COPYRIGHT` |
| `openxr_loader.dll` | Khronos OpenXR-SDK | Apache-2.0 |
| `dxgi.dll`, `d3d11.dll` | DXVK | zlib |
| `MonoPosixHelper.dll` | Mono `zlib-helper.c` (MIT) + zlib (zlib) | MIT + zlib |
| `steam_api64.dll` | this project | MIT |
| `winhttp.dll` | BSIPA's Doorstop (CC0) + this project's glue | CC0 / MIT |
| `MonoMod.Core.dll` | unmodified upstream MonoMod.Core 1.3.4 NuGet package (`net452`) | MIT |

Anyone distributing the built binaries must follow those licenses. For the LGPL parts, that means
offering the corresponding source; pointing to the pinned upstream tags plus this repo does that.

`lsteamclient_a64.dll` and `steam_api64.dll` are compiled against the Steamworks SDK headers that
Proton carries. Proton ships those under the Steamworks SDK license (`lsteamclient/LICENSE`) and
distributes its own `lsteamclient` builds publicly; this project does the same.

## Releases

`./build.sh package` (and the GitHub release workflow) bundles exactly the files above, with
`licenses/` holding each upstream license (Proton, the Steamworks SDK license, Wine's LGPL, DXVK and
its submodules, OpenXR-SDK, zlib, Mono, Doorstop, MonoMod, llvm-mingw's runtime) and `SOURCES.md`
linking the exact upstream sources and this repository's commit. Nothing from the next table is in a
release.

## What is downloaded on the user's machine and never redistributed

| File | Source | Why it isn't redistributed |
|---|---|---|
| Unity Windows ARM64 player (`WindowsPlayer.exe`, `UnityPlayer.dll`, `UnityCrashHandler64.exe`, `mono-2.0-bdwgc.dll`) | Unity's download CDN | Unity runtime binaries: the Unity licence lets them ship inside a game built by a Unity licensee, not on their own |
| `UnityOpenXR.dll` (ARM64) | Unity package registry, com.unity.xr.openxr 1.14.3 | Unity Companion License; patched locally |

`install/bs-arm64.sh fetch` downloads and patches these on the user's machine.

## The game

Beat Saber's files, and the user's ownership of the game, are required and are verified through Steam
as usual. The install **replaces the game's engine binaries** in a local copy; no game data or code is
changed. The project is unofficial and is not affiliated with Beat Games. "Beat Saber" is a trademark
of Beat Games.

## Project license

The original code in this repository is MIT licensed (see [LICENSE](../LICENSE)). The patches in
`patches/` fall under the licenses of the projects they modify.
