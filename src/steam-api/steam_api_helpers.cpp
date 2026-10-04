/*
 * ARM64 steam_api64.dll replacement: flat helpers that are implemented inside
 * steam_api itself rather than by an interface vtable method.
 *
 * Only non-virtual SDK code may be used here: this file is built with the
 * Itanium C++ ABI, so interface calls must go through the flat wrappers.
 */
#include "steam_api_shim.h"

#include <string.h>
#include <new>

#include "sdk_inline_impl.inc"

static ISteamNetworkingUtils *networking_utils(void)
{
    return SteamAPI_SteamNetworkingUtils_SteamAPI_v004();
}

/* --- Interface accessors --- */

#define USER_ACCESSOR(type, name, version) \
    S_API type *name() { return (type *)SteamInternal_FindOrCreateUserInterface(SteamAPI_GetHSteamUser(), version); }
#define GAMESERVER_ACCESSOR(type, name, version) \
    S_API type *name() { return (type *)SteamInternal_FindOrCreateGameServerInterface(SteamGameServer_GetHSteamUser(), version); }

USER_ACCESSOR(ISteamUser, SteamAPI_SteamUser_v023, STEAMUSER_INTERFACE_VERSION)
USER_ACCESSOR(ISteamFriends, SteamAPI_SteamFriends_v017, STEAMFRIENDS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamUtils, SteamAPI_SteamUtils_v010, STEAMUTILS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamMatchmaking, SteamAPI_SteamMatchmaking_v009, STEAMMATCHMAKING_INTERFACE_VERSION)
USER_ACCESSOR(ISteamMatchmakingServers, SteamAPI_SteamMatchmakingServers_v002, STEAMMATCHMAKINGSERVERS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamGameSearch, SteamAPI_SteamGameSearch_v001, STEAMGAMESEARCH_INTERFACE_VERSION)
USER_ACCESSOR(ISteamParties, SteamAPI_SteamParties_v002, STEAMPARTIES_INTERFACE_VERSION)
USER_ACCESSOR(ISteamRemoteStorage, SteamAPI_SteamRemoteStorage_v016, STEAMREMOTESTORAGE_INTERFACE_VERSION)
USER_ACCESSOR(ISteamUserStats, SteamAPI_SteamUserStats_v013, STEAMUSERSTATS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamApps, SteamAPI_SteamApps_v008, STEAMAPPS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamNetworking, SteamAPI_SteamNetworking_v006, STEAMNETWORKING_INTERFACE_VERSION)
USER_ACCESSOR(ISteamScreenshots, SteamAPI_SteamScreenshots_v003, STEAMSCREENSHOTS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamMusic, SteamAPI_SteamMusic_v001, STEAMMUSIC_INTERFACE_VERSION)
USER_ACCESSOR(ISteamMusicRemote, SteamAPI_SteamMusicRemote_v001, STEAMMUSICREMOTE_INTERFACE_VERSION)
USER_ACCESSOR(ISteamHTTP, SteamAPI_SteamHTTP_v003, STEAMHTTP_INTERFACE_VERSION)
USER_ACCESSOR(ISteamInput, SteamAPI_SteamInput_v006, STEAMINPUT_INTERFACE_VERSION)
USER_ACCESSOR(ISteamController, SteamAPI_SteamController_v008, STEAMCONTROLLER_INTERFACE_VERSION)
USER_ACCESSOR(ISteamUGC, SteamAPI_SteamUGC_v020, STEAMUGC_INTERFACE_VERSION)
USER_ACCESSOR(ISteamHTMLSurface, SteamAPI_SteamHTMLSurface_v005, STEAMHTMLSURFACE_INTERFACE_VERSION)
USER_ACCESSOR(ISteamInventory, SteamAPI_SteamInventory_v003, STEAMINVENTORY_INTERFACE_VERSION)
USER_ACCESSOR(ISteamTimeline, SteamAPI_SteamTimeline_v004, STEAMTIMELINE_INTERFACE_VERSION)
USER_ACCESSOR(ISteamVideo, SteamAPI_SteamVideo_v007, STEAMVIDEO_INTERFACE_VERSION)
USER_ACCESSOR(ISteamParentalSettings, SteamAPI_SteamParentalSettings_v001, STEAMPARENTALSETTINGS_INTERFACE_VERSION)
USER_ACCESSOR(ISteamRemotePlay, SteamAPI_SteamRemotePlay_v002, STEAMREMOTEPLAY_INTERFACE_VERSION)
USER_ACCESSOR(ISteamNetworkingMessages, SteamAPI_SteamNetworkingMessages_SteamAPI_v002, STEAMNETWORKINGMESSAGES_INTERFACE_VERSION)
USER_ACCESSOR(ISteamNetworkingSockets, SteamAPI_SteamNetworkingSockets_SteamAPI_v012, STEAMNETWORKINGSOCKETS_INTERFACE_VERSION)
/* The real steam_api creates this one through SteamInternal_CreateInterface. */
S_API ISteamNetworkingUtils *SteamAPI_SteamNetworkingUtils_SteamAPI_v004()
{
    return (ISteamNetworkingUtils *)SteamInternal_CreateInterface(STEAMNETWORKINGUTILS_INTERFACE_VERSION);
}

