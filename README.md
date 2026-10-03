# bs-arm64: native ARM64 Beat Saber on Proton

> [!NOTE]
> The easiest way to get this running on your Frame is the Frame-compatible BSManager fork, which
> installs it with one click.
> **[How to install on the Steam Frame](https://github.com/DaVarga/bs-manager/blob/bs-arm64/docs/steam-frame.md)**

Run Beat Saber as a **native Windows ARM64** program on ARM64 Linux under Proton, tested on the
**Steam Frame**, instead of emulating the x64 build with FEX. Any game build on the same Unity engine
(6000.0.40f1) works, which today means 1.42.x through 1.44.1; the benchmarks below are from 1.44.1.

The game's engine and C# code both run natively. Only Proton's small `steam.exe` launcher stays x64.

## Results on the Steam Frame

Numbers come from SteamVR's per-session compositor stats, at a 120 Hz target:

| Build | App CPU / frame | App GPU / frame | Frames reprojected |
|---|---|---|---|
| x64 1.44.1 via FEX (73k frames) | 7.8 ms | 6.6 ms | 26 % |
| x64 1.44.1 via FEX (50k frames) | 8.8 ms | 7.8 ms | 34 % |
| **native ARM64 1.44.1 (76k frames)** | **3.3 ms** | **3.3 ms** | **1.3 %** |

With FEX, the retail game ran at about 90 fps and dipped to about 55. With the native build, the frame drops are gone.

A CPU micro-benchmark run inside the game's Mono runtime shows the same thing: native code is
2–3× faster than FEX-translated x64 on everything except `Vector3` math (see
[docs/FINDINGS.md](docs/FINDINGS.md#benchmark)).

## Tip: turn off Adaptive SFX

Turn off **Adaptive SFX**: Solo → song selection → **Player Settings** tab in the panel next to the song
list (not the main menu's Options). It measures the song's loudness on the audio thread with thousands
of `Math.Pow` calls per second. On x64 that's cheap; on ARM64, Mono's `pow` is
slow and the measurement takes most of the audio thread. With it off, frame times were steadier in a
replay benchmark: 30 % fewer frames over 9.5 ms at 120 Hz. The trade-off: hit sounds no longer adapt
to the song's loudness. See [docs/FINDINGS.md](docs/FINDINGS.md#frame-pacing).

## Tip: turn off Screen Distortion

In the game's graphics settings, turn off **Screen Distortion**. For the effect, the game copies the
whole scene in the middle of every frame and keeps drawing on it, which costs a lot of GPU time on the
Frame's tiled GPU. In v0.1.6 it also caused frozen ghost images of the menu and sabers.

## Foveated rendering (optional)

With foveated rendering the Frame's GPU renders the area you look at in full resolution and the edges
at lower resolution. bs-arm64 uses SteamVR's own foveated rendering (Valve's `fdm_injection` layer),
the same one Steam turns on for the x64 game with **Properties** → **Performance** → **Foveated
Rendering**. With SteamVR's eye tracking the sharp area follows your eyes.

By hand, start the game with `bs-arm64.sh launch --foveation`. That sets what Steam sets:
`FDM_DEBUG=enable` and `VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection`. Steam's
default is mild; `FDM_DEBUG=enable,med` or `FDM_DEBUG=enable,hi` saves more and is easier to notice.
BSManager's ARM64 tab doesn't set these yet.

| STARLIGHT replay, 1776 px per eye, no MSAA, 120 Hz | GPU / frame | CPU / frame | System power |
|---|---|---|---|
| off | 3.83 ms | 5.28 ms | 17.7 W |
| default | 2.92 ms | 4.70 ms | 15.7 W |
| `hi` | 2.64 ms | 4.62 ms | 15.2 W |

One run each, headset off (no eye movement). bs-arm64 0.2.0's own foveated rendering got 3.16 ms GPU
and 5.37 ms CPU in the same test, so it was removed.

AssetBundleLoadingTools' **Enable Multi-Pass Rendering** (Mod Settings, or `EnableMultiPassRendering`
in `UserData/AssetBundleLoadingTools.json`) makes the game draw everything twice, once per eye. It
also kept 0.2.0's foveated rendering off; Valve's layer hasn't been tried with it. Check it when you
copy `UserData` over from a Windows install.

## What works

| Area | Status |
|---|---|
| Menu, maps (official), audio, visuals | ✅ |
| Steam (login, ownership, platform init, online services) | ✅ |
| OpenXR on SteamVR, controllers, recenter | ✅ |
| Burst-compiled code | ⚠️ x64 `lib_burst_generated.dll` can't load; Unity falls back to managed code |
| LIV mixed-reality capture | ❌ not available (a stub `LIV_Bridge.dll` reports "no capture") |
| Mods: BSIPA 4.3.7 + Harmony (tested: SiraUtil, BSML, SongCore, BS Utils) | ✅ with the ARM64 Doorstop + upstream MonoMod.Core 1.3.4 |
| Game versions | ✅ any build on Unity 6000.0.40f1 (1.42.x through 1.44.1); other engines unsupported |

## How it works

The ARM64 player comes from the same Unity version the game was built with (6000.0.40f1). Every native
piece around it that only existed as x64 or ARM64EC has an ARM64 replacement. Details are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Piece | Source |
|---|---|
| Unity player, `UnityPlayer.dll`, Mono runtime | Unity's official Windows ARM64 player (downloaded) |
| `steam_api64.dll` | **new**: Steamworks SDK 1.61 flat API ([src/steam-api](src/steam-api)) |
| `lsteamclient_a64.dll` | Proton's lsteamclient, Windows half, rebuilt for pure aarch64 |
| `wineopenxr_a64.dll` | Proton's wineopenxr, Windows half, rebuilt for pure aarch64 |
| `openxr_loader.dll` | Khronos loader 1.1.45, patched ([patches/openxr-loader](patches/openxr-loader)) |
| `UnityOpenXR.dll` | Unity's UWP ARM64 build, imports patched for desktop ([src/unityopenxr](src/unityopenxr)) |
| `dxgi.dll`, `d3d11.dll` | DXVK at Proton's commit, built for aarch64 ([patches/dxvk](patches/dxvk)) |
| `MonoPosixHelper.dll` | Mono's zlib helper + zlib; Unity doesn't ship one for ARM64 |
| `ucrtbs64.dll`, `vcruntime140.dll`, `msvcp140.dll` | private Wine ARM64 C++ runtime, built from the matching Proton source with the upstream exception-handling fix ([patches/wine](patches/wine)) |
| `winhttp.dll` (mods) | BSIPA's Doorstop injector, rebuilt for ARM64 ([src/doorstop](src/doorstop)) |
| `Libs/MonoMod.Core.dll` (mods) | unmodified upstream MonoMod.Core 1.3.4, which includes Windows ARM64 support |

## Quick start

### With BSManager (easiest)

The Steam Frame fork of BSManager, [DaVarga/bs-manager](https://github.com/DaVarga/bs-manager)
(ARM64 AppImage on its releases page), fixes BSManager for ARM64 Proton and adds an **ARM64 tab**
next to Mods for 1.44.1 instances. That tab downloads the release matching your Proton build and
installs, reinstalls or removes it, with or without mod support. It also re-applies the ARM64 mod
loader fixes after BSIPA is installed, and sets up the launch environment.

Follow its [Steam Frame guide](https://github.com/DaVarga/bs-manager/blob/bs-arm64/docs/steam-frame.md).
On a fresh Frame, three things trip people up:
- Install **Proton 11.0 (ARM64)** (and **Steam Linux Runtime 4.0 for arm64**) from the Steam library
  (Tools) first; BSManager asks for the Proton folder.
- Add `DISABLE_VULKAN_FDM_INJECTION_LAYER=1 %command%` as launch command in BSManager. Without it the
  game hangs at startup: Valve's foveated rendering layer is half on outside Steam. For foveated
  rendering in the x64 game, use
  `FDM_DEBUG=enable VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection %command%`
  instead.
- Launch 1.44.1 once before clicking Install in the ARM64 tab. That creates BSManager's Wine prefix.
  If Install already failed with `Wine prefix … does not exist`, the version is left half changed;
  launch another version once, then click Install again.

### By hand

On the Steam Frame, with BSManager, a Unity 6000.0.40f1 instance (1.42.x or 1.44.1), and
"Proton 11.0 (ARM64)" (the install guard checks the instance's Unity engine, not its game version):

Download the release tarball that matches your Proton version (`<Proton dir>/version`) from the
[releases page](https://github.com/DaVarga/bs-arm64/releases), then on the Frame:

```sh
tar xf bs-arm64-*.tar.gz && cd bs-arm64-*/
./bs-arm64.sh install ~/.local/share/BSManager/BSInstances/1.44.1   # downloads the Unity player etc.
./bs-arm64.sh launch  ~/.local/share/BSManager/BSInstances/1.44.1
```

Or build it yourself:

```sh
# 1. build the open-source parts (any Linux host, x86_64 or aarch64); see docs/BUILD.md
./build.sh
# 2. copy the repo (with out/) to the Frame, then there:
install/bs-arm64.sh install ~/.local/share/BSManager/BSInstances/1.44.1
install/bs-arm64.sh launch  ~/.local/share/BSManager/BSInstances/1.44.1
# undo:
install/bs-arm64.sh uninstall ~/.local/share/BSManager/BSInstances/1.44.1
```

See [docs/INSTALL.md](docs/INSTALL.md) for every file that gets touched.

> **Status:** verified end to end on the Frame. A clean `build.sh` output was installed with
> `install/bs-arm64.sh` into a fresh copy of a BSManager 1.44.1 instance: Steam, VR and maps all work.
> The same runtime also installs on 1.42.x instances, since they share the 6000.0.40f1 engine.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): every component, and why it's needed
- [docs/BUILD.md](docs/BUILD.md): build requirements and steps
- [docs/INSTALL.md](docs/INSTALL.md): what the installer changes, launching, uninstalling
- [docs/FINDINGS.md](docs/FINDINGS.md): the debugging path, pitfalls, and the benchmark
- [docs/LEGAL.md](docs/LEGAL.md): licenses, and what may or may not be redistributed

## License

MIT (see [LICENSE](LICENSE)) for the original code. The patches follow their upstream licenses. This
project is unofficial and not affiliated with Beat Games, Valve or Unity. See
[docs/LEGAL.md](docs/LEGAL.md).
