/*
 * Workaround for Wine bug 60453 (https://bugs.winehq.org/show_bug.cgi?id=60453).
 *
 * On ARM64, Wine's call_user_mode_callback() (dlls/ntdll/unix/signal_arm64.c)
 * saves FPSR over FPCR ("bfi x1, x2, #0, #32" instead of "#32, #32"), so every
 * user callback (window procedures, hooks, ...) returns with FPCR = old FPSR.
 * On FEAT_AFP CPUs that turns on FPCR.FIZ/AH and denormal inputs read as zero,
 * which breaks Mathf.Approximately and with it some environments (issue #8).
 *
 * Patch that one instruction in this process's copy of ntdll.so. The code sits
 * just before __wine_syscall_dispatcher, which Wine's PE ntdll exports a
 * pointer to. Wine doesn't manage the memory of ntdll.so, so VirtualProtect
 * and WriteProcessMemory can't change it; Linux mprotect is called directly.
 * The mapping is private: ntdll.so on disk and other processes are unaffected.
 * On a Wine with the fix the sequence isn't found and nothing happens.
 *
 * STEAMAPI_ARM64_FPCR_FIX=0 disables it.
 */
#include "steam_api_shim.h"

#include <windows.h>
#include <stdlib.h>
#include <string.h>

static const DWORD bad_seq[3] = {
    0xd53b4401, /* mrs x1, fpcr */
    0xd53b4422, /* mrs x2, fpsr */
    0xb3407c41, /* bfi x1, x2, #0, #32 */
};
static const DWORD good_bfi = 0xb3607c41; /* bfi x1, x2, #32, #32 */

/* Linux arm64 syscall ABI: number in x8, arguments in x0..x2, result in x0. */
static const long long LINUX_NR_MPROTECT = 226;
static const long long LINUX_PROT_RX = 0x1 | 0x4;
static const long long LINUX_PROT_RWX = 0x1 | 0x2 | 0x4;
static const ULONG_PTR LINUX_PAGE_SIZE = 4096;

static long long linux_mprotect(void *addr, unsigned long long len, long long prot)
{
    register long long x8 __asm__("x8") = LINUX_NR_MPROTECT;
    register long long x0 __asm__("x0") = (long long)addr;
    register long long x1 __asm__("x1") = (long long)len;
    register long long x2 __asm__("x2") = prot;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory");
    return x0;
}

static unsigned long long get_fpcr(void)
{
    unsigned long long v;
    __asm__ volatile("mrs %0, fpcr" : "=r"(v));
    return v;
}

static void set_fpcr(unsigned long long v)
{
    __asm__ volatile("msr fpcr, %0" :: "r"(v));
}

void fpcr_fix(void)
{
    const char *env = getenv("STEAMAPI_ARM64_FPCR_FIX");
    if (env && !strcmp(env, "0")) return;

    void **disp = (void **)GetProcAddress(GetModuleHandleA("ntdll"), "__wine_syscall_dispatcher");
    if (!disp || !*disp) return; /* not Wine on ARM64 */

    DWORD code[1024];
    char *base = (char *)*disp - sizeof(code);
    SIZE_T read;
    if (!ReadProcessMemory(GetCurrentProcess(), base, code, sizeof(code), &read))
    {
        shim_log("fpcr fix: can't read ntdll.so code, error %lu", GetLastError());
        return;
    }

    char *hit = NULL;
    int hits = 0;
    for (size_t i = 0; i + 3 <= sizeof(code) / sizeof(code[0]); i++)
        if (!memcmp(&code[i], bad_seq, sizeof(bad_seq)))
        {
            hit = base + i * sizeof(DWORD) + 2 * sizeof(DWORD);
            hits++;
        }
    if (hits != 1)
    {
        if (hits) shim_log("fpcr fix: %d matches, not patching", hits);
        return; /* 0: this Wine has the fix */
    }

    void *page = (void *)((ULONG_PTR)hit & ~(LINUX_PAGE_SIZE - 1));
    long long err = linux_mprotect(page, LINUX_PAGE_SIZE, LINUX_PROT_RWX);
    if (err)
    {
        shim_log("fpcr fix: mprotect failed (%lld), not patching", err);
        return;
    }
    *(volatile DWORD *)hit = good_bfi;
    err = linux_mprotect(page, LINUX_PAGE_SIZE, LINUX_PROT_RX);
    FlushInstructionCache(GetCurrentProcess(), hit, sizeof(DWORD));

    /* Callbacks before this point may have left FIZ/AH (bits 0-1) set on this thread. */
    unsigned long long fpcr = get_fpcr();
    set_fpcr(fpcr & ~3ull);
    shim_log("fpcr fix: patched ntdll.so at %p (restore %lld), fpcr was %08llx", hit, err, fpcr);
}