GAMESERVER_ACCESSOR(ISteamUtils, SteamAPI_SteamGameServerUtils_v010, STEAMUTILS_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamNetworking, SteamAPI_SteamGameServerNetworking_v006, STEAMNETWORKING_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamHTTP, SteamAPI_SteamGameServerHTTP_v003, STEAMHTTP_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamUGC, SteamAPI_SteamGameServerUGC_v020, STEAMUGC_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamInventory, SteamAPI_SteamGameServerInventory_v003, STEAMINVENTORY_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamNetworkingMessages, SteamAPI_SteamGameServerNetworkingMessages_SteamAPI_v002, STEAMNETWORKINGMESSAGES_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamNetworkingSockets, SteamAPI_SteamGameServerNetworkingSockets_SteamAPI_v012, STEAMNETWORKINGSOCKETS_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamGameServer, SteamAPI_SteamGameServer_v015, STEAMGAMESERVER_INTERFACE_VERSION)
GAMESERVER_ACCESSOR(ISteamGameServerStats, SteamAPI_SteamGameServerStats_v001, STEAMGAMESERVERSTATS_INTERFACE_VERSION)

/* --- ISteamNetworkingUtils inline helpers --- */

S_API void SteamAPI_ISteamNetworkingUtils_InitRelayNetworkAccess(ISteamNetworkingUtils *self)
{
    SteamAPI_ISteamNetworkingUtils_CheckPingDataUpToDate(self, 1e10f);
}

S_API bool SteamAPI_ISteamNetworkingUtils_IsFakeIPv4(ISteamNetworkingUtils *self, uint32 nIPv4)
{
    return SteamAPI_ISteamNetworkingUtils_GetIPv4FakeIPType(self, nIPv4) > k_ESteamNetworkingFakeIPType_NotFake;
}

