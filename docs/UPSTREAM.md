# Upstream bugs

Bugs in other projects that bs-arm64 works around: what we do until they're fixed, and where they're
reported.

| # | Project | Bug | Our workaround | Status |
|---|---|---|---|---|
| 1 | MonoMod / BSIPA | No default ABI for Windows ARM64 | upstream MonoMod.Core 1.3.4 | fixed in MonoMod.Core 1.3.4 ([e8e742c](https://github.com/MonoMod/MonoMod/commit/e8e742c397347bb5a65e9ec4b937f9d0dca6fe1c)); BSIPA 4.3.7 still ships 1.3.3 |
| 2 | Wine (msvcrt) | ARM64 `__CxxFrameHandler3` looks up the unadjusted return address → NULL deref on MSVC code | private Wine C++ runtime with the backported fix | fixed in Wine master: [6964eb2](https://github.com/wine-mirror/wine/commit/6964eb2b018a9029b561124269e7ceec5bde8086) ([bug 60399](https://bugs.winehq.org/show_bug.cgi?id=60399)); our pinned Proton predates the fix |
| 3 | Proton (Wine win32u) | Device callback gets `vkGetDeviceProcAddr`, wineopenxr passes it on as `vkGetInstanceProcAddr` | none shipped (only hit in an experiment) | fixed in Proton experimental/bleeding-edge, not yet in 11.0 stable |
| 4 | Valve (SteamVR) | `fdm_injection` hangs `vkCreateDevice` when only its implicit OpenXR half is active (games started outside Steam); its Vulkan manifest can't load | set the layer's variables as Steam does, or `DISABLE_VULKAN_FDM_INJECTION_LAYER=1` | [reported](https://github.com/ValveSoftware/SteamVR-for-Linux/issues/972) |

## 1. MonoMod: no default ABI on Windows ARM64

MonoMod.Core's `WindowsSystem` sets `DefaultAbi` only for x86 and x64. On Windows ARM64,
`MonoRuntime` then refuses to start: `Cannot use Mono system, because the underlying system doesn't
provide a default ABI!`, and Harmony can't patch anything.

- **Fixed upstream:** MonoMod added the same ABI (AAPCS64, as on Linux and macOS ARM64) in
  [e8e742c](https://github.com/MonoMod/MonoMod/commit/e8e742c397347bb5a65e9ec4b937f9d0dca6fe1c)
  "Add Windows-ARM64 support", released in MonoMod.Core 1.3.4 (March 2026).
- **Missing:** BSIPA 4.3.7 still ships MonoMod.Core 1.3.3. A dependency bump in BSIPA is enough.
- **Until then:** the installer upgrades BSIPA's DLL to unmodified upstream MonoMod.Core 1.3.4.
  Earlier releases rebuilt and patched 1.3.3; that local patch is no longer needed.
- **Verified on the Frame (2026-10-03):** the upstream `net452` DLL completed a full modded
  STARLIGHT replay (21,982 recorded frames) with BSIPA's existing dependencies, including
  MonoMod.Utils 25.0.11. Only Core was replaced for the test.

## 2. Wine: ARM64 C++ exception handling

Before the upstream fix, Wine's ARM64 `__CxxFrameHandler3` (ucrtbase) crashes with a NULL read (`ucrtbase+0x40d68`,
`ldr w8, [x0]`) when `UnityOpenXR` throws and catches, e.g. when the tracking origin changes
(recenter, headset put on).

**Cause** (`dlls/msvcrt/except.c`, `cxx_frame_handler`, as reproduced on Wine 11.18):

```c
/* update orig_frame if it's a nested exception */
throw_func_off = RtlLookupFunctionEntry(dispatch->ControlPc, &throw_base, NULL)->BeginAddress;
```

On ARM64, `dispatch->ControlPc` of a caller frame is the return address. MSVC emits nothing after a
call to a noreturn function (clang adds a `brk`), so a function that ends with such a call, typically a
throw helper, has its return address just past its own end. The `ip_to_state()` calls above use
`get_exception_pc()` (`ControlPc - 4` when `ControlPcIsUnwound`), this line doesn't. If no function
starts at that address, `RtlLookupFunctionEntry` returns NULL and the handler faults; if one does, it
silently returns the wrong function.

In `UnityOpenXR.dll` (Unity OpenXR 1.14.3, ARM64): 449 functions use `__CxxFrameHandler3`, 25 of them
end with a call to a noreturn throw helper, and for 18 the return address lies in no function.

**Reproduced** (2026-09-28, Proton 11.0 ARM64 on the Frame) with a small test built by llvm-mingw's
clang in MSVC mode (`--target=aarch64-pc-windows-msvc`, importing `vcruntime140.dll`): a DLL function
with a local destructor object that ends with a call to a `noreturn` throw helper, its unwind range cut
after the call to match MSVC's layout, called from a `try`/`catch` in the exe. With Wine's runtime it
crashes at exactly `ucrtbase+0x40d68`; with Microsoft's `vcruntime140.dll` next to it the exception is
caught. Ordinary throw/catch (in the exe, inside the DLL, across the DLL boundary, `catch (...)`) works
with Wine's runtime. Reproducer: [tools/repro/cxx-eh](../tools/repro/cxx-eh) (`build.sh`, case 5).

- **Reported:** [Wine bug 60399](https://bugs.winehq.org/show_bug.cgi?id=60399) (component msvcrt),
  with the reproducer and logs, reproduced on WineHQ master (wine-11.18, native aarch64).
- **Fixed upstream:** Wine master merged
  [6964eb2](https://github.com/wine-mirror/wine/commit/6964eb2b018a9029b561124269e7ceec5bde8086)
  (2026-10-02), "msvcrt: Don't compute handler pointer in cxx_frame_handler if it's not needed."
  The merged fix defers the lookup until a nested catch needs it and checks for a missing function
  entry. It retains `dispatch->ControlPc`; it does not use the adjusted exception PC suggested above.
- **Verified locally (2026-10-03):** all five reproducer cases pass with Wine's built-in runtime on
  native aarch64 after rebuilding our Wine 11.18 test checkout with the exact merged `except.c`
  change. The extended sixth case (a throw-at-end function that also contains a try block) passes
  too. This checks the Wine fix, not UnityOpenXR on Proton.
- **Until available in our Proton build:** the release builds a private Wine runtime from the pinned
  Proton source with this fix backported. `ucrtbs64.dll`, `vcruntime140.dll` and `msvcp140.dll` install
  beside the ARM64 game; no shared-prefix runtime overrides are needed. This replaces earlier
  releases' Microsoft-runtime workaround. The source-built release DLLs passed all six reproducer
  cases and loaded successfully under Frame's bundled Proton. Those exact DLLs also completed
  a full STARLIGHT replay on the Frame (21,982 recorded frames) and exited cleanly.

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

## 4. SteamVR: fdm_injection hangs vkCreateDevice; broken Vulkan manifest

The implicit OpenXR layer `XR_APILAYER_VALVE_fdm_injection`
(`/usr/share/openxr/1/api_layers/implicit.d/XrApiLayer_VALVE_fdm_injection.json`) is active for every
OpenXR app unless `DISABLE_VULKAN_FDM_INJECTION_LAYER` is set. A D3D11 OpenXR game started through
Proton outside the Steam client (BSManager, scripts) then hangs forever creating its device: Beat Saber
stops at `GfxDevice: creating device client` (> 7 minutes, x64 and ARM64 builds alike). Reproduced on
SteamOS stable (20260922.6101926, SteamVR r25358740) and beta (20260925.6191901, SteamVR r25513384).

Steam doesn't set `DISABLE_VULKAN_FDM_INJECTION_LAYER`, as we first assumed. With a game's
**Foveated Rendering** switch on, it sets `FDM_DEBUG=enable` and
`VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection` (checked in retail Beat Saber's
environment). With those two, a launch outside Steam works too, x64 and ARM64, and the layer creates its
density maps. So the hang happens when the OpenXR half is active and the Vulkan half isn't.

Also, `/usr/share/vulkan/explicit_layer.d/VkLayer_VALVE_fdm_injection.json` names
`libVkLayer_VALVE_fdm_injection.so`, but that library exports its entry points with a prefix
(`fdm_injection_GetInstanceProcAddr`, `fdm_injection_GetDeviceProcAddr`) and the manifest has no
`functions` mapping. Enabling the layer by name in `vulkaninfo` fails: `Failed to find
'vkGetInstanceProcAddr' in layer "libVkLayer_VALVE_fdm_injection.so"`. In the game it works anyway.

- **Reported:** [ValveSoftware/SteamVR-for-Linux#972](https://github.com/ValveSoftware/SteamVR-for-Linux/issues/972).
- **Until then:** launch with the two variables for foveated rendering, or with
  `DISABLE_VULKAN_FDM_INJECTION_LAYER=1` without it. `bs-arm64.sh launch` does that (`--foveation`).
