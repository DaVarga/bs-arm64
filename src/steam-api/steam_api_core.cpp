/*
 * ARM64 steam_api64.dll replacement: core (init, pipes, callbacks, interface lookup).
 *
 * Talks to a pure ARM64 build of Proton's lsteamclient (lsteamclient_a64.dll),
 * which forwards to the native Linux steamclient.so through Wine's unix call
 * interface. Interface method calls are done by flat_generated.cpp.
 */
#include "steam_api_shim.h"

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


typedef void *(__cdecl *CreateInterfaceFn)(const char *name, int *return_code);
typedef bool (__cdecl *Steam_BGetCallbackFn)(HSteamPipe pipe, CallbackMsg_t *msg, int32 *ignored);
typedef bool (__cdecl *Steam_FreeLastCallbackFn)(HSteamPipe pipe);
typedef bool (__cdecl *Steam_GetAPICallResultFn)(HSteamPipe pipe, SteamAPICall_t call, void *callback,
                                                 int callback_len, int id, bool *failed);
typedef void (__cdecl *Steam_ReleaseThreadLocalMemoryFn)(int thread_exit);

static const char *const CLIENT_DLL_DEFAULT = "lsteamclient_a64.dll";
static const char *const CLIENT_RUNTIME_DIR = "C:\\bs-arm64\\aarch64-windows";
static const char *const CLIENT_INTERFACE = "SteamClient021";

static CRITICAL_SECTION g_cs;
static HMODULE g_client_module;
static CreateInterfaceFn p_CreateInterface;
static Steam_BGetCallbackFn p_Steam_BGetCallback;
static Steam_FreeLastCallbackFn p_Steam_FreeLastCallback;
static Steam_GetAPICallResultFn p_Steam_GetAPICallResult;
static Steam_ReleaseThreadLocalMemoryFn p_Steam_ReleaseThreadLocalMemory;

static ISteamClient *g_client;
static HSteamPipe g_pipe;
static HSteamUser g_user;
static bool g_manual_dispatch;
static bool g_try_catch_callbacks [[maybe_unused]] = true;
static uintptr_t g_context_counter = 1;
/* Small growable arrays instead of the C++ standard library: keeps the DLL well under
 * BSIPA's anti-piracy size heuristic for Steam DLLs (>= 350 KB named '*steam*'). */
struct iface_entry
{
    char *version;
    void *iface;
};
static iface_entry *g_user_interfaces;
static size_t g_user_interface_count;

S_API ISteamClient *g_pSteamClientGameServer = NULL;

/* STEAMAPI_ARM64_LOG=1 logs to stderr; any other value is a file to append to. */
static void shim_log(const char *fmt, ...)
{
    static int enabled = -1;
    static FILE *out;
    if (enabled < 0)
    {
        const char *dest = getenv("STEAMAPI_ARM64_LOG");
        enabled = dest != NULL;
        out = dest && strcmp(dest, "1") ? fopen(dest, "a") : NULL;
        if (!out) out = stderr;
    }
    if (!enabled) return;
    va_list args;
    va_start(args, fmt);
    fprintf(out, "steam_api64(arm64) [%04lx]: ", GetCurrentThreadId());
    vfprintf(out, fmt, args);
    fputc('\n', out);
    fflush(out);
    va_end(args);
}

#ifdef SHIM_TRACE_CALLS
void shim_trace(const char *name)
{
    shim_log("%s", name);
}
#endif

static void set_err(SteamErrMsg *out, const char *msg)
{
    shim_log("init failed: %s", msg);
    if (out) snprintf(*out, sizeof(*out), "%s", msg);
}

