# Findings and pitfalls

This is roughly the order the work happened in, on a Steam Frame (SteamOS "vr" 0.3.0, Snapdragon /
Adreno 750 with Turnip, Proton 11.0-2c ARM64, Beat Saber 1.44.1).

## Why go native

- With FEX, retail 1.45.1 ran at about 86–106 fps with 1 % lows around 55. 1.44.1 through BSManager
  was similar. Lowering the resolution barely helped: the game is CPU-bound.
- `perf` on gameplay showed:
  - the main thread takes about 51–56 % of process samples
  - 83–87 % of the main thread is `[anon:FEXMemJIT]` (translated code), and 3–5 % is FEX itself
  - about 25 % of the process was already native (DXVK, the driver)
- FEX's `TSOEnabled:0` crashes the game. TSO has to stay on.

## Benchmark

`Bench.dll` is a netstandard2.1 assembly. It's injected through `RuntimeInitializeOnLoads.json`
(`loadTypes: 2`, AfterAssembliesLoaded) and `ScriptingAssemblies.json` (type 16), so the game itself
isn't modified. Each workload gets a warm-up run and 5 timed runs; the best is kept. Numbers are in
ms, lower is better.

| Workload | x64 via FEX | native ARM64 | Speed-up |
|---|---|---|---|
| Vector3 math (4M) | 740.5 | 704.2 | 1.05× |
| Quaternion/Matrix4x4 (1M) | 688.8 | 329.3 | 2.09× |
| Mathf trig/sqrt (6M) | 785.1 | 264.6 | 2.97× |
| allocation + GC (3M objects) | 932.6 | 338.1 | 2.76× |
| Dictionary/List (20×50k) | 87.6 | 42.2 | 2.08× |
| interface/virtual calls (8M) | 224.0 | 73.9 | 3.03× |
| strings (200k) | 366.6 | 193.4 | 1.90× |

The geometric mean is about 2.15×. The Vector3 loop produced NaNs, which likely distorted that row.

In the game, app CPU time per frame went from 7.8–8.8 ms to 3.3 ms (see the README).

## Steam bridge

- Proton ARM64's `lsteamclient.dll` and DXVK in the `aarch64-windows` folders have PE machine
  `0x8664`. That makes them **ARM64EC**, not ARM64X. A pure ARM64 process can't use them.
- Wine loads a DLL's unix half only for *builtin* modules found through its DLL paths. Two
  consequences:
  - A builtin-marked file placed anywhere triggers a builtin lookup by name through `dll_paths`.
  - A DLL named only in `WINEDLLPATH` isn't found by `LoadLibrary("name.dll")` (outside prefix
    bootstrap). A builtin-marked copy has to sit on the normal search path.
- `dll_paths` puts Proton's `lib/wine` before `WINEDLLPATH`. Proton's ARM64EC module of the **same
  name** gets mapped into the ARM64 process and then fails `DllMain`. That's why the ARM64 modules are
  named `*_a64`.
- lsteamclient's Windows half compiles for `__aarch64__` unchanged. It only needs Wine's headers,
  `winecrt0/unix_lib.c` and a few ntdll imports (`__wine_dbg_*`, `__wine_unix_call_dispatcher`).
- Smoke test result (pure ARM64 exe on the Frame):
  `pipe 1 user 1 / steamid 7656119… / loggedon 1 / appid 620980 / persona name`.
- The ARM64 Unity player loads native plugins from `Plugins/ARM64/`. With the DLL still in
  `Plugins/x86_64/`, you get `DllNotFoundException: steam_api64` even when the DLL is fine.

## OpenXR

- Unity OpenXR 1.14.3 is byte-identical to the game's plugin. Its only ARM64 binary is the UWP one
  (`MSVCP140_APP`, `VCRUNTIME140_APP`, `LoadPackagedLibrary`, WinRT imports). Wine's `msvcp140` and
  `vcruntime140` export every symbol it imports, and Wine's WinRT API sets are enough for it to load.
- The UWP plugin loads `openxr_loader.dll` by bare name. That searches the exe's directory, not
  `Plugins/ARM64`.
- Khronos ships no desktop ARM64 loader (only `ARM64_uwp`). The loader source needs one `<iterator>`
  include for libc++, plus a CMake fix, because the version script is GNU-only.
