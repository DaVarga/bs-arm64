"""What we read from the Steam client's files: the reaper, Beat Saber's Foveated Rendering switch,
and the client version (for doctor)."""
import re
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".steam/steam"

# Steam account id (userdata/<id>) = SteamID64 - this
_STEAMID64_BASE = 76561197960265728


def reaper(root: Path) -> Path | None:
    """Steam's process-tree helper. Steam starts every game as `reaper SteamLaunch AppId=<id> -- ...`;
    from that it knows which app is running. Without it, Steam treats the game as a non-VR app:
    the Frame's non-VR frame limiter applies and the desktop window shows in the VR overlay."""
    for candidate in (root / "steamrtarm64/reaper", root / "ubuntu12_32/reaper"):
        if candidate.is_file():
            return candidate
    return None


def foveation_enabled(root: Path, app_id: str) -> bool:
    """The per-game "Foveated Rendering" switch (game properties → Performance), stored as
    apps/<id>/FDMEnable in the most recent user's localconfig.vdf; absent when off."""
    user = _most_recent_user(root)
    if user is None:
        return False
    config = read_vdf(root / "userdata" / user / "config/localconfig.vdf")
    app = _path(config, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", app_id)
    return isinstance(app, dict) and _get(app, "FDMEnable") == "1"


def client_version(root: Path) -> str:
    for manifest in sorted((root / "package").glob("steam_client_*.manifest")):
        match = re.search(r'"version"\s+"(\d+)"', manifest.read_text(errors="replace"))
        if match:
            return match.group(1)
    return "unknown"


def _most_recent_user(root: Path) -> str | None:
    """Account id of the user logged in most recently, from config/loginusers.vdf."""
    users = _path(read_vdf(root / "config/loginusers.vdf"), "users")
    if not isinstance(users, dict):
        return None
    ids = [i for i, u in users.items() if i.isdigit() and isinstance(u, dict)]
    recent = [i for i in ids if _get(users[i], "MostRecent") == "1"]
    best = recent[0] if recent else max(ids, key=lambda i: int(_get(users[i], "Timestamp") or 0), default=None)
    return str(int(best) - _STEAMID64_BASE) if best else None


# --- VDF (Valve's text key-value format) --------------------------------------------------------

_TOKEN = re.compile(r'\s*(?://[^\n]*|"((?:[^"\\]|\\.)*)"|([{}])|([^\s{}"]+))')


def parse_vdf(text: str) -> dict:
    """Nested dicts of strings. Keys keep their case; look them up with _get (Steam isn't
    consistent about case)."""
    root: dict = {}
    stack = [root]
    key = None
    for match in _TOKEN.finditer(text):
        quoted, brace, bare = match.groups()
        if brace == "{":
            child: dict = {}
            stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif quoted is not None or bare is not None:
            value = bare if quoted is None else re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m[1], m[1]), quoted)
            if key is None:
                key = value
            else:
                stack[-1][key] = value
                key = None
    return root


def read_vdf(path: Path) -> dict:
    try:
        return parse_vdf(path.read_text(errors="replace"))
    except OSError:
        return {}


def _get(node: dict, key: str):
    """Case-insensitive lookup."""
    if key in node:
        return node[key]
    lower = key.lower()
    return next((v for k, v in node.items() if k.lower() == lower), None)


def _path(node, *keys: str):
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = _get(node, key)
    return node
