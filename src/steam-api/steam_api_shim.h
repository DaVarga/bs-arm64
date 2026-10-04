#pragma once
#define STEAM_API_EXPORTS
#include "steam/steam_api_flat.h"
#include "steam/steam_gameserver.h"

#define VTBL(obj) (*(void ***)(obj))

/* Older-SDK support (steam_api_core.cpp, flat_generated.cpp) */
const char *shim_map_interface_version(const char *version);
void *shim_legacy_user_interface(const char *version);
void *shim_raw_generic_interface(ISteamClient *self, HSteamUser hSteamUser, HSteamPipe hSteamPipe, const char *pchVersion);

/* Debug builds (-DSHIM_TRACE_CALLS) log every flat call. */
#ifdef SHIM_TRACE_CALLS
void shim_trace(const char *name);
#define SHIM_TRACE(name) shim_trace(name)
#else
#define SHIM_TRACE(name) ((void)0)
#endif