static bool load_client_module(void)
{
    if (g_client_module) return true;

    const char *name = getenv("STEAMAPI_ARM64_CLIENT_DLL");
    if (!name || !*name) name = CLIENT_DLL_DEFAULT;

    /* Wine resolves the builtin (and its unix half) through WINEDLLPATH only after it
     * finds a builtin-marked file on the normal search path. Try, in order: a copy next
     * to this DLL, the prefix runtime directory set up by the installer (which keeps
     * large '*steam*' files out of the game folder), then the normal search path. */
    if (!strchr(name, '\\') && !strchr(name, '/'))
    {
        char path[MAX_PATH];
        HMODULE self = NULL;
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)&load_client_module, &self);
        if (self && GetModuleFileNameA(self, path, sizeof(path)))
        {
            char *slash = strrchr(path, '\\');
            if (slash && (size_t)(slash + 1 - path) + strlen(name) < sizeof(path))
            {
                strcpy(slash + 1, name);
                if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) g_client_module = LoadLibraryA(path);
            }
        }
        if (!g_client_module && snprintf(path, sizeof(path), "%s\\%s", CLIENT_RUNTIME_DIR, name) < (int)sizeof(path) &&
            GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES)
            g_client_module = LoadLibraryA(path);
    }
    if (!g_client_module) g_client_module = LoadLibraryA(name);
    if (!g_client_module)
    {
        shim_log("failed to load %s, error %lu", name, GetLastError());
        return false;
    }

    p_CreateInterface = (CreateInterfaceFn)GetProcAddress(g_client_module, "CreateInterface");
    p_Steam_BGetCallback = (Steam_BGetCallbackFn)GetProcAddress(g_client_module, "Steam_BGetCallback");
    p_Steam_FreeLastCallback = (Steam_FreeLastCallbackFn)GetProcAddress(g_client_module, "Steam_FreeLastCallback");
    p_Steam_GetAPICallResult = (Steam_GetAPICallResultFn)GetProcAddress(g_client_module, "Steam_GetAPICallResult");
    p_Steam_ReleaseThreadLocalMemory =
        (Steam_ReleaseThreadLocalMemoryFn)GetProcAddress(g_client_module, "Steam_ReleaseThreadLocalMemory");
    if (!p_CreateInterface || !p_Steam_BGetCallback || !p_Steam_FreeLastCallback || !p_Steam_GetAPICallResult)
    {
        shim_log("%s is missing required exports", name);
        FreeLibrary(g_client_module);
        g_client_module = NULL;
        return false;
    }
    return true;
}

static void ensure_app_id_env(void)
{
    char buf[32];
    if (GetEnvironmentVariableA("SteamAppId", buf, sizeof(buf))) return;

    FILE *f = fopen("steam_appid.txt", "r");
    if (!f) return;
    unsigned int appid = 0;
    if (fscanf(f, "%u", &appid) == 1 && appid)
    {
        snprintf(buf, sizeof(buf), "%u", appid);
        SetEnvironmentVariableA("SteamAppId", buf);
        SetEnvironmentVariableA("SteamGameId", buf);
    }
    fclose(f);
}

S_API ESteamAPIInitResult S_CALLTYPE SteamInternal_SteamAPI_Init(const char *pszInternalCheckInterfaceVersions,
                                                                 SteamErrMsg *pOutErrMsg)
{
    ESteamAPIInitResult result = k_ESteamAPIInitResult_OK;

    EnterCriticalSection(&g_cs);
    if (g_client && g_user) goto done;

    ensure_app_id_env();
    if (!load_client_module())
    {
        set_err(pOutErrMsg, "Failed to load the ARM64 steamclient (lsteamclient_a64.dll)");
        result = k_ESteamAPIInitResult_NoSteamClient;
        goto done;
    }

    g_client = (ISteamClient *)p_CreateInterface(CLIENT_INTERFACE, NULL);
    if (!g_client)
    {
        set_err(pOutErrMsg, "steamclient does not provide " "SteamClient021");
        result = k_ESteamAPIInitResult_VersionMismatch;
        goto done;
    }

    g_pipe = SteamAPI_ISteamClient_CreateSteamPipe(g_client);
    if (!g_pipe)
    {
        set_err(pOutErrMsg, "Failed to create a Steam pipe; is Steam running?");
        result = k_ESteamAPIInitResult_NoSteamClient;
        goto done;
    }

    g_user = SteamAPI_ISteamClient_ConnectToGlobalUser(g_client, g_pipe);
    if (!g_user)
    {
        SteamAPI_ISteamClient_BReleaseSteamPipe(g_client, g_pipe);
        g_pipe = 0;
        set_err(pOutErrMsg, "Failed to connect to the Steam user; is Steam running and logged in?");
        result = k_ESteamAPIInitResult_NoSteamClient;
        goto done;
    }

    for (const char *ver = pszInternalCheckInterfaceVersions; ver && *ver; ver += strlen(ver) + 1)
    {
        if (!SteamAPI_ISteamClient_GetISteamGenericInterface(g_client, g_user, g_pipe, ver))
        {
            char msg[256];
            snprintf(msg, sizeof(msg), "No interface %s; the Steam client may be out of date", ver);
            set_err(pOutErrMsg, msg);
            SteamAPI_ISteamClient_ReleaseUser(g_client, g_pipe, g_user);
            SteamAPI_ISteamClient_BReleaseSteamPipe(g_client, g_pipe);
            g_pipe = 0;
            g_user = 0;
            result = k_ESteamAPIInitResult_VersionMismatch;
            goto done;
        }
    }

    ++g_context_counter;
    shim_log("initialized: pipe %d user %d", g_pipe, g_user);
    if (pOutErrMsg) (*pOutErrMsg)[0] = 0;

done:
    LeaveCriticalSection(&g_cs);
    return result;
}

