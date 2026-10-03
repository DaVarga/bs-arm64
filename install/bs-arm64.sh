#!/bin/bash
# Turn a Beat Saber 1.44.1 install into a native ARM64 build and run it on ARM64 Proton
# (e.g. the Steam Frame).
#
#   bs-arm64.sh fetch     [--cache DIR]
#       Download the parts we may not redistribute, from their official sources:
#       Unity 6000.0.40f1 Windows ARM64 player, Unity OpenXR 1.14.3 ARM64 plugin (import
#       patched for desktop). The private Wine C++ runtime comes with the release.
#   bs-arm64.sh install   <instance> [--no-mods] [--artifacts DIR] [--cache DIR] [--prefix DIR] [--proton DIR]
#       Back up the x64 files and install the ARM64 files into <instance>; set up the
#       Wine prefix (ARM64 runtime dir, OpenXR runtime JSON, registry value).
#       If BSIPA is installed, also install its ARM64 fixes, unless --no-mods is given
#       (then the game always starts without mods).
#   bs-arm64.sh uninstall <instance>
#       Restore the x64 files from the backup.
#   bs-arm64.sh launch    <instance> [--no-mods] [--foveation] [--prefix DIR] [--proton DIR] [--debug]
#       Start the game through Proton with the environment it needs.
#       --no-mods: start without mods (BSIPA isn't loaded) this time.
#       --foveation: SteamVR's (eye-tracked) foveated rendering, as Steam's "Foveated Rendering"
#       switch does; FDM_DEBUG=enable,hi (or lo, med) picks a stronger or weaker preset.
#
# Defaults: --artifacts = this script's directory in a release, else ../out (build.sh output),
#           --cache     = ~/.cache/bs-arm64,
#           --prefix    = BSManager's shared compatdata,
#           --proton    = Steam's "Proton 11.0 (ARM64)".
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
VERSIONS=$HERE/../versions.env
[ -f "$VERSIONS" ] || VERSIONS=$HERE/versions.env
# shellcheck source=../versions.env
source "$VERSIONS"

# Release tarball: the DLLs sit next to this script. Repo checkout: build.sh writes them to out/.
if [ -f "$HERE/steam_api64.dll" ]; then ARTIFACTS=$HERE; else ARTIFACTS=$HERE/../out; fi
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/bs-arm64
PREFIX=$HOME/.local/share/BSManager/SharedContent/compatdata
PROTON="$HOME/.steam/steam/steamapps/common/Proton 11.0 (ARM64)"
DEBUG=0
MODS=1
FOVEATION=0

BS_APP_ID=620980
STATE_DIR=.bs-arm64             # inside the instance: backup + install record
RUNTIME_DIR=drive_c/bs-arm64    # inside the prefix: WINEDLLPATH for the Wine builtins
PLAYER_VARIATION=Variations/win_arm64_player_nondevelopment_mono

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*"; }

parse_opts() {
    POSITIONAL=()
    while [ $# -gt 0 ]; do
        case $1 in
            --artifacts) ARTIFACTS=$2; shift 2 ;;
            --cache) CACHE=$2; shift 2 ;;
            --prefix) PREFIX=$2; shift 2 ;;
            --proton) PROTON=$2; shift 2 ;;
            --debug) DEBUG=1; shift ;;
            --no-mods) MODS=0; shift ;;
            --foveation) FOVEATION=1; shift ;;
            -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
            *) POSITIONAL+=("$1"); shift ;;
        esac
    done
}

tool() { # locate a helper script (next to us in a release, in tools/ or src/ in the repo)
    local name=$1
    for d in "$HERE" "$ARTIFACTS" "$HERE/../tools" "$HERE/../src/unityopenxr"; do
        [ -f "$d/$name" ] && { echo "$d/$name"; return; }
    done
    die "helper $name not found"
}

proton_version() { cut -d' ' -f2 "$PROTON/version" 2>/dev/null || echo unknown; }

# --- fetch -------------------------------------------------------------------