- Proton's `ActiveRuntime` JSON points to `C:\windows\system32\wineopenxr.dll`, a symlink to the
  ARM64EC build (`c000007b` / "Bad EXE format"). Hence `ActiveRuntimeARM64`.
- The loader ignores `XR_RUNTIME_JSON` in "high integrity" processes, and under Wine every process
  counts as high integrity. The renamed ARM64 override is exempt from that check, but in the game it
  still didn't take effect; the registry value is what works.
- Building wineopenxr needs `wine/vulkan.h` (`dlls/winevulkan/make_vulkan -x vk.xml -X video.xml`) and
  IDL headers (`d3d11.h` …) from Wine's `widl`. Mixing in mingw-w64's headers fails, because
  `WINBOOL` and `SECURITY_ATTRIBUTES` conflict with Wine's.
- With WineD3D, the session fails with `xrCreateSession: XR_ERROR_VALIDATION_FAILURE`, because
  wineopenxr's D3D11 path needs DXVK interop. With DXVK aarch64 the session goes
  `IDLE → READY → SYNCHRONIZED → VISIBLE`, and then `FOCUSED` once SteamVR hands focus over.
- `xrCreateInstance` fails once with `-4`, and Unity retries successfully. The same happens on x64.

## Crashes found along the way

- **Recenter / headset put on** (tracking world change) → `xrEndFrame: XR_ERROR_HANDLE_INVALID` →
  page fault in `ucrtbase+0x40d68`, which is `__CxxFrameHandler3`. UnityOpenXR throws a C++ exception
  there, and Wine's ARM64 C++ EH dereferences NULL. Microsoft's ARM64 VC++ runtime next to the exe
  fixes it. The Unity crash report shows the same `unityopenxr` frame 1,000 times, which is an
  unwinder artifact, not recursion.
- **Maps don't start** → "Could not load readonly beatmap level data", then back to the menu.
  `BeatmapLevelDataUtils.ReadAllTextFromData` gunzips the beatmap through `GZipStream` →
  `MonoPosixHelper.dll`. The x64 copy can't load, and the exception is swallowed. Fixed by an ARM64
  build.
- A game whose VR session never opens spins at over 200 % CPU. Always stop test instances
  (`wineserver -k` on the prefix).

## Frame pacing

Measured with BeatLeader replays (Monday Not Sick Anymore and STARLIGHT, Expert+) at 2160×2160 and
120 Hz, logging every frame's time, with `perf` sampling all threads and the Frame's power rails
(`max34417` hwmon: `vph` system, `gfx` GPU, `apc*` CPU clusters).

- **LIV.** The game's LIV SDK P/Invokes `LIV_Bridge`, which only exists for x64. Every frame threw a
  `DllNotFoundException`, and BSIPA logged each one: 27,000 in one song. A stub `LIV_Bridge.dll` that
  reports "no capture" removed them. App CPU went from 5.3 to 4.7 ms per frame, and frames over
  9.5 ms dropped by 23 %.
- **Adaptive SFX.** `AdaptiveSfxVolume.OnAudioFilterRead` measures the song's loudness
  (`LufsMetering.LufsMeter.MomentaryLoudness`, `CalculateRmsBlockJob`) with many `Math.Pow` calls.
  Unity's ARM64 Mono links Microsoft's UCRT `pow`, whose slow path (`_frnd`, `_fpclass`, `_decomp`,
  `_set_exp`) dominated: 61 % of the audio thread's samples. On x64 the job is Burst-compiled.
  With the player setting off, the audio thread's samples dropped by 83 % and frames over 9.5 ms by 30 %.
- **MSAA stores.** The game draws the whole scene in one pass per frame: 2160×2160, 2 layers, 2× MSAA,
  color resolved inside the pass. The other passes are the small bloom chain and the desktop mirror.
  DXVK stored the multisampled color and depth after the resolve, though nothing reads them.
  Discarding them instead: GPU time per frame 6.3 → 4.8 ms, system power 17.6 → 16.7 W
  (STARLIGHT replay, 2160, 120 Hz, camera pinned). The picture is unchanged.
- **Fixed foveated rendering** (`BS_ARM64_FDM=1`, default profile) on top of that: GPU time 4.8 →
  4.2–4.3 ms, GPU rail 2.97 → 2.40–2.44 W, system power 16.7 → 15.4–15.6 W (two runs). Without MSAA,
  foveation saved less (4.7 → 4.5 ms). SteamVR's own foveation (`XR_FB_foveation`) would need the eye
  images created through OpenXR; Valve's `fdm_injection` layer targets Android and doesn't apply.