S_API ESteamAPIInitResult S_CALLTYPE SteamAPI_InitFlat(SteamErrMsg *pOutErrMsg)
{
    return SteamInternal_SteamAPI_Init(NULL, pOutErrMsg);
}

S_API bool S_CALLTYPE SteamAPI_InitSafe()
{
    return SteamInternal_SteamAPI_Init(NULL, NULL) == k_ESteamAPIInitResult_OK;
}

/* SDK 1.58 and older (e.g. Beat Saber 1.40.x, Steamworks.NET 20.2): a plain export
 * instead of the inline SteamAPI_Init() around SteamInternal_SteamAPI_Init. The SDK header
 * defines that inline one, hence the different C++ name. */
extern "C" __declspec(dllexport) bool S_CALLTYPE legacy_SteamAPI_Init() __asm__("SteamAPI_Init");
extern "C" bool S_CALLTYPE legacy_SteamAPI_Init()
{
    bool ok = SteamAPI_InitSafe();
    shim_log("SteamAPI_Init (SDK 1.58 or older): %d", ok);
    return ok;
}

S_API bool S_CALLTYPE SteamAPI_InitAnonymousUser()
{
    return SteamAPI_InitSafe();
}

S_API void S_CALLTYPE SteamAPI_Shutdown()
{
    EnterCriticalSection(&g_cs);
    if (g_client)
    {
        if (g_pipe && g_user) SteamAPI_ISteamClient_ReleaseUser(g_client, g_pipe, g_user);
        if (g_pipe) SteamAPI_ISteamClient_BReleaseSteamPipe(g_client, g_pipe);
        SteamAPI_ISteamClient_BShutdownIfAllPipesClosed(g_client);
    }
    g_pipe = 0;
    g_user = 0;
    g_client = NULL;
    for (size_t i = 0; i < g_user_interface_count; ++i) free(g_user_interfaces[i].version);
    free(g_user_interfaces);
    g_user_interfaces = NULL;
    g_user_interface_count = 0;
    ++g_context_counter;
    LeaveCriticalSection(&g_cs);
}

S_API bool S_CALLTYPE SteamAPI_RestartAppIfNecessary(uint32 unOwnAppID)
{
    return false;
}

S_API void S_CALLTYPE SteamAPI_ReleaseCurrentThreadMemory()
{
    if (p_Steam_ReleaseThreadLocalMemory) p_Steam_ReleaseThreadLocalMemory(0);
}

S_API void S_CALLTYPE SteamAPI_WriteMiniDump(uint32 uStructuredExceptionCode, void *pvExceptionInfo, uint32 uBuildID)
{
}

S_API void S_CALLTYPE SteamAPI_SetMiniDumpComment(const char *pchMsg)
{
}

S_API void S_CALLTYPE SteamAPI_UseBreakpadCrashHandler(char const *pchVersion, char const *pchDate,
                                                       char const *pchTime, bool bFullMemoryDumps, void *pvContext,
                                                       PFNPreMinidumpCallback m_pfnPreMinidumpCallback)
{
}

