#include "common.h"

extern "C" __declspec(dllimport) int dll_throw_catch();
extern "C" __declspec(dllimport) void dll_throw();
extern "C" __declspec(dllimport) void dll_call_throw_helper_last();
extern "C" __declspec(dllimport) char *__stdcall GetCommandLineA();
extern "C" __declspec(dllimport) void __stdcall ExitProcess(unsigned);

__declspec(noinline) static void thrower() { Guard g{"exe thrower"}; throw Err{1}; }

static int case_local() {
    try { Guard g{"exe try"}; thrower(); }
    catch (Err &e) { return e.code == 1; }
    return 0;
}
static int case_dll_internal() { return dll_throw_catch() == 42; }
static int case_across_dll() {
    try { dll_throw(); }
    catch (Err &e) { return e.code == 7; }
    return 0;
}
static int case_throw_at_end() {
    try { dll_call_throw_helper_last(); }
    catch (Err &e) { return e.code == 5; }
    return 0;
}
static int case_catch_all() {
    try { thrower(); }
    catch (...) { return 1; }
    return 0;
}

// cxxeh.exe [1-5]: run one case (a crash then only takes that case down); no argument: all
extern "C" void mainCRTStartup() {
    const char *cl = GetCommandLineA();
    char which = 0;
    for (const char *p = cl; *p; p++) if (*p >= '1' && *p <= '5' && (p[-1] == ' ')) which = *p;
    struct { char id; const char *name; int (*fn)(); } cases[] = {
        {'1', "throw/catch in exe", case_local},
        {'2', "throw/catch inside dll", case_dll_internal},
        {'3', "throw in dll, catch in exe", case_across_dll},
        {'4', "catch (...) in exe", case_catch_all},
        {'5', "dll function ending with a call to a noreturn throw helper", case_throw_at_end},
    };
    int fails = 0;
    for (auto &c : cases) {
        if (which && c.id != which) continue;
        say("case "); char id[2] = {c.id, 0}; say(id); say(": "); say(c.name); say("\n");
        int ok = c.fn();
        say(ok ? "  caught: OK\n" : "  FAILED\n");
        fails += !ok;
    }
    ExitProcess(fails);
}
