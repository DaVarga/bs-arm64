# Changelog

All notable changes to bs-arm64. Each release is built for one Proton build (see its release notes).

## [0.2.2] – 2026-10-04

### Changed
- The C++ runtime next to the game is now Wine's own, built from the matching Proton source with
  Wine's fix for the ARM64 exception-handling crash ([bug 60399](https://bugs.winehq.org/show_bug.cgi?id=60399),
  merged upstream as [6964eb2](https://github.com/wine-mirror/wine/commit/6964eb2b018a9029b561124269e7ceec5bde8086))
  backported. It installs `ucrtbs64.dll`, `vcruntime140.dll` and `msvcp140.dll` only in the ARM64
  instance; the prefix, other games and BSManager's launch settings are unchanged.
- Mods use the unmodified upstream MonoMod.Core 1.3.4, which has the Windows ARM64 ABI, instead of
  our patched rebuild of 1.3.3. The installer upgrades BSIPA's 1.3.3 and earlier bs-arm64 builds.
- Reinstalling over an earlier release swaps the runtimes and keeps the original backups; uninstall
  restores them. The `vcruntime140_1.dll` earlier releases installed is removed.
- The installer checks the Wine prefix and Proton before changing the instance, so a missing prefix
  no longer leaves it half installed.

### Removed
- The Microsoft VC++ ARM64 runtime download (`fetch` no longer needs it) and `vcredist_extract.py`.
- The local MonoMod patch; building no longer needs a .NET SDK.
- The Wine C++ exception-handling reproducer (`tools/repro/cxx-eh`); it is attached to the Wine bug.

### Docs
- [UPSTREAM.md](docs/UPSTREAM.md): the Wine and MonoMod bugs are fixed upstream; what we carry until
  Proton and BSIPA pick the fixes up.

## [0.2.1] – 2026-09-30

### Changed
- Foveated rendering now uses SteamVR's own (Valve's `fdm_injection` layer), the same one Steam turns
  on for the x64 game, instead of our DXVK implementation. It follows the eyes too and is cheaper:
  GPU 2.92 vs 3.16 ms and CPU 4.70 vs 5.37 ms per frame compared to 0.2.0's (STARLIGHT, 1776 px per
  eye, no MSAA). Steam's Foveated Rendering switch turns it on through BSManager v1.6.0-frame.4 or
  later; by hand, `bs-arm64.sh launch --foveation`. `FDM_DEBUG=enable,med` or `enable,hi` foveates
  more than Steam's mild default.
- The installer removes 0.2.0's eye-tracking OpenXR layer from the Wine prefix.

### Removed
- Our own fixed and eye-tracked foveated rendering (`BS_ARM64_FDM`, `BS_ARM64_FDM_*`) and
  `XrApiLayer_bs_arm64_gaze.dll`.

### Docs
- What trips up a first install on a fresh Frame, and a list of upstream bugs we work around
  ([UPSTREAM.md](docs/UPSTREAM.md)), including why Valve's layer hangs games started outside Steam.
- AssetBundleLoadingTools' multi-pass mode draws everything twice; check it when copying `UserData`
  from Windows.

## [0.2.0] – 2026-09-27

### Added
- Eye-tracked foveated rendering: the sharp area follows your eyes using SteamVR's eye tracking.
  Turn it on in Steam (Beat Saber → ⚙ → Properties → Performance → Foveated Rendering); BSManager reads
  that switch when it starts the game. With a manual install, start the game with `BS_ARM64_FDM=1`. A new OpenXR layer (`XrApiLayer_bs_arm64_gaze.dll`,
  registered by the installer, loaded only when foveated rendering is on) reads the gaze, and DXVK
  gives each eye its own density map around it. Without eye tracking the fixed profile applies.
  GPU time 4.2 → 3.6 ms per frame and system power 15.6 → 14.3 W compared to the fixed profile
  (4.8 ms / 16.7 W without foveated rendering; 2160, 120 Hz).