S_API void S_CALLTYPE SteamAPI_SetBreakpadAppID(uint32 unAppID)
{
}

S_API void SteamAPI_SetTryCatchCallbacks(bool bTryCatchCallbacks)
{
    g_try_catch_callbacks = bTryCatchCallbacks;
}

static bool read_steam_reg(const char *subkey, const char *value, DWORD type, void *data, DWORD size)
{
    HKEY key;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, subkey, 0, KEY_QUERY_VALUE, &key)) return false;
    DWORD actual_type = 0;
    LSTATUS status = RegQueryValueExA(key, value, NULL, &actual_type, (BYTE *)data, &size);
    RegCloseKey(key);
    return !status && actual_type == type;
}

S_API bool S_CALLTYPE SteamAPI_IsSteamRunning()
{
    if (g_pipe) return true;
    DWORD pid = 0;
    if (!read_steam_reg("Software\\Valve\\Steam\\ActiveProcess", "pid", REG_DWORD, &pid, sizeof(pid)) || !pid)
        return false;
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!process) return false;
    bool running = WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
    CloseHandle(process);
    return running;
}

S_API const char *SteamAPI_GetSteamInstallPath()
{
    static char path[MAX_PATH];
    if (!path[0] && !read_steam_reg("Software\\Valve\\Steam", "SteamPath", REG_SZ, path, sizeof(path) - 1))
        path[0] = 0;
    return path;
}

S_API HSteamPipe S_CALLTYPE SteamAPI_GetHSteamPipe()
{
    return g_pipe;
}

S_API HSteamUser S_CALLTYPE SteamAPI_GetHSteamUser()
{
    return g_user;
}

/* Undecorated legacy exports. */
extern "C" __declspec(dllexport) HSteamPipe GetHSteamPipe()
{
    return g_pipe;
}

extern "C" __declspec(dllexport) HSteamUser GetHSteamUser()
{
    return g_user;
}

S_API ISteamClient *SteamClient()
{
    return g_client;
}

/* Interface versions this shim implements (generated by gen.py). */
extern const char *const shim_interface_versions[];

static size_t version_number_start(const char *version)
{
    size_t n = strlen(version);
    while (n && version[n - 1] >= '0' && version[n - 1] <= '9') --n;
    return n;
}

/* The flat wrappers call our interface versions' vtables, so a game built against an older
 * SDK must get our version of an interface instead of the one it asks for. Its flat calls go
 * by name, and Valve only adds to or removes from an interface between versions; the few
 * flat functions it lost are passed to the old interface (LEGACY in gen.py). Newer versions
 * than ours and interfaces we don't have are left alone. */
const char *shim_map_interface_version(const char *version)
{
    if (!version) return version;
    size_t prefix = version_number_start(version);
    if (!prefix || !version[prefix]) return version;
    for (const char *const *ours = shim_interface_versions; *ours; ++ours)
    {
        if (version_number_start(*ours) != prefix || strncmp(*ours, version, prefix)) continue;
        if (atoi(version + prefix) >= atoi(*ours + prefix)) return version;
        shim_log("interface %s -> %s", version, *ours);
        return *ours;
    }
    return version;
}

S_API void *S_CALLTYPE SteamInternal_CreateInterface(const char *ver)
{
    ver = shim_map_interface_version(ver);
    if (!ver) return NULL;
    if (!strncmp(ver, "SteamClient", 11))
    {
        if (!load_client_module()) return NULL;
        return p_CreateInterface(ver, NULL);
    }
    if (!g_client) return NULL;
    return SteamAPI_ISteamClient_GetISteamGenericInterface(g_client, g_user, g_pipe, ver);
}

static void *find_or_create_user_interface(HSteamUser hSteamUser, const char *pszVersion)
{
    if (!g_client || !pszVersion) return NULL;

    EnterCriticalSection(&g_cs);
    void *iface = NULL;
    for (size_t i = 0; i < g_user_interface_count && !iface; ++i)
        if (!strcmp(g_user_interfaces[i].version, pszVersion)) iface = g_user_interfaces[i].iface;
    if (!iface && (iface = shim_raw_generic_interface(g_client, hSteamUser, g_pipe, pszVersion)))
    {
        iface_entry *grown = (iface_entry *)realloc(g_user_interfaces, (g_user_interface_count + 1) * sizeof(*grown));
        if (grown)
        {
            g_user_interfaces = grown;
            g_user_interfaces[g_user_interface_count].version = _strdup(pszVersion);
            g_user_interfaces[g_user_interface_count++].iface = iface;
        }
    }
    else if (!iface)
        shim_log("no user interface %s", pszVersion);
    LeaveCriticalSection(&g_cs);
    return iface;
}

