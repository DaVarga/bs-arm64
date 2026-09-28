// Minimal, header-free Windows ARM64 test for MSVC-style C++ exception handling
// (__CxxFrameHandler3 tables, as clang emits them for *-windows-msvc).
typedef void *HANDLE;
typedef unsigned long DWORD;
extern "C" __declspec(dllimport) HANDLE __stdcall GetStdHandle(DWORD);
extern "C" __declspec(dllimport) int __stdcall WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
extern "C" __declspec(dllimport) HANDLE __stdcall CreateFileA(const char *, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
extern "C" __declspec(dllimport) DWORD __stdcall SetFilePointer(HANDLE, long, long *, DWORD);
extern "C" __declspec(dllimport) int __stdcall CloseHandle(HANDLE);

static unsigned slen(const char *s) { unsigned n = 0; while (s[n]) n++; return n; }

// Log to stdout and append to cxxeh.log (Proton may not forward stdout)
static void say(const char *s) {
    DWORD w;
    WriteFile(GetStdHandle((DWORD)-11), s, slen(s), &w, 0);
    HANDLE f = CreateFileA("cxxeh.log", 0x40000000 /*GENERIC_WRITE*/, 1, 0, 4 /*OPEN_ALWAYS*/, 0x80, 0);
    if (f != (HANDLE)-1) { SetFilePointer(f, 0, 0, 2 /*FILE_END*/); WriteFile(f, s, slen(s), &w, 0); CloseHandle(f); }
}

struct Err { int code; };
struct Guard { const char *name; __declspec(noinline) ~Guard() { say("  unwind: "); say(name); say("\n"); } };

// type_info's vtable: MSVC programs get it from the static part of vcruntime; the EH code matches
// catch types by their decorated names, so a placeholder is enough here
extern "C" __declspec(selectany) const void *const type_info_vftable[4] __asm__("??_7type_info@@6B@") = {0, 0, 0, 0};