cmd_fetch() {
    mkdir -p "$CACHE"
    local unity=$CACHE/unity-$UNITY_VERSION
    if [ ! -f "$unity/$PLAYER_VARIATION/UnityPlayer.dll" ]; then
        log "Unity $UNITY_VERSION Windows ARM64 player (streams the ~500 MB package, keeps ~40 MB)"
        local url="https://download.unity3d.com/download_unity/$UNITY_CHANGESET/MacEditorTargetInstaller/UnitySetup-Windows-Mono-Support-for-Editor-$UNITY_VERSION.pkg"
        rm -rf "$unity.tmp"
        python3 "$(tool unity_pkg_extract.py)" "$url" "$unity.tmp" \
            "$PLAYER_VARIATION/WindowsPlayer.exe" "$PLAYER_VARIATION/UnityPlayer.dll" \
            "$PLAYER_VARIATION/UnityCrashHandler64.exe" "$PLAYER_VARIATION/MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll"
        mv "$unity.tmp" "$unity"
    fi

    local oxr=$CACHE/unity-openxr-$UNITY_OPENXR_VERSION
    if [ ! -f "$oxr/UnityOpenXR.dll" ]; then
        log "Unity OpenXR $UNITY_OPENXR_VERSION ARM64 plugin"
        mkdir -p "$oxr.tmp"
        curl -fsSL "https://download.packages.unity.com/com.unity.xr.openxr/-/com.unity.xr.openxr-$UNITY_OPENXR_VERSION.tgz" \
            | tar xz -C "$oxr.tmp" package/Runtime/universalwindows/arm64/UnityOpenXR.dll
        python3 "$(tool patch_unityopenxr.py)" "$oxr.tmp/package/Runtime/universalwindows/arm64/UnityOpenXR.dll" "$oxr.tmp/UnityOpenXR.dll"
        mkdir -p "$oxr" && mv "$oxr.tmp/UnityOpenXR.dll" "$oxr/" && rm -rf "$oxr.tmp"
    fi

    log "fetched into $CACHE"
}

# --- install -----------------------------------------------------------------

install_file() { # <src> <instance-relative dst>
    local src=$1 rel=$2 dst=$INSTANCE/$2 bak=$INSTANCE/$STATE_DIR/backup/$2
    [ -f "$src" ] || die "missing $src"
    if [ -e "$dst" ] && [ ! -e "$bak" ] && ! grep -qxF "$rel" "$INSTANCE/$STATE_DIR/added" 2>/dev/null; then
        mkdir -p "$(dirname "$bak")"
        cp -p "$dst" "$bak"
    elif [ ! -e "$dst" ] && [ ! -e "$bak" ] &&
         ! grep -qxF "$rel" "$INSTANCE/$STATE_DIR/added" 2>/dev/null; then
        echo "$rel" >> "$INSTANCE/$STATE_DIR/added"
    fi
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
}

# Remove a file installed by an earlier release while keeping its original backup
# for uninstall. Never remove an untracked file from the user's instance.
retire_installed_file() {
    local rel=$1 bak=$INSTANCE/$STATE_DIR/backup/$1
    if [ -e "$bak" ] || grep -qxF "$rel" "$INSTANCE/$STATE_DIR/added" 2>/dev/null; then
        rm -f "$INSTANCE/$rel"
        local added=$INSTANCE/$STATE_DIR/added
        awk -v retired="$rel" '$0 != retired' "$added" > "$added.tmp"
        mv "$added.tmp" "$added"
    fi
}

swap_bsipa_file() { # <instance-relative path> <replacement>
    local rel=$1 src=$2
    if cmp -s "$INSTANCE/$rel" "$src"; then return 0; fi
    # Keep the first backup: that's BSIPA's original, not an earlier build of ours.
    if [ ! -e "$INSTANCE/$STATE_DIR/backup/$rel" ]; then
        mkdir -p "$(dirname "$INSTANCE/$STATE_DIR/backup/$rel")"
        cp -p "$INSTANCE/$rel" "$INSTANCE/$STATE_DIR/backup/$rel"
    fi
    cp "$src" "$INSTANCE/$rel"
}

