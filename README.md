# bs-arm64: native ARM64 Beat Saber on Proton

> [!NOTE]
> The easiest way to get this running on your Frame is the Frame-compatible BSManager fork, which
> installs it with one click.
> **[How to install on the Steam Frame](https://github.com/DaVarga/bs-manager/blob/bs-arm64/docs/steam-frame.md)**

Run Beat Saber as a **native Windows ARM64** program on ARM64 Linux under Proton, tested on the
**Steam Frame**, instead of emulating the x64 build with FEX. Every game version on Unity 6000.0.40f1
works, which means 1.40.9 through 1.44.1 (see [Game versions](#game-versions)).

The game's engine and C# code both run natively. Only Proton's small `steam.exe` launcher stays x64.

## Results on the Steam Frame

Beat Saber 1.44.1, the same replay (STARLIGHT, Expert+) five times on each build, 2160 × 2160 per eye
at 120 Hz, with reduced graphics settings (anti-aliasing 2×, Bloom, mirror, smoke and Screen
Distortion off):

| | Native ARM64 | x64 via FEX |
|---|---|---|
| Frame rate | ~120 fps | ~104 fps |
| Reprojected frames (SteamVR) | 1.0 % | 30.9 % |
| App CPU time per frame | 4.2 ms | 8.4 ms |
| System power | 14.4 W | 19.2 W |

With the game's default graphics settings the GPU is the limit on both builds (~39 fps each), so lower
those first.

## Tips

- Turn off **Adaptive SFX** (Solo → song selection → **Player Settings** tab). On ARM64 its loudness
  measurement takes most of the audio thread; with it off, 30 % fewer slow frames. Hit sounds then no
  longer adapt to the song's loudness.
- Turn off **Screen Distortion** in the graphics settings. It costs a lot of GPU time on the Frame.

## Foveated rendering (optional)

bs-arm64 uses SteamVR's own foveated rendering, the same one Steam turns on for the x64 game. Turn on
Beat Saber's **Properties** → **Performance** → **Foveated Rendering** in Steam; `bs-arm64.sh launch`
follows it (`--foveation` / `--no-foveation` override it). With the Frame's eye tracking, the sharp
area follows your eyes. Steam's default strength is mild; `FDM_DEBUG=enable,hi` saves more GPU time.

AssetBundleLoadingTools' **Enable Multi-Pass Rendering** turns foveated rendering off. Check it when
you copy `UserData` over from a Windows install.

## What works

| Area | Status |
|---|---|
| Menu, maps (official), audio, visuals | ✅ |
| Steam (login, ownership, platform init, online services) | ✅ |
| OpenXR on SteamVR, controllers, recenter | ✅ |
| Mods: BSIPA 4.3.7 + Harmony (tested: SiraUtil, BSML, SongCore, BS Utils) | ✅ on 1.41.1 and later |
| Burst-compiled code | ⚠️ runs as managed code (no ARM64 Burst library) |
| LIV mixed-reality capture | ❌ not available |

## Game versions

The native runtime depends on the game's Unity engine, not on its version. Tested on the Frame, to the
main menu with Steam and VR:

| Beat Saber | Without mods | With mods |
|---|---|---|
| 1.40.8 and older | ❌ Unity 2022.3.33f1, the installer refuses it | |
| 1.40.9 – 1.40.13 | ✅ | BeatMods has no mods for these versions |
| 1.41.1 – 1.44.1 | ✅ | ✅ |

## How it works

The ARM64 player comes from the same Unity version the game was built with. Every native piece around
it that only existed as x64 or ARM64EC (Steam API, OpenXR, DXVK, the mod loader, ...) has an ARM64
replacement, built from source here. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

With a launcher: the [BSManager fork](https://github.com/DaVarga/bs-manager)'s **ARM64 tab** installs
the release matching your Proton version (see the note at the top).

By hand, on the device, with **Proton 11.0 (ARM64)** installed from Steam (Library → Tools): download
the release tarball for your Proton version from the
[releases page](https://github.com/DaVarga/bs-arm64/releases), then:

```sh
tar xf bs-arm64-*.tar.gz && cd bs-arm64-*/
./bs-arm64.sh install <instance>   # also downloads Unity's ARM64 player
./bs-arm64.sh launch  <instance>
./bs-arm64.sh uninstall <instance> # restores the x64 files
```

`<instance>` is the folder of a Beat Saber install (e.g. a BSManager instance); work on a copy. For a
bug report, paste the output of `./bs-arm64.sh doctor <instance>`. To build it yourself, see
[docs/BUILD.md](docs/BUILD.md).

## Docs

- [docs/INSTALL.md](docs/INSTALL.md): the installer, what it changes, launching, troubleshooting
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): every component, and why it's needed
- [docs/BUILD.md](docs/BUILD.md): building and releasing
- [docs/UPSTREAM.md](docs/UPSTREAM.md): bugs in other projects we work around
- [docs/LEGAL.md](docs/LEGAL.md): licenses, and what may or may not be redistributed

## License

MIT (see [LICENSE](LICENSE)) for the original code. The patches follow their upstream licenses. This
project is unofficial and not affiliated with Beat Games, Valve or Unity. See
[docs/LEGAL.md](docs/LEGAL.md).
