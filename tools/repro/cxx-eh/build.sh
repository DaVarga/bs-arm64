#!/bin/bash
# Build the Wine ARM64 C++ EH reproducer (docs/UPSTREAM.md #2) with llvm-mingw's clang in MSVC mode,
# no MSVC needed: cxxeh.exe + cxxdll.dll, importing vcruntime140.dll like MSVC-built code (/MD).
#   build.sh [llvm-mingw bin dir]
# Run: cxxeh.exe [1-5] under Proton/Wine, once as is (Wine's ucrtbase) and once with Microsoft's
# ARM64 vcruntime140.dll next to it. Case 5 crashes with Wine's runtime at __CxxFrameHandler3.
# Results are also appended to cxxeh.log in the working directory.
set -e
cd "$(dirname "$0")"
T=${1:-../../../deps/llvm-mingw/bin}
F="--target=aarch64-pc-windows-msvc -O1 -fexceptions -fcxx-exceptions -fms-extensions -c"
"$T/clang++" $F cxxdll.cpp -o cxxdll.obj
"$T/clang++" $F cxxeh.cpp -o cxxeh.obj
"$T/llvm-dlltool" -m arm64 -d vcruntime140.def -l vcruntime140.lib
"$T/llvm-dlltool" -m arm64 -d kernel32.def -l kernel32.lib
"$T/lld-link" /nologo /dll /nodefaultlib /entry:_DllMainCRTStartup /machine:arm64 cxxdll.obj vcruntime140.lib kernel32.lib \
    /out:cxxdll.dll /implib:cxxdll.lib
"$T/lld-link" /nologo /nodefaultlib /entry:mainCRTStartup /subsystem:console /machine:arm64 cxxeh.obj cxxdll.lib \
    vcruntime140.lib kernel32.lib /out:cxxeh.exe
# MSVC ends a function right after a call to a noreturn function; clang adds a brk. Cut it off.
rva=$("$T/llvm-readobj" --coff-exports cxxdll.dll | awk '/Name: dll_call_throw_helper_last/{f=1} f&&/RVA:/{print $2; exit}')
python3 msvc_layout.py cxxdll.dll "${rva#0x}"
rm -f ./*.obj ./*.lib ./*.exp
ls -l cxxeh.exe cxxdll.dll