# BSIPA (mod loader) needs two ARM64 fixes; applied only when BSIPA is installed.
# Run install again after (re)installing BSIPA, since IPA.exe copies its x64 files back.
#  - Doorstop (winhttp.dll): its x64 build can't load into the ARM64 player.
#  - MonoMod.Core.dll: BSIPA's 1.3.3 has no Windows ARM64 ABI; upstream 1.3.4 fixes it.
install_bsipa_fixes() {
    [ -f "$INSTANCE/winhttp.dll" ] || return 0
    [ -f "$ARTIFACTS/winhttp.dll" ] || die "BSIPA is installed but $ARTIFACTS/winhttp.dll is missing; run build.sh"
    log "BSIPA found: installing the ARM64 Doorstop (winhttp.dll)"
    swap_bsipa_file winhttp.dll "$ARTIFACTS/winhttp.dll"

    local core=Libs/MonoMod.Core.dll
    [ -f "$INSTANCE/$core" ] || return 0
    if [ -f "$ARTIFACTS/MonoMod.Core.dll" ] && cmp -s "$INSTANCE/$core" "$ARTIFACTS/MonoMod.Core.dll"; then
        return 0
    fi
    # Only upgrade BSIPA's exact version (or our earlier patched build).
    if ! grep -qaE "$MONOMOD_CORE_MATCH" "$INSTANCE/$core"; then
        echo "warning: $core is not the recognized BSIPA MonoMod.Core 1.3.3; leaving it unchanged" >&2
        return 0
    fi
    [ -f "$ARTIFACTS/MonoMod.Core.dll" ] || die "$ARTIFACTS/MonoMod.Core.dll is missing; run build.sh monomod"
    log "BSIPA found: upgrading MonoMod.Core to upstream $MONOMOD_CORE_VERSION"
    swap_bsipa_file "$core" "$ARTIFACTS/MonoMod.Core.dll"
}

# --no-mods after an install with mods: put BSIPA's own files back.
restore_bsipa_files() {
    local rel
    for rel in winhttp.dll Libs/MonoMod.Core.dll; do
        if [ -f "$INSTANCE/$STATE_DIR/backup/$rel" ] && [ -f "$INSTANCE/$rel" ] &&
            ! cmp -s "$INSTANCE/$STATE_DIR/backup/$rel" "$INSTANCE/$rel"; then
            log "no mods: restoring BSIPA's $rel"
            cp -p "$INSTANCE/$STATE_DIR/backup/$rel" "$INSTANCE/$rel"
        fi
    done
}

# Processes still running in the Wine prefix: the game, a process left hanging by an earlier
# launch, or Wine's helpers (wineserver, services.exe, ...) that linger for a few seconds
# after BSManager ran IPA.exe. Installing would then replace files in use, and
# `wineserver -w` would wait forever. Proton sets WINEPREFIX to "<compatdata>/pfx/".
prefix_pids() {
    local pfx=$PREFIX/pfx p
    for p in /proc/[0-9]*; do
        grep -qzxF -e "WINEPREFIX=$pfx" -e "WINEPREFIX=$pfx/" "$p/environ" 2>/dev/null && echo "${p#/proc/}"
    done
}

require_prefix_idle() {
    local pids p names waiting="" end=$((SECONDS + 30))
    while pids=$(prefix_pids); [ -n "$pids" ] && [ "$SECONDS" -lt "$end" ]; do
        [ -n "$waiting" ] || log "waiting for Windows programs in the Wine prefix to exit"
        waiting=1
        sleep 1
    done
    [ -n "$pids" ] || return 0
    # "C:\windows\system32\services.exe" -> "services.exe"
    names=$(for p in $pids; do
        tr '\0' '\n' < "/proc/$p/cmdline" 2>/dev/null | head -n1 | sed 's#.*[/\\]##'
    done | sort -u | paste -sd, - | sed 's/,/, /g')
    die "still running in $PREFIX/pfx: ${names:-unknown}; close it (if nothing is open, restart the device) and try again"
}

