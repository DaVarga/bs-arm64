#!/bin/bash
# Build the open-source parts of the native ARM64 Beat Saber runtime.
#
# Output (out/):
#   lsteamclient_a64.dll  Proton lsteamclient, Windows half, pure aarch64 (Wine builtin)
#   wineopenxr_a64.dll    Proton wineopenxr, Windows half, pure aarch64 (Wine builtin)
#   steam_api64.dll       Steamworks SDK 1.61 flat API on top of lsteamclient_a64
#   openxr_loader.dll     Khronos OpenXR loader 1.1.45 for Windows ARM64 (patched)
#   dxgi.dll, d3d11.dll   DXVK (Proton's commit) for aarch64
#   MonoPosixHelper.dll   Mono's zlib helper (System.IO.Compression) for Windows ARM64
#   winhttp.dll           BSIPA's Doorstop injector (mod loader entry point) for Windows ARM64
#   MonoMod.Core.dll      unmodified upstream 1.3.4 (Windows ARM64 ABI, Harmony)
#   LIV_Bridge.dll        stub for the LIV SDK's x64-only native bridge (reports: no LIV capture)
#   ucrtbs64.dll, vcruntime140.dll, msvcp140.dll  private Wine C++ runtime with the upstream EH fix
#   patch_unityopenxr.py  copied for install/
#
# Usage: ./build.sh [step...]   steps: toolchain fetch wine-tools lsteamclient wineopenxr
#                                      steam-api openxr-loader dxvk monoposixhelper doorstop monomod
#                                      liv-bridge wine-runtime
#        (default: all, in that order)
#        ./build.sh package        release tarball of out/ + installer + licenses into dist/
#                                  (version: $BS_ARM64_VERSION, else `git describe --tags`)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
source "$ROOT/versions.env"
DEPS=$ROOT/deps
OUT=$ROOT/out
OBJ=$ROOT/obj
JOBS=$(nproc)
mkdir -p "$DEPS" "$OUT" "$OBJ"

HOST_ARCH=$(uname -m)
TC=$DEPS/llvm-mingw
CC=$TC/bin/aarch64-w64-mingw32-clang
CXX=$TC/bin/aarch64-w64-mingw32-clang++
DLLTOOL=$TC/bin/aarch64-w64-mingw32-dlltool
PROTON=$DEPS/proton
WINE=$DEPS/wine
WINE_TOOLS=$DEPS/wine-tools

log() { printf '\n==> %s\n' "$*"; }

# Mark a PE file as a Wine builtin so Wine resolves it through WINEDLLPATH and loads
# its unix half (<name>.so) from there.
mark_wine_builtin() {
    python3 - "$1" <<'PY'
import struct, sys
d = bytearray(open(sys.argv[1], 'rb').read())
assert struct.unpack_from('<I', d, 0x3c)[0] >= 0x60, 'DOS stub too small for the builtin marker'
d[0x40:0x60] = b'Wine builtin DLL'.ljust(32, b'\0')
open(sys.argv[1], 'wb').write(d)
PY
}

git_fetch_commit() { # <url> <commit|tag> <dir>
    local url=$1 rev=$2 dir=$3
    [ -d "$dir/.git" ] && return 0
    git init -q "$dir"
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 origin "$rev"
    git -C "$dir" checkout -q FETCH_HEAD
}

step_toolchain() {
    [ -x "$CC" ] && return 0
    log "llvm-mingw $LLVM_MINGW_VERSION ($HOST_ARCH host)"
    local name=llvm-mingw-$LLVM_MINGW_VERSION-ucrt-ubuntu-22.04-$HOST_ARCH
    curl -fsSL "https://github.com/mstorsjo/llvm-mingw/releases/download/$LLVM_MINGW_VERSION/$name.tar.xz" | tar xJ -C "$DEPS"
    mv "$DEPS/$name" "$TC"
}