- **Eye-tracked foveated rendering** (sharp radius 0.15 around SteamVR's foveation centers, per-eye
  maps): GPU time 3.67/3.62 ms vs 4.18 ms fixed, GPU rail 1.83 vs 2.49 W, system power 14.3 vs 15.6 W,
  in alternating runs with the headset off (static gaze). App CPU and frame pacing unchanged.
- **GC** didn't cause hitches: the managed heap grew from 318 to 361 MB during the song and was
  never collected.
- The remaining hitches (13–18 ms, 13–25 per song) show the main thread busy in game and mod code.
  They vary between runs; not analysed further.

Symbols for Unity's ARM64 Mono are on Unity's symbol server
(`https://symbolserver.unity3d.com/mono-2.0-bdwgc.pdb/<guid><age>/mono-2.0-bdwgc.pdb`), and
`llvm-symbolizer --pdb` resolves them. For JIT-compiled code, `mono_jit_info_table_find` and
`mono_method_full_name` (both exported) map an address to its method inside the running game.

## Mods

- BSIPA 4.3.7 ships MonoMod.Core 1.3.3, which has an `Arm64Arch`, and Harmony 2.16. Its
  `WindowsSystem` sets `DefaultAbi` only for x86 and x64, so `MonoRuntime` refuses to start:
  `Cannot use Mono system, because the underlying system doesn't provide a default ABI!`. With the
  AAPCS64 ABI (as on Linux and macOS ARM64), SiraUtil, BSML, SongCore and BS Utils load, and their
  Harmony patches apply without errors.
- Doorstop worked on the first ARM64 build: it hooked Mono and invoked `IPA.Injector`. But the
  injector returned immediately, because `AntiPiracy.IsInvalid` counted our 552 KB `steam_api64.dll`
  and 2.1 MB `lsteamclient_a64.dll` as a Steam emulator (any file named "steam" of 350 KB or more).
- Doorstop's `LOG` macro uses MSVC's `__VA_ARGS__` comma elision. For a debug build with clang, use
  `##__VA_ARGS__`, and pass a byte-count pointer to `WriteFile`.
- SiraUtil's `DisableOpenXRRecentering` restarts the XR loader when the runtime is SteamVR. In 2 of
  3 ARM64 runs, SteamVR's standby toggled during the restart, and Unity then never recreated its
  eye textures. The headset showed a black window, and the session stayed `SYNCHRONIZED`/`VISIBLE`
  without frames. Runs where the headset was worn were fine, and so was an x64 run.
  This only happens when the game is started remotely (SSH, scripts) with the headset off; a player
  starts it with the headset on. For remote tests, put the headset on first, or use the bench
  plugin's `BS_ARM64_NO_XR_RESTART=1`.

## Other Frame notes (x64 path, BSManager)

- Valve's implicit `XR_APILAYER_VALVE_fdm_injection` / `VK_LAYER_VALVE_fdm_injection` spins forever
  in a `strcmp` loop during `vkCreateDevice`. `perf` showed about 85 % of time in
  `libVkLayer_VALVE_fdm_injection.so`. `DISABLE_VULKAN_FDM_INJECTION_LAYER=1` avoids it.
- Mod "Enhancements" 3.0.18 hangs 1.40.8 on the Frame while loading the main menu.
- `wine-mono` exists only for x86/x64. BSIPA's `IPA.exe` must run as a 32-bit x86 process under ARM64
  Proton (set `32BITREQUIRED` in the CLR header).

## Open items

- **Burst.** `lib_burst_generated.dll` is x64, and Burst jobs fall back to Mono. An ARM64 Burst library
  would need Unity's Burst compiler run for the game's assemblies; not attempted.
- **Wine's ARM64 C++ EH bug.** Report it upstream with a minimal repro. Once fixed, the Microsoft
  runtime isn't needed any more.
- **MonoMod upstream.** Send the Windows ARM64 default-ABI fix to MonoMod. Until then, the installer
  swaps in a rebuilt `MonoMod.Core.dll`.
- **SiraUtil XR restart vs. standby.** Look into why Unity doesn't recreate the eye textures when
  the headset goes into standby during SiraUtil's XR restart.
- **LIV.** Capture needs a real ARM64 `LIV_Bridge.dll` from LIV; the stub only stops the errors.