setup_prefix() {
    local pfx=$PREFIX/pfx rt=$PREFIX/pfx/$RUNTIME_DIR unix_lib=$PROTON/files/lib/wine/aarch64-unix
    [ -d "$pfx/drive_c" ] || die "Wine prefix $pfx does not exist; start any game with this prefix once first"
    [ -f "$unix_lib/lsteamclient.so" ] || die "$PROTON is not an ARM64 Proton"

    log "prefix runtime in $rt"
    mkdir -p "$rt/aarch64-windows" "$rt/aarch64-unix"
    cp "$ARTIFACTS/lsteamclient_a64.dll" "$ARTIFACTS/wineopenxr_a64.dll" "$rt/aarch64-windows/"
    # The Windows halves are built from this Proton's source; reuse its unix halves.
    ln -sfn "$unix_lib/lsteamclient.so" "$rt/aarch64-unix/lsteamclient_a64.so"
    ln -sfn "$unix_lib/wineopenxr.so" "$rt/aarch64-unix/wineopenxr_a64.so"
    cat > "$rt/wineopenxr_a64.json" <<'EOF'
{
   "file_format_version": "1.0.0",
   "runtime": {
      "library_path": "C:\\bs-arm64\\aarch64-windows\\wineopenxr_a64.dll"
   }
}
EOF
    proton_version > "$rt/proton-version"

    # Our openxr_loader.dll prefers ActiveRuntimeARM64 over Proton's ActiveRuntime
    # (which points at the ARM64EC wineopenxr a pure ARM64 process cannot load).
    log "registry: HKLM\\Software\\Khronos\\OpenXR\\1 ActiveRuntimeARM64"
    # Time limits: a hanging wine must end in an error message, not a stuck installer.
    PATH="$PROTON/files/bin-arm64:$PATH" WINEPREFIX=$pfx WINEDEBUG=-all \
        timeout 180 "$PROTON/files/bin-arm64/wine" reg add 'HKLM\Software\Khronos\OpenXR\1' \
        /v ActiveRuntimeARM64 /t REG_SZ /d 'C:\bs-arm64\wineopenxr_a64.json' /f >/dev/null ||
        die "setting the OpenXR runtime in the Wine prefix failed or timed out"
    # Up to 0.2.0 our own eye-tracking layer (for our DXVK foveation) was registered here; Valve's
    # fdm_injection layer replaces both.
    if [ -f "$rt/XrApiLayer_bs_arm64_gaze.json" ]; then
        log "removing the old bs-arm64 eye-tracking layer"
        PATH="$PROTON/files/bin-arm64:$PATH" WINEPREFIX=$pfx WINEDEBUG=-all \
            timeout 180 "$PROTON/files/bin-arm64/wine" reg delete 'HKLM\Software\Khronos\OpenXR\1\ApiLayers\Implicit' \
            /v 'C:\bs-arm64\XrApiLayer_bs_arm64_gaze.json' /f >/dev/null 2>&1 || true
        rm -f "$rt/XrApiLayer_bs_arm64_gaze.json" "$rt/XrApiLayer_bs_arm64_gaze.dll"
    fi
    PATH="$PROTON/files/bin-arm64:$PATH" WINEPREFIX=$pfx \
        timeout 60 "$PROTON/files/bin-arm64/wineserver" -w ||
        die "Wine in $pfx did not shut down; restart the device and try again"
}

# "1.44.1": from the build string in globalgamemanagers ("1.44.1_20239", as BSManager reads it).
# BeatSaberVersion.txt only exists after the game or BSIPA ran once.
game_version() {
    local v
    v=$( (grep -a -o '[0-9]\+\.[0-9]\+\.[0-9]\+_[0-9]\+' "$1/Beat Saber_Data/globalgamemanagers" || true) | head -n1)
    [ -n "$v" ] || v=$(cat "$1/BeatSaberVersion.txt" 2>/dev/null || true)
    echo "${v%%_*}" | grep . || echo unknown
}

# Unity engine version baked into the instance, e.g. "6000.0.40f1". The native runtime (player,
# mono, plugins) is engine-specific, not Beat Saber-version specific, so this is what we gate on.
engine_version() {
    (grep -a -o '[0-9]\{4\}\.[0-9]\+\.[0-9]\+f[0-9]\+' "$1/Beat Saber_Data/globalgamemanagers" || true) | head -n1
}

