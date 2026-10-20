# Upstream bugs

Bugs in other projects that bs-arm64 works around: what we do until they're fixed, and where they're
reported.

| # | Project | Bug | Our workaround | Status |
|---|---|---|---|---|
| 1 | MonoMod / BSIPA | No default ABI for Windows ARM64 | upstream MonoMod.Core 1.3.4 | fixed in MonoMod.Core 1.3.4 ([e8e742c](https://github.com/MonoMod/MonoMod/commit/e8e742c397347bb5a65e9ec4b937f9d0dca6fe1c)); BSIPA 4.3.7 still ships 1.3.3 |
| 2 | Wine (msvcrt) | ARM64 `__CxxFrameHandler3` looks up the unadjusted return address → NULL deref on MSVC code | private Wine C++ runtime with the backported fix | fixed in Wine master: [6964eb2](https://github.com/wine-mirror/wine/commit/6964eb2b018a9029b561124269e7ceec5bde8086) ([bug 60399](https://bugs.winehq.org/show_bug.cgi?id=60399)); our pinned Proton predates the fix |
| 3 | Proton (Wine win32u) | Device callback gets `vkGetDeviceProcAddr`, wineopenxr passes it on as `vkGetInstanceProcAddr` | none shipped (only hit in an experiment) | fixed in Proton experimental/bleeding-edge, not yet in 11.0 stable |
| 4 | Wine (ntdll, ARM64) | `call_user_mode_callback` saves FPSR over FPCR, so a returning user callback writes the FPSR flags into FPCR: FIZ/AH turn on with FEAT_AFP | `steam_api64.dll` patches the instruction in memory when it loads (0.3.1) | [bug 60453](https://bugs.winehq.org/show_bug.cgi?id=60453); in Wine master and Proton 11.0 |

## 1. MonoMod: no default ABI on Windows ARM64

MonoMod.Core 1.3.3 sets no default ABI on Windows ARM64, so Harmony can't patch anything.

- **Fixed upstream:** [e8e742c](https://github.com/MonoMod/MonoMod/commit/e8e742c397347bb5a65e9ec4b937f9d0dca6fe1c),
  released in MonoMod.Core 1.3.4. BSIPA 4.3.7 still ships 1.3.3; a dependency bump in BSIPA is enough.
- **Until then:** the installer upgrades BSIPA's DLL to unmodified upstream MonoMod.Core 1.3.4.

## 2. Wine: ARM64 C++ exception handling

Wine's ARM64 `__CxxFrameHandler3` crashes on some MSVC-compiled throw/catch, e.g. in `UnityOpenXR`
on recenter.

- **Reported:** [Wine bug 60399](https://bugs.winehq.org/show_bug.cgi?id=60399), with reproducer.
- **Fixed upstream:** [6964eb2](https://github.com/wine-mirror/wine/commit/6964eb2b018a9029b561124269e7ceec5bde8086)
  in Wine master; our pinned Proton predates it.
- **Until then:** the release builds a private Wine C++ runtime from the pinned Proton source with
  the fix backported (`ucrtbs64.dll`, `vcruntime140.dll`, `msvcp140.dll`, installed beside the game).
  Drop it once Proton ships the fix.

## 3. Proton wineopenxr: wrong proc address in the device callback

`xrCreateVulkanDeviceKHR` goes through winevulkan's device callback
(`VkCreateInfoWineDeviceCallback`). In Proton 11.0, Wine's win32u calls it as
`PFN_vkCreateDeviceCallbackWINE`, whose 5th argument is `PFN_vkGetDeviceProcAddrWINE`, and passes
`p_vkGetDeviceProcAddr` (`dlls/win32u/vulkan.c`). wineopenxr's `vk_create_device_callback`
(`wineopenxr/openxr.c`) treats that argument as `vkGetInstanceProcAddr` and hands it to the runtime as
`XrVulkanDeviceCreateInfoKHR::pfnGetInstanceProcAddr`. SteamVR calls it with its `VkInstance`, and the
process crashes: `err:vulkan:vkCreateDevice Exception 0xc0000005 in Unix call.`

This breaks apps that create their Vulkan device with `xrCreateVulkanDeviceKHR`
(`XR_KHR_vulkan_enable2`). We only hit it in an experiment (DXVK's device created through SteamVR, for
Valve's foveation layer); the shipped bs-arm64 doesn't use that path.

- **Fixed upstream:** Valve's Wine `experimental_11.0` and `bleeding-edge` pass `p_vkGetInstanceProcAddr`
  there; wineopenxr is unchanged. Not yet in Proton 11.0 stable (`proton_11.0`).
- **Until then:** nothing shipped. Our experiment used a fixed unix-side `wineopenxr.so`.

## 4. Wine: user callbacks write FPSR into FPCR on ARM64

After each window callback, Wine on ARM64 writes the floating-point status flags into the control
register. On the Frame's CPU that turns on flush-to-zero, which broke environment objects in Beat
Saber ([#8](https://github.com/DaVarga/bs-arm64/issues/8)).

- **Reported:** [Wine bug 60453](https://bugs.winehq.org/show_bug.cgi?id=60453), with test cases and
  the one-line patch.
- **Until then:** `steam_api64.dll` patches that instruction in the game's copy of `ntdll.so` when it
  loads ([`fpcr_fix.cpp`](../src/steam-api/fpcr_fix.cpp); `STEAMAPI_ARM64_FPCR_FIX=0` turns it off).
  Once Proton ships the fix, the instruction isn't found and the patch does nothing; remove it then.