step_fetch() {
    log "sources"
    [ -d "$PROTON/.git" ] || git clone -q --depth 1 --branch "$PROTON_TAG" https://github.com/ValveSoftware/Proton.git "$PROTON"
    git_fetch_commit https://github.com/ValveSoftware/wine.git "$WINE_COMMIT" "$WINE"
    if [ ! -d "$DEPS/dxvk/.git" ]; then
        git clone -q https://github.com/ValveSoftware/dxvk.git "$DEPS/dxvk"
        git -C "$DEPS/dxvk" checkout -q "$DXVK_COMMIT"
        git -C "$DEPS/dxvk" submodule update -q --init --recursive
    fi
    [ -d "$DEPS/OpenXR-SDK/.git" ] || git clone -q --depth 1 --branch "$OPENXR_SDK_TAG" https://github.com/KhronosGroup/OpenXR-SDK.git "$DEPS/OpenXR-SDK"
    [ -d "$DEPS/zlib-$ZLIB_VERSION" ] || curl -fsSL "https://github.com/madler/zlib/releases/download/v$ZLIB_VERSION/zlib-$ZLIB_VERSION.tar.gz" | tar xz -C "$DEPS"
    git_fetch_commit https://github.com/nike4613/BeatSaber-IPA-Reloaded.git "$BSIPA_COMMIT" "$DEPS/bsipa"
    [ -f "$DEPS/zlib-helper.c" ] || curl -fsSL -o "$DEPS/zlib-helper.c" \
        "https://raw.githubusercontent.com/Unity-Technologies/mono/$UNITY_MONO_COMMIT/support/zlib-helper.c"
    [ -f "$DEPS/mono-LICENSE" ] || curl -fsSL -o "$DEPS/mono-LICENSE" \
        "https://raw.githubusercontent.com/Unity-Technologies/mono/$UNITY_MONO_COMMIT/LICENSE"
}

# widl/winebuild plus the IDL-generated and Vulkan headers that Wine-style PE
# modules (lsteamclient, wineopenxr) need. Only tools and headers are built.
step_wine_tools() {
    [ -x "$WINE_TOOLS/tools/winebuild/winebuild" ] && [ -f "$WINE_TOOLS/include/d3d11.h" ] && return 0
    log "wine tools and headers"
    (cd "$WINE" && [ -f configure ] || autoreconf -f)
    (cd "$WINE" && tools/make_specfiles >/dev/null && { tools/make_makefiles >/dev/null 2>&1 || true; })
    (cd "$WINE/dlls/winevulkan" && python3 make_vulkan -x vk.xml -X video.xml)
    mkdir -p "$WINE_TOOLS"
    (cd "$WINE_TOOLS" && PATH=$TC/bin:$PATH "$WINE/configure" -q --without-x --without-freetype \
        --disable-tests --without-gstreamer --without-vulkan --without-wayland --without-alsa \
        --without-pulse --without-dbus --without-gnutls --without-cups --without-sane --without-usb \
        --without-v4l2 --without-krb5 --without-netapi --without-opencl --without-pcap --without-sdl \
        --without-udev --without-unwind --without-gphoto --without-fontconfig >/dev/null)
    local headers
    headers=$(grep -o '^include/[A-Za-z0-9_.]*\.h:' "$WINE_TOOLS/Makefile" | tr -d : | sort -u | grep -v config.h)
    PATH=$TC/bin:$PATH make -C "$WINE_TOOLS" -j"$JOBS" tools/widl/widl tools/winebuild/winebuild >/dev/null
    # shellcheck disable=SC2086
    PATH=$TC/bin:$PATH make -C "$WINE_TOOLS" -k -j"$JOBS" $headers >/dev/null 2>&1 || true
    [ -f "$WINE_TOOLS/include/d3d11.h" ] || { echo "header generation failed" >&2; exit 1; }
}