cmd_install() {
    INSTANCE=${POSITIONAL[0]:-}
    [ -n "$INSTANCE" ] && [ -f "$INSTANCE/Beat Saber_Data/globalgamemanagers" ] || die "usage: install <Beat Saber instance dir>"
    INSTANCE=$(cd "$INSTANCE" && pwd)
    local version engine
    version=$(game_version "$INSTANCE")
    engine=$(engine_version "$INSTANCE")
    [ "$engine" = "$UNITY_VERSION" ] || die "instance is Unity ${engine:-unknown} (Beat Saber $version); this runtime is built for Unity $UNITY_VERSION"
    # lsteamclient_a64/wineopenxr_a64 talk to this Proton's unix libraries: the build must match.
    case $(proton_version) in
        "$PROTON_TAG" | "$PROTON_TAG"-*) ;;
        *) die "Proton is $(proton_version), but these DLLs were built for $PROTON_TAG; rebuild them (docs/BUILD.md)" ;;
    esac
    for f in lsteamclient_a64.dll wineopenxr_a64.dll steam_api64.dll openxr_loader.dll dxgi.dll d3d11.dll MonoPosixHelper.dll \
             LIV_Bridge.dll ucrtbs64.dll vcruntime140.dll msvcp140.dll; do
        [ -f "$ARTIFACTS/$f" ] || die "$ARTIFACTS/$f missing; run build.sh first (or pass --artifacts)"
    done
    [ -d "$PREFIX/pfx/drive_c" ] || die "Wine prefix $PREFIX/pfx does not exist; start any game with this prefix once first"
    [ -f "$PROTON/files/lib/wine/aarch64-unix/lsteamclient.so" ] || die "$PROTON is not an ARM64 Proton"
    require_prefix_idle
    cmd_fetch

    local unity=$CACHE/unity-$UNITY_VERSION/$PLAYER_VARIATION
    local oxr=$CACHE/unity-openxr-$UNITY_OPENXR_VERSION/UnityOpenXR.dll plugins="Beat Saber_Data/Plugins/ARM64"
    mkdir -p "$INSTANCE/$STATE_DIR"
    touch "$INSTANCE/$STATE_DIR/added"

    log "installing into $INSTANCE"
    # Unity engine (ARM64 player of the same Unity version the game was built with)
    install_file "$unity/WindowsPlayer.exe" "Beat Saber.exe"
    install_file "$unity/UnityPlayer.dll" "UnityPlayer.dll"
    install_file "$unity/UnityCrashHandler64.exe" "UnityCrashHandler64.exe"
    install_file "$unity/MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll" "MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll"
    install_file "$ARTIFACTS/MonoPosixHelper.dll" "MonoBleedingEdge/EmbedRuntime/MonoPosixHelper.dll"
    # Graphics (app dir wins over the ARM64EC DXVK Proton puts in system32)
    install_file "$ARTIFACTS/dxgi.dll" "dxgi.dll"
    install_file "$ARTIFACTS/d3d11.dll" "d3d11.dll"
    # Private Wine CRT: the wrappers import ucrtbs64 instead of the shared ucrtbase.
    # No runtime registry overrides or Proton/prefix DLL replacement are needed.
    install_file "$ARTIFACTS/ucrtbs64.dll" "ucrtbs64.dll"
    install_file "$ARTIFACTS/vcruntime140.dll" "vcruntime140.dll"
    install_file "$ARTIFACTS/msvcp140.dll" "msvcp140.dll"
    # Pure ARM64 uses __CxxFrameHandler3; none of this game's ARM64 DLLs import
    # vcruntime140_1. Retire the Microsoft DLL installed by previous releases.
    retire_installed_file vcruntime140_1.dll
    # Native plugins, looked up by the ARM64 player in Plugins/ARM64
    install_file "$ARTIFACTS/steam_api64.dll" "$plugins/steam_api64.dll"
    # The game's LIV SDK has an x64-only bridge; without this stub it throws every frame
    install_file "$ARTIFACTS/LIV_Bridge.dll" "$plugins/LIV_Bridge.dll"
    # lsteamclient_a64.dll lives only in the prefix runtime dir (C:\bs-arm64): BSIPA's
    # anti-piracy check rejects large '*steam*' files inside the game folder.
    if [ -f "$INSTANCE/$plugins/lsteamclient_a64.dll" ]; then
        rm -f "$INSTANCE/$plugins/lsteamclient_a64.dll"
        sed -i '\#/lsteamclient_a64.dll$#d' "$INSTANCE/$STATE_DIR/added"
    fi
    install_file "$oxr" "$plugins/UnityOpenXR.dll"
    install_file "$ARTIFACTS/openxr_loader.dll" "$plugins/openxr_loader.dll"
    # UnityOpenXR (UWP build) loads the loader by bare name: must be next to the exe
    install_file "$ARTIFACTS/openxr_loader.dll" "openxr_loader.dll"

    if [ "$MODS" = 1 ]; then
        install_bsipa_fixes
    else
        restore_bsipa_files
    fi
    echo "$MODS" > "$INSTANCE/$STATE_DIR/mods"
    setup_prefix
    proton_version > "$INSTANCE/$STATE_DIR/proton-version"
    echo "$version" > "$INSTANCE/$STATE_DIR/installed"
    log "done"
    # Run by hand (not from a launcher such as BSManager): show how to start it
    [ -t 1 ] && log "start with: $0 launch '$INSTANCE'"
    return 0
}