S_API void *S_CALLTYPE SteamInternal_FindOrCreateUserInterface(HSteamUser hSteamUser, const char *pszVersion)
{
    return find_or_create_user_interface(hSteamUser, shim_map_interface_version(pszVersion));
}

/* The old interface version itself, for the flat functions newer SDKs dropped. */
void *shim_legacy_user_interface(const char *version)
{
    return find_or_create_user_interface(g_user, version);
}

/* Dropped from ISteamClient after SDK 1.58; the interface itself still exists. */
S_API void *SteamAPI_ISteamClient_GetISteamAppList(ISteamClient *self, HSteamUser hSteamUser, HSteamPipe hSteamPipe,
                                                   const char *pchVersion)
{
    return shim_raw_generic_interface(self, hSteamUser, hSteamPipe, pchVersion);
}

S_API void *S_CALLTYPE SteamInternal_ContextInit(void *pContextInitData)
{
    /* struct { void (*pFn)(void *pCtx); uintptr_t counter; <context> } */
    struct ContextInitData
    {
        void (*pFn)(void *ctx);
        uintptr_t counter;
        void *ctx[1];
    } *data = (ContextInitData *)pContextInitData;

    if (data->counter != g_context_counter)
    {
        EnterCriticalSection(&g_cs);
        if (data->counter != g_context_counter)
        {
            data->pFn(&data->ctx);
            data->counter = g_context_counter;
        }
        LeaveCriticalSection(&g_cs);
    }
    return &data->ctx;
}

/* --- Callbacks --- */

S_API void S_CALLTYPE SteamAPI_ManualDispatch_Init()
{
    SHIM_TRACE("SteamAPI_ManualDispatch_Init");
    g_manual_dispatch = true;
}

S_API void S_CALLTYPE SteamAPI_ManualDispatch_RunFrame(HSteamPipe hSteamPipe)
{
    /* lsteamclient pumps the pipe in Steam_BGetCallback. */
}

S_API bool S_CALLTYPE SteamAPI_ManualDispatch_GetNextCallback(HSteamPipe hSteamPipe, CallbackMsg_t *pCallbackMsg)
{
    if (!p_Steam_BGetCallback) return false;
    int32 ignored = 0;
    bool got = p_Steam_BGetCallback(hSteamPipe, pCallbackMsg, &ignored);
#ifdef SHIM_TRACE_CALLS
    if (got) shim_log("callback %d (%d bytes)", pCallbackMsg->m_iCallback, pCallbackMsg->m_cubParam);
#endif
    return got;
}

S_API void S_CALLTYPE SteamAPI_ManualDispatch_FreeLastCallback(HSteamPipe hSteamPipe)
{
    if (p_Steam_FreeLastCallback) p_Steam_FreeLastCallback(hSteamPipe);
}

S_API bool S_CALLTYPE SteamAPI_ManualDispatch_GetAPICallResult(HSteamPipe hSteamPipe, SteamAPICall_t hSteamAPICall,
                                                               void *pCallback, int cubCallback,
                                                               int iCallbackExpected, bool *pbFailed)
{
    if (!p_Steam_GetAPICallResult) return false;
    bool got = p_Steam_GetAPICallResult(hSteamPipe, hSteamAPICall, pCallback, cubCallback, iCallbackExpected, pbFailed);
#ifdef SHIM_TRACE_CALLS
    shim_log("call result %llu: callback %d, %d bytes -> %d failed %d", (unsigned long long)hSteamAPICall,
             iCallbackExpected, cubCallback, got, pbFailed ? *pbFailed : -1);
#endif
    return got;
}