# Build only the private ARM64 CRT DLLs in an isolated copy of Proton's Wine source.
# The patches name/link the private UCRT and produce ordinary application-local PE files;
# neither the cached Wine checkout nor Proton's shared runtime is modified.
step_wine_runtime() {
    log "private Wine ARM64 C++ runtime"
    local src=$OBJ/wine-runtime-src b=$OBJ/wine-runtime fingerprint
    fingerprint=$( { printf '%s\n' "$WINE_COMMIT" "$LLVM_MINGW_VERSION";
                     sha256sum "$ROOT/build.sh" "$ROOT/patches/wine/"*.patch; } | sha256sum | cut -d' ' -f1)
    if [ "$(cat "$src/.bs-arm64-inputs" 2>/dev/null || true)" != "$fingerprint" ]; then
        rm -rf "${src:?}" "${b:?}"
        mkdir -p "$src" "$b"
        git -C "$WINE" archive "$WINE_COMMIT" | tar x -C "$src"
        (cd "$src" && tools/make_specfiles >/dev/null)
        local patch
        for patch in "$ROOT/patches/wine/"*.patch; do patch -d "$src" -p1 < "$patch"; done
        cp "$src/dlls/ucrtbase/ucrtbase.spec" "$src/dlls/ucrtbase/ucrtbs64.spec"
        (cd "$src" && autoreconf -f)
        (cd "$src/dlls/winevulkan" && python3 make_vulkan -x vk.xml -X video.xml)
        printf '%s\n' "$fingerprint" > "$src/.bs-arm64-inputs"
    fi
    if [ ! -f "$b/Makefile" ]; then
        (cd "$b" && PATH="$TC/bin:$PATH" "$src/configure" --enable-archs=aarch64 --disable-tests \
            --without-x --without-freetype --without-fontconfig --without-gstreamer --without-vulkan \
            --without-wayland --without-alsa --without-pulse --without-dbus --without-gnutls \
            --without-cups --without-sane --without-usb --without-v4l2 --without-krb5 \
            --without-netapi --without-opencl --without-pcap --without-sdl --without-udev \
            --without-unwind --without-gphoto > configure.log 2>&1) ||
            { echo "Wine runtime configure failed; see $b/configure.log" >&2; exit 1; }
    fi
    PATH="$TC/bin:$PATH" make -C "$b" -j"$JOBS" \
        dlls/ucrtbase/aarch64-windows/ucrtbs64.dll \
        dlls/vcruntime140/aarch64-windows/vcruntime140.dll \
        dlls/msvcp140/aarch64-windows/msvcp140.dll > "$b/build.log" 2>&1 ||
        { tail -40 "$b/build.log" >&2; exit 1; }
    cp "$b/dlls/ucrtbase/aarch64-windows/ucrtbs64.dll" "$OUT/"
    cp "$b/dlls/vcruntime140/aarch64-windows/vcruntime140.dll" "$OUT/"
    cp "$b/dlls/msvcp140/aarch64-windows/msvcp140.dll" "$OUT/"
    python3 "$ROOT/src/wine-runtime/verify.py" "$OUT"
}

wine_pe_flags() { # <module source dir>
    local res
    res=$($CC -print-resource-dir)
    echo "-O2 -nostdinc -isystem $res/include -I $1 -I $WINE/include -I $WINE/include/msvcrt -I $WINE_TOOLS/include" \
         "-D__WINESRC__ -D_UCRT -D_WIN32_WINNT=0xa00 -DWINE_NO_TRACE_MSGS -fno-builtin -fms-extensions -Wno-everything"
}

# Import library for a Wine dll, generated from its .spec (exports Wine-internal symbols).
wine_import_lib() { # <module> <out.a>
    local def=$OBJ/$1.def
    "$WINE_TOOLS/tools/winebuild/winebuild" --def -m64 --target aarch64-windows -E "$WINE/dlls/$1/$1.spec" -o "$def"
    "$DLLTOOL" -m arm64 -d "$def" -l "$2"
}