cmd_uninstall() {
    INSTANCE=${POSITIONAL[0]:-}
    [ -n "$INSTANCE" ] && [ -f "$INSTANCE/$STATE_DIR/installed" ] || die "usage: uninstall <patched instance dir>"
    require_prefix_idle
    log "restoring x64 files in $INSTANCE"
    (cd "$INSTANCE/$STATE_DIR/backup" && find . -type f -print0) | while IFS= read -r -d '' f; do
        f=${f#./}
        # BSIPA's own files: only while BSIPA is still installed (uninstalling BSIPA removes them)
        case $f in
            winhttp.dll | Libs/MonoMod.Core.dll) [ -e "$INSTANCE/$f" ] || continue ;;
        esac
        cp -p "$INSTANCE/$STATE_DIR/backup/$f" "$INSTANCE/$f"
    done
    while IFS= read -r f; do [ -n "$f" ] && rm -f "$INSTANCE/$f"; done < "$INSTANCE/$STATE_DIR/added"
    rmdir "$INSTANCE/Beat Saber_Data/Plugins/ARM64" 2>/dev/null || true
    rm -rf "${INSTANCE:?}/$STATE_DIR"
    log "done (the prefix runtime in $PREFIX/pfx/$RUNTIME_DIR is left in place)"
}

# --- launch ------------------------------------------------------------------

cmd_launch() {
    INSTANCE=${POSITIONAL[0]:-}
    [ -n "$INSTANCE" ] && [ -f "$INSTANCE/$STATE_DIR/installed" ] || die "usage: launch <patched instance dir>"
    INSTANCE=$(cd "$INSTANCE" && pwd)
    local rt=$PREFIX/pfx/$RUNTIME_DIR built_for
    built_for=$(cat "$rt/proton-version" 2>/dev/null || echo unknown)
    # lsteamclient/wineopenxr Windows halves must match Proton's unix halves exactly.
    [ "$built_for" = "$(proton_version)" ] || die "Proton changed ($built_for -> $(proton_version)); rebuild and reinstall"
    # Installed with --no-mods: BSIPA's winhttp.dll (if any) is still the x64 one.
    [ "$(cat "$INSTANCE/$STATE_DIR/mods" 2>/dev/null || echo 1)" = 1 ] || MODS=0
    # Mod loader: BSIPA's Doorstop (winhttp.dll) in the game dir, else Wine's builtin.
    # Without mods, always the builtin, so Doorstop never loads.
    local winhttp=n,b
    [ "$MODS" = 1 ] || { winhttp=b; log "starting without mods"; }

    # Started outside a graphical session (e.g. over SSH): use the device's main X display.
    local env=(
        DISPLAY="${DISPLAY:-:0}"
        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        SteamAppId=$BS_APP_ID SteamGameId=$BS_APP_ID SteamOverlayGameId=$BS_APP_ID SteamEnv=1
        STEAM_COMPAT_APP_ID=$BS_APP_ID
        STEAM_COMPAT_DATA_PATH="$PREFIX"
        STEAM_COMPAT_INSTALL_PATH="$INSTANCE"
        STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.steam/steam"
        WINEDLLPATH="$rt"
        WINEDLLOVERRIDES="winhttp=$winhttp"
    )
    # Valve's foveated rendering (fdm_injection): its OpenXR half is an implicit layer, its Vulkan
    # half must be enabled explicitly, as Steam does for "Foveated Rendering". With only the
    # OpenXR half active, vkCreateDevice hangs, so without --foveation turn both off.
    if [ "$FOVEATION" = 1 ]; then
        env+=(FDM_DEBUG="${FDM_DEBUG:-enable}" VK_INSTANCE_LAYERS=VK_LAYER_VALVE_rpo:VK_LAYER_VALVE_fdm_injection)
    else
        env+=(DISABLE_VULKAN_FDM_INJECTION_LAYER=1)
    fi
    if [ "$DEBUG" = 1 ]; then
        env+=(STEAMAPI_ARM64_LOG=1 XR_LOADER_DEBUG=all DXVK_LOG_LEVEL=info
              WINEDEBUG=+loaddll,err,warn+openxr,warn+module,+debugstr)
    fi
    log "launching $INSTANCE (log: /tmp/bs-arm64.log)"
    cd "$INSTANCE"
    env "${env[@]}" setsid "$PROTON/proton" run "$INSTANCE/Beat Saber.exe" > /tmp/bs-arm64.log 2>&1 < /dev/null &
    echo "pid $!"
}

[ $# -ge 1 ] || { sed -n '2,25p' "$0"; exit 1; }
CMD=$1; shift
parse_opts "$@"
case $CMD in
    fetch) cmd_fetch ;;
    install) cmd_install ;;
    uninstall) cmd_uninstall ;;
    launch) cmd_launch ;;
    -h|--help|help) sed -n '2,25p' "$0" ;;
    *) die "unknown command $CMD" ;;
esac
