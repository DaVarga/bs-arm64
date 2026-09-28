#include "common.h"

__declspec(noinline) static void thrower() { Guard g{"dll thrower"}; throw Err{42}; }

// Throws and catches inside the DLL, like UnityOpenXR does
extern "C" __declspec(dllexport) int dll_throw_catch() {
    try { Guard g{"dll try"}; thrower(); }
    catch (Err &e) { return e.code; }
    return -1;
}

// Throws out of the DLL, to be caught by the caller
extern "C" __declspec(dllexport) void dll_throw() { Guard g{"dll_throw"}; throw Err{7}; }

extern "C" int __stdcall _DllMainCRTStartup(void *, DWORD, void *) { return 1; }

// MSVC layout: a function with C++ EH state whose last instruction is the call to a noreturn
// throw helper (MSVC emits nothing after it). The return address then points past the end of
// the function. clang adds a brk after the call; build.sh cuts it out of the function's range.
extern "C" __declspec(noinline) __declspec(noreturn) void throw_helper() { throw Err{5}; }
extern "C" __declspec(dllexport) void dll_call_throw_helper_last() { Guard g{"dll_call_throw_helper_last"}; throw_helper(); }