step_lsteamclient() {
    log "lsteamclient_a64.dll"
    local src=$PROTON/lsteamclient o=$OBJ/lsteamclient flags
    mkdir -p "$o"
    flags="$(wine_pe_flags "$src") -DSTEAM_API_EXPORTS -Dprivate=public -Dprotected=public"
    for f in "$src"/*.c; do
        echo "$CC -c $flags '$f' -o '$o/$(basename "$f").o'"
    done | xargs -P"$JOBS" -I{} sh -c '{}'
    # shellcheck disable=SC2086
    $CC -c $flags -D__WINE_PE_BUILD "$WINE/dlls/winecrt0/unix_lib.c" -o "$o/unix_lib.o"
    { echo "LIBRARY lsteamclient_a64.dll"; echo EXPORTS
      grep -E '^[0-9@]+ +cdecl' "$src/lsteamclient.spec" | sed -E 's/^[0-9@]+ +cdecl +(-private +)?([A-Za-z0-9_]+).*/\2/'
    } > "$OBJ/lsteamclient.def"
    wine_import_lib ntdll "$OBJ/libntdll_wine.a"
    $CC -shared -o "$OUT/lsteamclient_a64.dll" "$o"/*.o "$OBJ/lsteamclient.def" \
        -L"$OBJ" -lntdll_wine -luser32 -lws2_32
    mark_wine_builtin "$OUT/lsteamclient_a64.dll"
}

step_wineopenxr() {
    log "wineopenxr_a64.dll"
    local src=$PROTON/wineopenxr o=$OBJ/wineopenxr flags
    mkdir -p "$o"
    flags="$(wine_pe_flags "$src") -DWINE_NO_LONG_TYPES"
    for f in openxr_loader.c loader_thunks.c; do
        # shellcheck disable=SC2086
        $CC -c $flags "$src/$f" -o "$o/$f.o"
    done
    # shellcheck disable=SC2086
    $CC -c $flags -D__WINE_PE_BUILD "$WINE/dlls/winecrt0/unix_lib.c" -o "$o/unix_lib.o"
    printf 'LIBRARY wineopenxr_a64.dll\nEXPORTS\nxrNegotiateLoaderRuntimeInterface\n__wineopenxr_GetVulkanInstanceExtensions\n__wineopenxr_GetVulkanDeviceExtensions\nwineopenxr_init_registry\n' \
        > "$OBJ/wineopenxr.def"
    wine_import_lib ntdll "$OBJ/libntdll_wine.a"
    wine_import_lib winevulkan "$OBJ/libwinevulkan_wine.a"
    $CC -shared -o "$OUT/wineopenxr_a64.dll" "$o"/*.o "$OBJ/wineopenxr.def" \
        -L"$OBJ" -lwinevulkan_wine -lntdll_wine -ldxgi -ladvapi32 -luser32
    mark_wine_builtin "$OUT/wineopenxr_a64.dll"
}

step_steam_api() {
    log "steam_api64.dll"
    local src=$ROOT/src/steam-api o=$OBJ/steam-api sdk=$PROTON/lsteamclient/steamworks_sdk_161
    mkdir -p "$o/inc"
    ln -sfn "$sdk" "$o/inc/steam"
    python3 "$src/gen.py" "$PROTON/lsteamclient" "$o"
    python3 "$src/gen_sdk_inline.py" "$sdk/steamnetworkingtypes.h" "$o/sdk_inline_impl.inc"
    # Size matters: BSIPA's anti-piracy check rejects any file named '*steam*' of 350 KB or
    # more in the game folder. No C++ runtime, no exceptions/RTTI, -Os, stripped.
    local flags=(-Os -fno-exceptions -fno-rtti -I"$o/inc" -I"$src" -I"$o" -Wall -Wno-unused-parameter -Wno-unused-function -Wno-pragma-pack -Wno-unknown-pragmas)
    $CXX -c "${flags[@]}" "$o/flat_generated.cpp" -o "$o/flat_generated.o"
    $CXX -c "${flags[@]}" "$src/steam_api_core.cpp" -o "$o/steam_api_core.o"
    $CXX -c "${flags[@]}" "$src/steam_api_helpers.cpp" -o "$o/steam_api_helpers.o"
    $CXX -shared -Os -s -static -o "$OUT/steam_api64.dll" "$o"/flat_generated.o "$o"/steam_api_core.o "$o"/steam_api_helpers.o
    local size
    size=$(stat -c %s "$OUT/steam_api64.dll")
    [ "$size" -lt $((350 * 1024)) ] || { echo "steam_api64.dll is $size bytes; must stay below 350 KB (BSIPA anti-piracy heuristic)" >&2; exit 1; }
}

step_openxr_loader() {
    log "openxr_loader.dll"
    local src=$DEPS/OpenXR-SDK b=$OBJ/openxr-loader
    git -C "$src" apply --check "$ROOT/patches/openxr-loader/"*.patch 2>/dev/null && git -C "$src" apply "$ROOT/patches/openxr-loader/"*.patch
    mkdir -p "$b"
    cat > "$b/toolchain.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR ARM64)
set(CMAKE_C_COMPILER $CC)
set(CMAKE_CXX_COMPILER $CXX)
set(CMAKE_RC_COMPILER $TC/bin/aarch64-w64-mingw32-windres)
set(CMAKE_FIND_ROOT_PATH $TC/aarch64-w64-mingw32)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
EOF
    cmake -S "$src" -B "$b" -G Ninja -DCMAKE_TOOLCHAIN_FILE="$b/toolchain.cmake" -DCMAKE_BUILD_TYPE=Release \
        -DDYNAMIC_LOADER=ON -DBUILD_TESTS=OFF -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF >/dev/null
    ninja -C "$b" openxr_loader >/dev/null
    cp "$b/src/loader/openxr_loader.dll" "$OUT/"
}

step_dxvk() {
    log "DXVK (dxgi.dll, d3d11.dll)"
    local src=$DEPS/dxvk b=$OBJ/dxvk
    git -C "$src" apply --check "$ROOT/patches/dxvk/0001-libcxx-missing-includes.patch" 2>/dev/null &&
        git -C "$src" apply "$ROOT/patches/dxvk/0001-libcxx-missing-includes.patch"
    git -C "$src/subprojects/dxbc-spirv" apply --check "$ROOT/patches/dxvk/0002-dxbc-spirv-missing-include.patch" 2>/dev/null &&
        git -C "$src/subprojects/dxbc-spirv" apply "$ROOT/patches/dxvk/0002-dxbc-spirv-missing-include.patch"
    git -C "$src" apply --check "$ROOT/patches/dxvk/0003-discard-resolved-msaa.patch" 2>/dev/null &&
        git -C "$src" apply "$ROOT/patches/dxvk/0003-discard-resolved-msaa.patch"
    git -C "$src" apply --check "$ROOT/patches/dxvk/0005-keep-loaded-msaa-targets.patch" 2>/dev/null &&
        git -C "$src" apply "$ROOT/patches/dxvk/0005-keep-loaded-msaa-targets.patch"
    cat > "$OBJ/dxvk-cross-aarch64.txt" <<EOF
[binaries]
c = '$CC'
cpp = '$CXX'
ar = '$TC/bin/aarch64-w64-mingw32-ar'
strip = '$TC/bin/aarch64-w64-mingw32-strip'
windres = '$TC/bin/aarch64-w64-mingw32-windres'

[properties]
needs_exe_wrapper = true

[host_machine]
system = 'windows'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'
EOF
    [ -f "$b/build.ninja" ] || meson setup --cross-file "$OBJ/dxvk-cross-aarch64.txt" --buildtype release -Dbuild_id=false "$b" "$src" >/dev/null
    ninja -C "$b" >/dev/null
    cp "$b/src/dxgi/dxgi.dll" "$b/src/d3d11/d3d11.dll" "$OUT/"
}

step_monoposixhelper() {
    log "MonoPosixHelper.dll"
    local z=$DEPS/zlib-$ZLIB_VERSION
    $CC -O2 -shared -o "$OUT/MonoPosixHelper.dll" -I"$ROOT/src/monoposixhelper" -I"$z" -DHAVE_SYS_ZLIB \
        "$DEPS/zlib-helper.c" "$z"/{adler32,crc32,deflate,inflate,inffast,inftrees,trees,zutil}.c
}

step_doorstop() {
    log "winhttp.dll (BSIPA Doorstop)"
    local src=$DEPS/bsipa/Doorstop/Proxy o=$OBJ/doorstop
    mkdir -p "$o"
    python3 "$ROOT/src/doorstop/gen_proxy_arm64.py" "$src/proxy.c" "$o/proxy_arm64.c"
    $CC -O2 -fgnu89-inline -fno-builtin -shared -nostdlib -Wl,--entry,DllMain \
        -DUNICODE -D_UNICODE -DNDEBUG -D_WINDOWS -D_USRDLL -DNOGDI \
        -I"$ROOT/src/doorstop/shim" -I"$src" -o "$OUT/winhttp.dll" \
        "$ROOT/src/doorstop/doorstop_arm64.c" "$ROOT/src/doorstop/compat.c" "$o/proxy_arm64.c" "$src/proxy.def" \
        -lkernel32 -luser32 -lshell32 -ladvapi32 -lshlwapi -lucrt
}

# The game's LIV SDK (mixed reality capture) P/Invokes LIV_Bridge, which only exists for x64.
# Without an ARM64 one, LIV.dll throws DllNotFoundException every frame.
step_liv_bridge() {
    log "LIV_Bridge.dll (stub)"
    $CC -shared -Os -s -o "$OUT/LIV_Bridge.dll" "$ROOT/src/liv-bridge/liv_bridge.c"
}


# Harmony (via MonoMod.Core) has no default ABI for Windows ARM64 and refuses to patch.
# Use the unmodified upstream net452 DLL, including the Windows ARM64 ABI fix.
step_monomod() {
    log "MonoMod.Core $MONOMOD_CORE_VERSION (upstream package)"
    local src=$DEPS/monomod-core-$MONOMOD_CORE_VERSION pkg
    mkdir -p "$src"
    pkg=$src/monomod.core.$MONOMOD_CORE_VERSION.nupkg
    [ -f "$pkg" ] || curl -fsSL -o "$pkg" \
        "https://api.nuget.org/v3-flatcontainer/monomod.core/$MONOMOD_CORE_VERSION/monomod.core.$MONOMOD_CORE_VERSION.nupkg"
    printf '%s  %s\n' "$MONOMOD_CORE_SHA256" "$pkg" | sha256sum -c -
    python3 - "$pkg" "$OUT/MonoMod.Core.dll" "$src/LICENSE" <<'PY'
import sys, zipfile
from pathlib import Path
with zipfile.ZipFile(sys.argv[1]) as package:
    Path(sys.argv[2]).write_bytes(package.read('lib/net452/MonoMod.Core.dll'))
    Path(sys.argv[3]).write_bytes(package.read('LICENSE.txt'))
PY
}

# The DLLs a release ships; the installer needs all of them.
RELEASE_DLLS=(lsteamclient_a64.dll wineopenxr_a64.dll steam_api64.dll openxr_loader.dll dxgi.dll d3d11.dll
              MonoPosixHelper.dll winhttp.dll MonoMod.Core.dll LIV_Bridge.dll
              ucrtbs64.dll vcruntime140.dll msvcp140.dll)

# Release tarball in dist/: the DLLs, the installer and its helpers, docs, the upstream
# licenses, and SOURCES.md (where the corresponding source is, for the LGPL parts).
step_package() {
    local version=${BS_ARM64_VERSION:-$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || echo dev)}
    local name=bs-arm64-$version-$PROTON_TAG dist=$ROOT/dist
    local stage=$dist/$name repo=${BS_ARM64_REPO_URL:-https://github.com/DaVarga/bs-arm64}
    log "package $name"
    local f
    for f in "${RELEASE_DLLS[@]}"; do
        [ -f "$OUT/$f" ] || { echo "$OUT/$f missing; run the full build first" >&2; exit 1; }
    done
    # Every native DLL must be pure ARM64 (0xaa64); MonoMod.Core.dll is IL.
    python3 - "$OUT" "${RELEASE_DLLS[@]}" <<'PY'
import struct, sys
bad = []
for name in sys.argv[2:]:
    if name == 'MonoMod.Core.dll':
        continue
    d = open(f'{sys.argv[1]}/{name}', 'rb').read(4096)
    machine = struct.unpack_from('<H', d, struct.unpack_from('<I', d, 0x3c)[0] + 4)[0]
    if machine != 0xaa64:
        bad.append(f'{name}: machine {machine:#x}')
if bad:
    sys.exit('not ARM64: ' + ', '.join(bad))
PY
    [ "$(stat -c %s "$OUT/steam_api64.dll")" -lt $((350 * 1024)) ] ||
        { echo "steam_api64.dll must stay below 350 KB (BSIPA anti-piracy heuristic)" >&2; exit 1; }
    python3 "$ROOT/src/wine-runtime/verify.py" "$OUT"

    rm -rf "${stage:?}" "$dist/$name.tar.gz" "$dist/$name.tar.gz.sha256"
    mkdir -p "$stage/licenses"
    for f in "${RELEASE_DLLS[@]}"; do cp "$OUT/$f" "$stage/"; done
    cp "$ROOT/install/bs-arm64.sh" "$ROOT/versions.env" "$ROOT/src/unityopenxr/patch_unityopenxr.py" \
       "$ROOT/tools/unity_pkg_extract.py" "$ROOT/LICENSE" "$ROOT/README.md" "$stage/"
    cp -r "$ROOT/docs" "$stage/"

    local l=$stage/licenses
    cp "$PROTON/LICENSE" "$l/Proton-LICENSE"
    cp "$PROTON/LICENSE.proton" "$l/Proton-LICENSE.proton"
    cp "$PROTON/lsteamclient/LICENSE" "$l/Steamworks-SDK-LICENSE"
    cp "$WINE/LICENSE" "$l/Wine-LICENSE"
    cp "$WINE/COPYING.LIB" "$l/Wine-COPYING.LIB"
    cp "$WINE/libs/musl/COPYRIGHT" "$l/musl-COPYRIGHT"
    cp "$DEPS/dxvk/LICENSE" "$l/DXVK-LICENSE"
    cp "$DEPS/dxvk/subprojects/dxbc-spirv/LICENSE" "$l/dxbc-spirv-LICENSE"
    cp "$DEPS/dxvk/subprojects/libdisplay-info/LICENSE" "$l/libdisplay-info-LICENSE"
    cp "$DEPS/OpenXR-SDK/LICENSE" "$l/OpenXR-SDK-LICENSE"
    cp "$DEPS/zlib-$ZLIB_VERSION/LICENSE" "$l/zlib-LICENSE"
    cp "$DEPS/mono-LICENSE" "$l/Mono-LICENSE"
    cp "$DEPS/bsipa/Doorstop/LICENSE" "$l/Doorstop-LICENSE"
    cp "$DEPS/monomod-core-$MONOMOD_CORE_VERSION/LICENSE" "$l/MonoMod-LICENSE"
    cp "$TC/LICENSE.TXT" "$l/llvm-mingw-LICENSE.TXT"

    local rev
    rev=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)
    cat > "$stage/SOURCES.md" <<EOF
# Corresponding source

The native binaries in this release were built by \`build.sh\` from these exact sources.
MonoMod.Core is the unmodified DLL from its pinned upstream NuGet package. Each upstream
license is in \`licenses/\`; this project's own code is MIT (\`LICENSE\`).

| Component | Source |
|---|---|
| bs-arm64 (build script, patches, steam_api64, LIV_Bridge stub, installer) | $repo/tree/$rev |
| Proton $PROTON_TAG (lsteamclient, wineopenxr, Steamworks SDK headers) | https://github.com/ValveSoftware/Proton/tree/$PROTON_TAG |
| Wine, Proton's fork (private C++ runtime, winecrt0, headers, widl, winebuild; patches/wine includes upstream $WINE_CXX_EH_FIX) | https://github.com/ValveSoftware/wine/tree/$WINE_COMMIT |
| musl (statically linked into the private Wine runtime) | https://github.com/ValveSoftware/wine/tree/$WINE_COMMIT/libs/musl |
| DXVK, Proton's fork, with its submodules | https://github.com/ValveSoftware/dxvk/tree/$DXVK_COMMIT |
| OpenXR-SDK $OPENXR_SDK_TAG | https://github.com/KhronosGroup/OpenXR-SDK/tree/$OPENXR_SDK_TAG |
| zlib $ZLIB_VERSION | https://github.com/madler/zlib/releases/tag/v$ZLIB_VERSION |
| Mono \`support/zlib-helper.c\` (Unity's fork) | https://github.com/Unity-Technologies/mono/blob/$UNITY_MONO_COMMIT/support/zlib-helper.c |
| BSIPA's Doorstop | https://github.com/nike4613/BeatSaber-IPA-Reloaded/tree/$BSIPA_COMMIT/Doorstop |
| MonoMod.Core $MONOMOD_CORE_VERSION (unmodified NuGet net452 DLL, package SHA256 $MONOMOD_CORE_SHA256) | https://github.com/MonoMod/MonoMod/tree/$MONOMOD_COMMIT |
| llvm-mingw $LLVM_MINGW_VERSION (toolchain; statically linked runtime parts) | https://github.com/mstorsjo/llvm-mingw/releases/tag/$LLVM_MINGW_VERSION |

The changes to upstream code are the patches in \`patches/\` of the bs-arm64 tree above.
To rebuild, run \`./build.sh\` there (see docs/BUILD.md).
EOF

    (cd "$stage" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum > "$dist/SHA256SUMS.tmp")
    mv "$dist/SHA256SUMS.tmp" "$stage/SHA256SUMS"
    tar -C "$dist" --owner=0 --group=0 --numeric-owner --sort=name -czf "$dist/$name.tar.gz" "$name"
    (cd "$dist" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")

    cat > "$dist/RELEASE_NOTES.md" <<EOF
Runs Beat Saber **$GAME_VERSION** as a native Windows ARM64 program under ARM64 Proton (tested on the
Steam Frame) instead of emulating the x64 build with FEX.

## Works with

| | |
|---|---|
| Proton | **$PROTON_TAG** only: Steam's "Proton 11.0 (ARM64)" at that build |
| Beat Saber | **$GAME_VERSION** only (Unity $UNITY_VERSION), e.g. a BSManager instance |
| VR | SteamVR (OpenXR) |
| Mods | BSIPA 4.3.7 with Harmony mods (tested: SiraUtil, BSML, SongCore, BS Utils, CustomSabersLite, HitScoreVisualizer) |

Check your Proton build before installing; it must print \`$PROTON_TAG\` (with an \`-arm64\` suffix):

\`\`\`sh
cut -d' ' -f2 ~/.steam/steam/steamapps/common/"Proton 11.0 (ARM64)"/version
\`\`\`

The installer refuses any other Proton build, because the Steam and OpenXR libraries talk directly to
that Proton's own libraries. When Steam updates Proton, wait for a matching release.

## Install

Easiest: the **ARM64 tab** of the Steam Frame BSManager fork
(https://github.com/DaVarga/bs-manager) installs this release for you. By hand:

Work on a **copy** of your $GAME_VERSION instance (BSManager can duplicate instances). The Wine prefix
must exist: launch any game with it once.

\`\`\`sh
tar xf $name.tar.gz && cd $name
./bs-arm64.sh install ~/.local/share/BSManager/BSInstances/<copy>   # also downloads the Unity player etc.
./bs-arm64.sh launch  ~/.local/share/BSManager/BSInstances/<copy>
./bs-arm64.sh uninstall ~/.local/share/BSManager/BSInstances/<copy> # restores the x64 files
\`\`\`

Without mod support: \`install --no-mods\` (engine only), or \`launch --no-mods\` to start one
time without mods. If you (re)install BSIPA afterwards, run \`install\` again. See \`docs/INSTALL.md\` for every file it
touches.

## Known issues

- If the headset goes into standby while SiraUtil restarts the XR session at startup, the game stays
  on a black screen. Keep the headset on while the game starts.
- Burst code runs as managed code (no ARM64 Burst library). LIV capture isn't available.

## Not included

The Unity ARM64 player and Unity's OpenXR plugin aren't redistributable. The
installer downloads them from their official sources. The fixed, private Wine C++ runtime is included
and installs beside the ARM64 game; no Microsoft runtime download or BSM changes are needed.
Corresponding source for the binaries:
\`SOURCES.md\`, built from $repo/tree/$rev.

Unofficial project, not affiliated with Beat Games or Valve.
EOF
    ls -la "$dist"
}

ALL=(toolchain fetch wine-tools lsteamclient wineopenxr steam-api openxr-loader dxvk monoposixhelper doorstop monomod
     liv-bridge wine-runtime)
STEPS=("$@")
[ ${#STEPS[@]} -eq 0 ] && STEPS=("${ALL[@]}")
for s in "${STEPS[@]}"; do
    "step_${s//-/_}"
done
[ "${STEPS[*]}" = package ] && exit 0
cp "$ROOT/src/unityopenxr/patch_unityopenxr.py" "$ROOT/tools/unity_pkg_extract.py" "$OUT/"
log "done"
ls -la "$OUT"