/*
 * Legacy CCallback/CCallResult dispatch. CCallbackBase objects are built by the
 * game's MSVC compiler, so call their virtuals through the MSVC vtable layout:
 * overloads are laid out in reverse declaration order.
 *   [0] Run(void *param, bool io_failure, SteamAPICall_t call)
 *   [1] Run(void *param)
 *   [2] GetCallbackSizeBytes()
 */
struct msvc_callback_base
{
    void **vtable;
    uint8 flags;
    int callback_id;
};

typedef void (*RunCallResultFn)(void *self, void *param, bool io_failure, SteamAPICall_t call);
typedef void (*RunCallbackFn)(void *self, void *param);
typedef int (*GetCallbackSizeFn)(void *self);

enum { CALLBACK_FLAG_REGISTERED = 0x01, CALLBACK_FLAG_GAMESERVER = 0x02 };

/* Registered callbacks / pending call results: (key, object) pairs. */
struct callback_entry
{
    uint64 key;
    msvc_callback_base *cb;
};

struct callback_list
{
    callback_entry *items;
    size_t count;
};

static callback_list g_callbacks, g_call_results;

static void list_add(callback_list *list, uint64 key, msvc_callback_base *cb)
{
    callback_entry *grown = (callback_entry *)realloc(list->items, (list->count + 1) * sizeof(*grown));
    if (!grown) return;
    list->items = grown;
    list->items[list->count].key = key;
    list->items[list->count++].cb = cb;
}

/* Remove entries matching cb (any key if match_key is false); optionally collect them. */
static size_t list_take(callback_list *list, bool match_key, uint64 key, msvc_callback_base *cb,
                        msvc_callback_base ***taken)
{
    size_t kept = 0, n = 0;
    msvc_callback_base **out = taken ? (msvc_callback_base **)malloc((list->count + 1) * sizeof(*out)) : NULL;
    for (size_t i = 0; i < list->count; ++i)
    {
        callback_entry e = list->items[i];
        if ((!match_key || e.key == key) && (!cb || e.cb == cb))
        {
            if (out) out[n] = e.cb;
            ++n;
        }
        else
            list->items[kept++] = e;
    }
    list->count = kept;
    if (taken) *taken = out;
    return n;
}

S_API void S_CALLTYPE SteamAPI_RegisterCallback(CCallbackBase *pCallback, int iCallback)
{
    msvc_callback_base *cb = (msvc_callback_base *)pCallback;
    EnterCriticalSection(&g_cs);
    cb->flags |= CALLBACK_FLAG_REGISTERED;
    cb->callback_id = iCallback;
    list_add(&g_callbacks, (uint64)(int64)iCallback, cb);
    LeaveCriticalSection(&g_cs);
}

S_API void S_CALLTYPE SteamAPI_UnregisterCallback(CCallbackBase *pCallback)
{
    msvc_callback_base *cb = (msvc_callback_base *)pCallback;
    EnterCriticalSection(&g_cs);
    list_take(&g_callbacks, false, 0, cb, NULL);
    cb->flags &= ~CALLBACK_FLAG_REGISTERED;
    LeaveCriticalSection(&g_cs);
}

S_API void S_CALLTYPE SteamAPI_RegisterCallResult(CCallbackBase *pCallback, SteamAPICall_t hAPICall)
{
    EnterCriticalSection(&g_cs);
    list_add(&g_call_results, hAPICall, (msvc_callback_base *)pCallback);
    LeaveCriticalSection(&g_cs);
}

S_API void S_CALLTYPE SteamAPI_UnregisterCallResult(CCallbackBase *pCallback, SteamAPICall_t hAPICall)
{
    EnterCriticalSection(&g_cs);
    list_take(&g_call_results, true, hAPICall, (msvc_callback_base *)pCallback, NULL);
    LeaveCriticalSection(&g_cs);
}