static bool set_config(ISteamNetworkingUtils *self, ESteamNetworkingConfigValue value, ESteamNetworkingConfigScope scope,
                       intptr_t obj, ESteamNetworkingConfigDataType type, const void *arg)
{
    return SteamAPI_ISteamNetworkingUtils_SetConfigValue(self, value, scope, obj, type, arg);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32(ISteamNetworkingUtils *self,
                                                                    ESteamNetworkingConfigValue eValue, int32 val)
{
    return set_config(self, eValue, k_ESteamNetworkingConfig_Global, 0, k_ESteamNetworkingConfig_Int32, &val);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueFloat(ISteamNetworkingUtils *self,
                                                                    ESteamNetworkingConfigValue eValue, float val)
{
    return set_config(self, eValue, k_ESteamNetworkingConfig_Global, 0, k_ESteamNetworkingConfig_Float, &val);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueString(ISteamNetworkingUtils *self,
                                                                     ESteamNetworkingConfigValue eValue,
                                                                     const char *val)
{
    return set_config(self, eValue, k_ESteamNetworkingConfig_Global, 0, k_ESteamNetworkingConfig_String, val);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValuePtr(ISteamNetworkingUtils *self,
                                                                  ESteamNetworkingConfigValue eValue, void *val)
{
    /* Pointer values are passed as a pointer to the pointer. */
    return set_config(self, eValue, k_ESteamNetworkingConfig_Global, 0, k_ESteamNetworkingConfig_Ptr, &val);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetConnectionConfigValueInt32(ISteamNetworkingUtils *self,
                                                                        HSteamNetConnection hConn,
                                                                        ESteamNetworkingConfigValue eValue, int32 val)
{
    return set_config(self, eValue, k_ESteamNetworkingConfig_Connection, hConn, k_ESteamNetworkingConfig_Int32, &val);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetConnectionConfigValueFloat(ISteamNetworkingUtils *self,
                                                                        HSteamNetConnection hConn,
                                                                        ESteamNetworkingConfigValue eValue, float val)
{
    return set_config(self, eValue, k_ESteamNetworkingConfig_Connection, hConn, k_ESteamNetworkingConfig_Float, &val);
}

S_API bool SteamAPI_ISteamNetworkingUtils_SetConnectionConfigValueString(ISteamNetworkingUtils *self,
                                                                         HSteamNetConnection hConn,
                                                                         ESteamNetworkingConfigValue eValue,
                                                                         const char *val)
{
    return set_config(self, eValue, k_ESteamNetworkingConfig_Connection, hConn, k_ESteamNetworkingConfig_String, val);
}

#define GLOBAL_CALLBACK(name, fn_type, config)                                                                  \
    S_API bool SteamAPI_ISteamNetworkingUtils_SetGlobalCallback_##name(ISteamNetworkingUtils *self, fn_type fn) \
    {                                                                                                           \
        return SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValuePtr(self, config, (void *)fn);                \
    }

GLOBAL_CALLBACK(SteamNetConnectionStatusChanged, FnSteamNetConnectionStatusChanged,
                k_ESteamNetworkingConfig_Callback_ConnectionStatusChanged)
GLOBAL_CALLBACK(SteamNetAuthenticationStatusChanged, FnSteamNetAuthenticationStatusChanged,
                k_ESteamNetworkingConfig_Callback_AuthStatusChanged)
GLOBAL_CALLBACK(SteamRelayNetworkStatusChanged, FnSteamRelayNetworkStatusChanged,
                k_ESteamNetworkingConfig_Callback_RelayNetworkStatusChanged)
GLOBAL_CALLBACK(FakeIPResult, FnSteamNetworkingFakeIPResult, k_ESteamNetworkingConfig_Callback_FakeIPResult)
GLOBAL_CALLBACK(MessagesSessionRequest, FnSteamNetworkingMessagesSessionRequest,
                k_ESteamNetworkingConfig_Callback_MessagesSessionRequest)
GLOBAL_CALLBACK(MessagesSessionFailed, FnSteamNetworkingMessagesSessionFailed,
                k_ESteamNetworkingConfig_Callback_MessagesSessionFailed)

S_API bool SteamAPI_ISteamNetworkingUtils_SetConfigValueStruct(ISteamNetworkingUtils *self,
                                                               const SteamNetworkingConfigValue_t &opt,
                                                               ESteamNetworkingConfigScope eScopeType,
                                                               intptr_t scopeObj)
{
    const void *val = opt.m_eDataType == k_ESteamNetworkingConfig_String ? (const void *)opt.m_val.m_string
                                                                           : (const void *)&opt.m_val;
    return set_config(self, opt.m_eValue, eScopeType, scopeObj, opt.m_eDataType, val);
}

/* --- SteamNetworkingIPAddr --- */

S_API void SteamAPI_SteamNetworkingIPAddr_Clear(SteamNetworkingIPAddr *self) { self->Clear(); }
S_API bool SteamAPI_SteamNetworkingIPAddr_IsIPv6AllZeros(SteamNetworkingIPAddr *self) { return self->IsIPv6AllZeros(); }
S_API void SteamAPI_SteamNetworkingIPAddr_SetIPv6(SteamNetworkingIPAddr *self, const uint8 *ipv6, uint16 nPort) { self->SetIPv6(ipv6, nPort); }
S_API void SteamAPI_SteamNetworkingIPAddr_SetIPv4(SteamNetworkingIPAddr *self, uint32 nIP, uint16 nPort) { self->SetIPv4(nIP, nPort); }
S_API bool SteamAPI_SteamNetworkingIPAddr_IsIPv4(SteamNetworkingIPAddr *self) { return self->IsIPv4(); }
S_API uint32 SteamAPI_SteamNetworkingIPAddr_GetIPv4(SteamNetworkingIPAddr *self) { return self->GetIPv4(); }
S_API void SteamAPI_SteamNetworkingIPAddr_SetIPv6LocalHost(SteamNetworkingIPAddr *self, uint16 nPort) { self->SetIPv6LocalHost(nPort); }
S_API bool SteamAPI_SteamNetworkingIPAddr_IsLocalHost(SteamNetworkingIPAddr *self) { return self->IsLocalHost(); }
S_API bool SteamAPI_SteamNetworkingIPAddr_IsEqualTo(SteamNetworkingIPAddr *self, const SteamNetworkingIPAddr &x) { return *self == x; }

S_API void SteamAPI_SteamNetworkingIPAddr_ToString(SteamNetworkingIPAddr *self, char *buf, uint32 cbBuf, bool bWithPort)
{
    SteamAPI_ISteamNetworkingUtils_SteamNetworkingIPAddr_ToString(networking_utils(), *self, buf, cbBuf, bWithPort);
}

S_API bool SteamAPI_SteamNetworkingIPAddr_ParseString(SteamNetworkingIPAddr *self, const char *pszStr)
{
    return SteamAPI_ISteamNetworkingUtils_SteamNetworkingIPAddr_ParseString(networking_utils(), self, pszStr);
}

S_API ESteamNetworkingFakeIPType SteamAPI_SteamNetworkingIPAddr_GetFakeIPType(SteamNetworkingIPAddr *self)
{
    return SteamAPI_ISteamNetworkingUtils_SteamNetworkingIPAddr_GetFakeIPType(networking_utils(), *self);
}

S_API bool SteamAPI_SteamNetworkingIPAddr_IsFakeIP(SteamNetworkingIPAddr *self)
{
    return SteamAPI_SteamNetworkingIPAddr_GetFakeIPType(self) > k_ESteamNetworkingFakeIPType_NotFake;
}

/* --- SteamNetworkingIdentity --- */

S_API void SteamAPI_SteamNetworkingIdentity_Clear(SteamNetworkingIdentity *self) { self->Clear(); }
S_API bool SteamAPI_SteamNetworkingIdentity_IsInvalid(SteamNetworkingIdentity *self) { return self->IsInvalid(); }
S_API void SteamAPI_SteamNetworkingIdentity_SetSteamID(SteamNetworkingIdentity *self, uint64_steamid steamID) { self->SetSteamID64(steamID); }
S_API uint64_steamid SteamAPI_SteamNetworkingIdentity_GetSteamID(SteamNetworkingIdentity *self) { return self->GetSteamID64(); }
S_API void SteamAPI_SteamNetworkingIdentity_SetSteamID64(SteamNetworkingIdentity *self, uint64 steamID) { self->SetSteamID64(steamID); }
S_API uint64 SteamAPI_SteamNetworkingIdentity_GetSteamID64(SteamNetworkingIdentity *self) { return self->GetSteamID64(); }
S_API bool SteamAPI_SteamNetworkingIdentity_SetXboxPairwiseID(SteamNetworkingIdentity *self, const char *pszString) { return self->SetXboxPairwiseID(pszString); }
S_API const char *SteamAPI_SteamNetworkingIdentity_GetXboxPairwiseID(SteamNetworkingIdentity *self) { return self->GetXboxPairwiseID(); }
/* Dropped after SDK 1.58 (k_ESteamNetworkingIdentityType_GoogleStadia = 19, a 64-bit ID). */
static const ESteamNetworkingIdentityType IDENTITY_GOOGLE_STADIA = (ESteamNetworkingIdentityType)19;
S_API void SteamAPI_SteamNetworkingIdentity_SetStadiaID(SteamNetworkingIdentity *self, uint64 id)
{
    self->m_eType = IDENTITY_GOOGLE_STADIA;
    self->m_cbSize = sizeof(self->data.m_steamID64);
    self->data.m_steamID64 = id;
}
S_API uint64 SteamAPI_SteamNetworkingIdentity_GetStadiaID(SteamNetworkingIdentity *self)
{
    return self->m_eType == IDENTITY_GOOGLE_STADIA ? self->data.m_steamID64 : 0;
}
S_API void SteamAPI_SteamNetworkingIdentity_SetPSNID(SteamNetworkingIdentity *self, uint64 id) { self->SetPSNID(id); }
S_API uint64 SteamAPI_SteamNetworkingIdentity_GetPSNID(SteamNetworkingIdentity *self) { return self->GetPSNID(); }
S_API void SteamAPI_SteamNetworkingIdentity_SetIPAddr(SteamNetworkingIdentity *self, const SteamNetworkingIPAddr &addr) { self->SetIPAddr(addr); }
S_API const SteamNetworkingIPAddr *SteamAPI_SteamNetworkingIdentity_GetIPAddr(SteamNetworkingIdentity *self) { return self->GetIPAddr(); }
S_API void SteamAPI_SteamNetworkingIdentity_SetIPv4Addr(SteamNetworkingIdentity *self, uint32 nIPv4, uint16 nPort) { self->SetIPv4Addr(nIPv4, nPort); }
S_API uint32 SteamAPI_SteamNetworkingIdentity_GetIPv4(SteamNetworkingIdentity *self) { return self->GetIPv4(); }
S_API void SteamAPI_SteamNetworkingIdentity_SetLocalHost(SteamNetworkingIdentity *self) { self->SetLocalHost(); }
S_API bool SteamAPI_SteamNetworkingIdentity_IsLocalHost(SteamNetworkingIdentity *self) { return self->IsLocalHost(); }
S_API bool SteamAPI_SteamNetworkingIdentity_SetGenericString(SteamNetworkingIdentity *self, const char *pszString) { return self->SetGenericString(pszString); }
S_API const char *SteamAPI_SteamNetworkingIdentity_GetGenericString(SteamNetworkingIdentity *self) { return self->GetGenericString(); }
S_API bool SteamAPI_SteamNetworkingIdentity_SetGenericBytes(SteamNetworkingIdentity *self, const void *data, uint32 cbLen) { return self->SetGenericBytes(data, cbLen); }
S_API const uint8 *SteamAPI_SteamNetworkingIdentity_GetGenericBytes(SteamNetworkingIdentity *self, int &cbLen) { return self->GetGenericBytes(cbLen); }
S_API bool SteamAPI_SteamNetworkingIdentity_IsEqualTo(SteamNetworkingIdentity *self, const SteamNetworkingIdentity &x) { return *self == x; }

S_API ESteamNetworkingFakeIPType SteamAPI_SteamNetworkingIdentity_GetFakeIPType(SteamNetworkingIdentity *self)
{
    const SteamNetworkingIPAddr *addr = self->GetIPAddr();
    return addr ? SteamAPI_SteamNetworkingIPAddr_GetFakeIPType((SteamNetworkingIPAddr *)addr)
                : k_ESteamNetworkingFakeIPType_Invalid;
}

S_API bool SteamAPI_SteamNetworkingIdentity_IsFakeIP(SteamNetworkingIdentity *self)
{
    return SteamAPI_SteamNetworkingIdentity_GetFakeIPType(self) > k_ESteamNetworkingFakeIPType_NotFake;
}

S_API void SteamAPI_SteamNetworkingIdentity_ToString(SteamNetworkingIdentity *self, char *buf, uint32 cbBuf)
{
    SteamAPI_ISteamNetworkingUtils_SteamNetworkingIdentity_ToString(networking_utils(), *self, buf, cbBuf);
}

S_API bool SteamAPI_SteamNetworkingIdentity_ParseString(SteamNetworkingIdentity *self, const char *pszStr)
{
    return SteamAPI_ISteamNetworkingUtils_SteamNetworkingIdentity_ParseString(networking_utils(), self, pszStr);
}

/* --- SteamNetworkingMessage_t / SteamNetworkingConfigValue_t --- */

S_API void SteamAPI_SteamNetworkingMessage_t_Release(SteamNetworkingMessage_t *self) { (*self->m_pfnRelease)(self); }

S_API void SteamAPI_SteamNetworkingConfigValue_t_SetInt32(SteamNetworkingConfigValue_t *self, ESteamNetworkingConfigValue eVal, int32_t data) { self->SetInt32(eVal, data); }
S_API void SteamAPI_SteamNetworkingConfigValue_t_SetInt64(SteamNetworkingConfigValue_t *self, ESteamNetworkingConfigValue eVal, int64_t data) { self->SetInt64(eVal, data); }
S_API void SteamAPI_SteamNetworkingConfigValue_t_SetFloat(SteamNetworkingConfigValue_t *self, ESteamNetworkingConfigValue eVal, float data) { self->SetFloat(eVal, data); }
S_API void SteamAPI_SteamNetworkingConfigValue_t_SetPtr(SteamNetworkingConfigValue_t *self, ESteamNetworkingConfigValue eVal, void *data) { self->SetPtr(eVal, data); }
S_API void SteamAPI_SteamNetworkingConfigValue_t_SetString(SteamNetworkingConfigValue_t *self, ESteamNetworkingConfigValue eVal, const char *data) { self->SetString(eVal, data); }

/* --- SteamDatagramHostedAddress (opaque, dedicated servers only) --- */

struct SteamDatagramHostedAddress
{
    int m_cbSize;
    char m_data[128];
};

S_API void SteamAPI_SteamDatagramHostedAddress_Clear(SteamDatagramHostedAddress *self) { memset(self, 0, sizeof(*self)); }
S_API SteamNetworkingPOPID SteamAPI_SteamDatagramHostedAddress_GetPopID(SteamDatagramHostedAddress *self) { return 0; }
S_API void SteamAPI_SteamDatagramHostedAddress_SetDevAddress(SteamDatagramHostedAddress *self, uint32 nIP, uint16 nPort, SteamNetworkingPOPID popid) {}

/* --- Matchmaking data types --- */

S_API bool SteamAPI_SteamIPAddress_t_IsSet(SteamIPAddress_t *self) { return self->IsSet(); }
S_API void SteamAPI_MatchMakingKeyValuePair_t_Construct(MatchMakingKeyValuePair_t *self) { new (self) MatchMakingKeyValuePair_t(); }
S_API void SteamAPI_servernetadr_t_Construct(servernetadr_t *self) { new (self) servernetadr_t(); }
S_API void SteamAPI_servernetadr_t_Init(servernetadr_t *self, unsigned int ip, uint16 usQueryPort, uint16 usConnectionPort) { self->Init(ip, usQueryPort, usConnectionPort); }
S_API uint16 SteamAPI_servernetadr_t_GetQueryPort(servernetadr_t *self) { return self->GetQueryPort(); }
S_API void SteamAPI_servernetadr_t_SetQueryPort(servernetadr_t *self, uint16 usPort) { self->SetQueryPort(usPort); }
S_API uint16 SteamAPI_servernetadr_t_GetConnectionPort(servernetadr_t *self) { return self->GetConnectionPort(); }
S_API void SteamAPI_servernetadr_t_SetConnectionPort(servernetadr_t *self, uint16 usPort) { self->SetConnectionPort(usPort); }
S_API uint32 SteamAPI_servernetadr_t_GetIP(servernetadr_t *self) { return self->GetIP(); }
S_API void SteamAPI_servernetadr_t_SetIP(servernetadr_t *self, uint32 unIP) { self->SetIP(unIP); }
S_API const char *SteamAPI_servernetadr_t_GetConnectionAddressString(servernetadr_t *self) { return self->GetConnectionAddressString(); }
S_API const char *SteamAPI_servernetadr_t_GetQueryAddressString(servernetadr_t *self) { return self->GetQueryAddressString(); }
S_API bool SteamAPI_servernetadr_t_IsLessThan(servernetadr_t *self, const servernetadr_t &netadr) { return *self < netadr; }
S_API void SteamAPI_servernetadr_t_Assign(servernetadr_t *self, const servernetadr_t &that) { *self = that; }
S_API void SteamAPI_gameserveritem_t_Construct(gameserveritem_t *self) { new (self) gameserveritem_t(); }
S_API const char *SteamAPI_gameserveritem_t_GetName(gameserveritem_t *self) { return self->GetName(); }
S_API void SteamAPI_gameserveritem_t_SetName(gameserveritem_t *self, const char *pName) { self->SetName(pName); }