- `BS_ARM64_FDM_GAZE_*` variables for the sharp radius and the gaze correction, plus a debug
  crosshair (`BS_ARM64_FDM_GAZE_CROSSHAIR=1`), see [ARCHITECTURE.md](docs/ARCHITECTURE.md#graphics-dxvk).

## [0.1.7] – 2026-09-27

### Fixed
- Frozen ghost images of the menu and sabers with **Screen Distortion** on (since 0.1.6). For the
  effect the game keeps drawing on its multisampled scene after resolving it, which the 0.1.6
  optimization had already discarded. DXVK now stores such a target again once a later pass loads it;
  without Screen Distortion the saving stays.

### Added
- Optional fixed foveated rendering for the Frame's GPU: start the game with `BS_ARM64_FDM=1` and DXVK
  renders the edges of each eye at lower resolution. GPU time 4.8 → 4.2 ms per frame, system power
  16.7 → 15.4 W (2160, 120 Hz, MSAA on). Radius and densities are set with `BS_ARM64_FDM_*`
  variables, see [ARCHITECTURE.md](docs/ARCHITECTURE.md#graphics-dxvk). Off by default.

### Changed
- README: turn off Screen Distortion (expensive on the Frame's GPU), and where the Adaptive SFX
  setting is (Solo → song selection → Player Settings tab).

## [0.1.6] – 2026-09-27

### Changed
- DXVK doesn't store multisampled render targets after resolving them inside the render pass. Beat
  Saber resolves its 2× MSAA scene that way, so on the Frame's tiled GPU this saves writing about
  150 MB per frame: GPU time 6.3 → 4.8 ms per frame, system power 17.6 → 16.7 W (2160, 120 Hz).
  Anti-aliasing is unchanged. `BS_ARM64_KEEP_MSAA=1` restores DXVK's behavior.

## [0.1.5] – 2026-09-27

### Fixed
- Install right after installing BSIPA failed with "still running": the installer now waits up to
  30 s for Wine's helper processes to exit, and names the programs still running if they don't.

## [0.1.4] – 2026-09-27

### Added
- ARM64 `LIV_Bridge.dll` stub. The game's LIV SDK (mixed reality capture) only ships an x64 bridge,
  so every frame threw `DllNotFoundException` and BSIPA logged it. About 0.6 ms less CPU per frame and
  steadier frame times. LIV capture itself is still not available.
- Tip in the README: turn off **Adaptive SFX** in the player settings; its loudness measurement is
  expensive on ARM64.

### Fixed
- Install and uninstall stop with a message instead of hanging when the Wine prefix is in use (game
  still running, or a Wine process left over from an earlier launch).

## [0.1.3] – 2026-09-26

### Fixed
- A version freshly downloaded in BSManager was rejected as "Beat Saber unknown": the installer now
  reads the game version from `globalgamemanagers`, as BSManager does, instead of
  `BeatSaberVersion.txt`, which only exists after BSIPA ran.

### Changed
- README links the Steam Frame install guide at the top.

## [0.1.2] – 2026-09-26

### Changed
- README, INSTALL.md and the release notes point to the Steam Frame BSManager fork, whose ARM64 tab
  runs this installer.
- The installer prints its "start with" hint only when run from a terminal.

### Fixed
- Uninstall no longer brings BSIPA's Doorstop back if BSIPA was removed in between.

## [0.1.1] – 2026-09-26

### Added
- `install --no-mods`: install only the ARM64 engine and leave BSIPA's files alone.
- `launch --no-mods`: start once without mods.

## [0.1.0] – 2026-09-26

First release: Beat Saber 1.44.1 as a native Windows ARM64 program on Proton 11.0 (ARM64), with
Steam, OpenXR on SteamVR and BSIPA mods.

- Unity's Windows ARM64 player, downloaded by the installer together with Unity's OpenXR plugin and
  Microsoft's ARM64 VC++ runtime.
- `steam_api64.dll`: Steamworks flat API on top of Proton's lsteamclient, built for ARM64.
- `lsteamclient_a64.dll`, `wineopenxr_a64.dll`: Proton's Windows halves, built for pure ARM64.
- Patched Khronos OpenXR loader, import-patched UnityOpenXR.
- DXVK and `MonoPosixHelper.dll` for ARM64.
- Mods: BSIPA's Doorstop (`winhttp.dll`) for ARM64, and MonoMod.Core with a Windows ARM64 ABI so
  Harmony can patch.
- Release packaging and GitHub workflow; the installer refuses other Proton builds.

[0.2.2]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.2.2
[0.2.1]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.2.1
[0.2.0]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.2.0
[0.1.7]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.7
[0.1.6]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.6
[0.1.5]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.5
[0.1.4]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.4
[0.1.3]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.3
[0.1.2]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.2
[0.1.1]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.1
[0.1.0]: https://github.com/DaVarga/bs-arm64/releases/tag/v0.1.0