static void dispatch_call_result(HSteamPipe pipe, const SteamAPICallCompleted_t *completed)
{
    msvc_callback_base **targets = NULL;
    EnterCriticalSection(&g_cs);
    size_t n = list_take(&g_call_results, true, completed->m_hAsyncCall, NULL, &targets);
    LeaveCriticalSection(&g_cs);

    for (size_t i = 0; targets && i < n; ++i)
    {
        msvc_callback_base *cb = targets[i];
        int size = ((GetCallbackSizeFn)cb->vtable[2])(cb);
        void *buf = calloc(1, size > 0 ? size : 1);
        bool failed = false;
        if (!buf || !SteamAPI_ManualDispatch_GetAPICallResult(pipe, completed->m_hAsyncCall, buf, size,
                                                             cb->callback_id, &failed))
            failed = true;
        ((RunCallResultFn)cb->vtable[0])(cb, buf, failed, completed->m_hAsyncCall);
        free(buf);
    }
    free(targets);
}

static void run_callbacks(HSteamPipe pipe, bool gameserver)
{
    if (!pipe || g_manual_dispatch) return;

    CallbackMsg_t msg;
    while (SteamAPI_ManualDispatch_GetNextCallback(pipe, &msg))
    {
        if (msg.m_iCallback == SteamAPICallCompleted_t::k_iCallback)
            dispatch_call_result(pipe, (const SteamAPICallCompleted_t *)msg.m_pubParam);
        else
        {
            size_t n = 0;
            EnterCriticalSection(&g_cs);
            msvc_callback_base **targets =
                (msvc_callback_base **)malloc((g_callbacks.count + 1) * sizeof(*targets));
            for (size_t i = 0; targets && i < g_callbacks.count; ++i)
            {
                callback_entry e = g_callbacks.items[i];
                if (e.key == (uint64)(int64)msg.m_iCallback && !(e.cb->flags & CALLBACK_FLAG_GAMESERVER) == !gameserver)
                    targets[n++] = e.cb;
            }
            LeaveCriticalSection(&g_cs);
            for (size_t i = 0; i < n; ++i) ((RunCallbackFn)targets[i]->vtable[1])(targets[i], msg.m_pubParam);
            free(targets);
        }
        SteamAPI_ManualDispatch_FreeLastCallback(pipe);
    }
}

S_API void S_CALLTYPE SteamAPI_RunCallbacks()
{
    SHIM_TRACE("SteamAPI_RunCallbacks");
    run_callbacks(g_pipe, false);
}

/* --- Game server: not supported by this shim --- */

S_API ESteamAPIInitResult S_CALLTYPE SteamInternal_GameServer_Init_V2(uint32 unIP, uint16 usGamePort,
                                                                      uint16 usQueryPort, EServerMode eServerMode,
                                                                      const char *pchVersionString,
                                                                      const char *pszInternalCheckInterfaceVersions,
                                                                      SteamErrMsg *pOutErrMsg)
{
    set_err(pOutErrMsg, "Game servers are not supported by the ARM64 steam_api shim");
    return k_ESteamAPIInitResult_FailedGeneric;
}

/* SDK 1.58 and older */
S_API bool S_CALLTYPE SteamInternal_GameServer_Init(uint32 unIP, uint16 usLegacySteamPort, uint16 usGamePort,
                                                    uint16 usQueryPort, EServerMode eServerMode,
                                                    const char *pchVersionString)
{
    return false;
}

extern "C" __declspec(dllexport) bool SteamGameServer_InitSafe(uint32 unIP, uint16 usSteamPort, uint16 usGamePort,
                                                              uint16 usQueryPort, EServerMode eServerMode,
                                                              const char *pchVersionString)
{
    return false;
}

S_API void S_CALLTYPE SteamGameServer_Shutdown()
{
}

S_API void S_CALLTYPE SteamGameServer_RunCallbacks()
{
}

S_API bool SteamGameServer_BSecure()
{
    return false;
}

S_API uint64 SteamGameServer_GetSteamID()
{
    return 0;
}

S_API HSteamPipe S_CALLTYPE SteamGameServer_GetHSteamPipe()
{
    return 0;
}

S_API HSteamUser S_CALLTYPE SteamGameServer_GetHSteamUser()
{
    return 0;
}

extern "C" __declspec(dllexport) uint32 SteamGameServer_GetIPCCallCount()
{
    return 0;
}

S_API void *S_CALLTYPE SteamInternal_FindOrCreateGameServerInterface(HSteamUser hSteamUser, const char *pszVersion)
{
    return NULL;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(instance);
        InitializeCriticalSection(&g_cs);
    }
    return TRUE;
}
