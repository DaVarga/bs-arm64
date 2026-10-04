# Building

`build.sh` builds the native components from pinned sources ([versions.env](../versions.env)) into
`out/` and downloads the pinned upstream MonoMod.Core package. It works on x86_64 or aarch64 Linux;
native output is Windows ARM64 (`aarch64-w64-mingw32`), and MonoMod.Core is managed code.

## Requirements

Debian/Ubuntu packages:

```sh
sudo apt install git curl python3 make gcc patch flex bison autoconf perl \
                 cmake ninja-build meson glslang-tools
```

`build.sh` downloads the llvm-mingw toolchain (pinned release) itself.

The `monomod` step extracts the unmodified `net452` DLL from MonoMod.Core 1.3.4's official NuGet
package after checking its pinned SHA256. It requires no .NET SDK or local MonoMod patch.

On Ubuntu, `needrestart` can block an unattended `apt` behind an interactive prompt. Use
`sudo NEEDRESTART_MODE=a apt install …`.

## Steps

```sh
./build.sh                 # everything
./build.sh steam-api dxvk  # selected steps
```

| Step | What it does |
|---|---|
| `toolchain` | download llvm-mingw into `deps/` |
| `fetch` | clone Proton (tag), Wine (Proton's submodule commit), DXVK (Proton's commit, with submodules), OpenXR-SDK (tag); download zlib and Mono's `zlib-helper.c` |
| `wine-tools` | `autoreconf`, `make_specfiles`, `make_makefiles`, `make_vulkan`, then a tools-only `configure` and build of `widl`, `winebuild`, and every IDL-generated header |
| `wine-runtime` | isolated copy of Proton's pinned Wine source + `patches/wine`: build `ucrtbs64.dll`, `vcruntime140.dll`, `msvcp140.dll` as ordinary, game-local ARM64 DLLs |
| `lsteamclient` | Proton `lsteamclient/*.c` (Windows half) → `lsteamclient_a64.dll`, exports from its `.spec`, Wine builtin marker |
| `wineopenxr` | Proton `wineopenxr/{openxr_loader,loader_thunks}.c` → `wineopenxr_a64.dll`, import libs for `winevulkan`/`ntdll` generated with `winebuild --def` |
| `steam-api` | `gen.py` (flat API wrappers) + `gen_sdk_inline.py` + core/helpers → `steam_api64.dll` |
| `openxr-loader` | apply patch, CMake + Ninja → `openxr_loader.dll` |
| `dxvk` | apply patches, Meson cross build → `dxgi.dll`, `d3d11.dll` |
| `monoposixhelper` | `zlib-helper.c` + zlib → `MonoPosixHelper.dll` |
| `doorstop` | BSIPA's Doorstop + generated ARM64 winhttp stubs → `winhttp.dll` |
| `monomod` | download and verify the pinned upstream MonoMod.Core 1.3.4 NuGet package → unmodified `MonoMod.Core.dll` (net452) |
| `liv-bridge` | `src/liv-bridge/liv_bridge.c` → `LIV_Bridge.dll` (stub for the game's LIV SDK) |
| `package` | not part of the default run: release tarball in `dist/` (see below) |

A full build from scratch takes about 15–20 minutes, mostly Wine's header generation and DXVK.

The private runtime is built from source with its own UCRT name, including the C++ library's dynamic
lookups. Wine's build rules omit the builtin marker for these three DLLs, so they load from the game
folder without runtime registry overrides. `src/wine-runtime/verify.py` checks their architecture,
imports and exception-handler forwarders during the build and packaging. No binary name rewriting
is used. The runtime build uses `--enable-archs=aarch64` on either Linux host architecture.

## Releases

`./build.sh package` checks that every DLL is pure ARM64 (and `steam_api64.dll` below 350 KB), then
writes `dist/bs-arm64-<version>-<PROTON_TAG>.tar.gz` plus its `.sha256`, and
`dist/bs-arm64-manifest.json`. The tarball holds the DLLs,
`bs-arm64.sh` with its helpers and `versions.env`, the docs, `SHA256SUMS`, the upstream licenses in
`licenses/`, and `SOURCES.md`, which names the exact upstream sources (the LGPL source offer). The
version is `$BS_ARM64_VERSION`, or else `git describe --tags`.

The manifest lists what the release was tested with, from `versions.env`: the Unity engines
(`UNITY_VERSION`), the Beat Saber versions (`BS_VERSIONS`) and the BSIPA versions (`BSIPA_VERSIONS`).
BSManager offers the ARM64 tab only for those Beat Saber versions, and mod support only for those
BSIPA versions:

```json
{
  "version": "v0.3.0",
  "proton": "proton-11.0-2c",
  "unityVersions": ["6000.0.40f1"],
  "bsVersions": ["1.40.9", "1.40.10", "…", "1.44.1"],
  "bsipaVersions": ["4.3.7"]
}
```

A version tested after the release can be added without a new build: edit the manifest and replace
it on the release with `gh release upload <tag> bs-arm64-manifest.json --clobber`.

[.github/workflows/release.yml](../.github/workflows/release.yml) does this on GitHub:

- **Push a tag** `v*` → full build, package, and a GitHub release with the tarball, its checksum and
  the manifest.
- **Run it manually** (Actions → release → Run workflow) → build and package only. The tarball is
  attached to the run as an artifact, which is useful as a dry run before tagging.

```sh
git tag v0.1.0 && git push origin v0.1.0
```

It runs on `ubuntu-24.04-arm`. If Arm runners aren't available for the repository, set the repository
variable `BS_ARM64_RUNNER` to `ubuntu-24.04`. `deps/` is cached, keyed on `versions.env`,
`patches/` and `build.sh`.

The workflow also runs the installer upgrade/uninstall tests in
`tools/test_installer_runtime.py` and checks that the tarball contains all three private runtime DLLs.

Each release is tied to one Proton build. When Valve updates Proton ARM64, update the pins (below) and
tag a new release.

## Keeping in sync with Proton

`lsteamclient_a64.dll` and `wineopenxr_a64.dll` must be built from the **same Proton version** that
runs the game. Their unix halves are Proton's own `.so` files, and the parameter structs and call
numbers change between versions. When Steam updates "Proton 11.0 (ARM64)":

1. Read the new version from `<Proton dir>/version` (for example `proton-11.0-2c-arm64`).
2. Set `PROTON_TAG` to the matching tag of github.com/ValveSoftware/Proton, and set `WINE_COMMIT` and
   `DXVK_COMMIT` to that tag's submodule commits (`git -C Proton submodule status`).
3. `rm -rf deps obj out && ./build.sh`, then reinstall.

## Checks

- Every output DLL must be `IMAGE_FILE_MACHINE_ARM64` (`0xaa64`).
- `steam_api64.dll` must export everything the real SDK 1.61 one does (1,089 symbols), plus the
  older SDKs' entry points (1,100 in total).
- [tools/smoketest.cpp](../tools/smoketest.cpp): a minimal ARM64 exe that loads `lsteamclient_a64.dll`
  and prints your SteamID, login state, app ID and persona name. Build and run:
  ```sh
  deps/llvm-mingw/bin/aarch64-w64-mingw32-clang++ -O2 -Iobj/steam-api/inc -Isrc/steam-api \
      tools/smoketest.cpp obj/steam-api/flat_generated.o -o smoketest.exe -static
  # on the device, with WINEDLLPATH set up and lsteamclient_a64.dll next to the exe:
  WINEDLLPATH=… proton run smoketest.exe   # writes the result to Z:\home\steamos\smoke.log
  ```
- [tools/loadtest.c](../tools/loadtest.c): `LoadLibrary` any DLL and print the error; run with
  `WINEDEBUG=+loaddll,+module` to see why a module fails to load.
