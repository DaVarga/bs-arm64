"""versions.env (the pinned versions, shared with build.sh) and where the release files are.

Release tarball:  bs-arm64.sh, bs_arm64/, versions.env, VERSION and the DLLs side by side.
Repo checkout:    install/bs_arm64/, versions.env at the top, DLLs in out/ (build.sh output).
"""
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
_RELEASE_DIR = PACKAGE_DIR.parent        # release: the tarball's top dir; repo: install/
_REPO_DIR = PACKAGE_DIR.parent.parent

# Version of the status/--json interface; raise it when a change breaks BSManager's parsing.
API_VERSION = 1

BS_APP_ID = "620980"


def is_release() -> bool:
    return (_RELEASE_DIR / "steam_api64.dll").is_file()


def default_artifacts() -> Path:
    return _RELEASE_DIR if is_release() else _REPO_DIR / "out"


def version() -> str:
    """Release version, e.g. "v0.4.0" (build.sh package writes VERSION); "dev" in a checkout."""
    try:
        return (_RELEASE_DIR / "VERSION").read_text().strip()
    except OSError:
        return "dev"


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines of a shell variable file; comments and blank lines skipped, quotes removed."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


@dataclass(frozen=True)
class Engine:
    """A Unity engine the release supports, and what install downloads for it."""
    version: str          # as in the instance's globalgamemanagers, e.g. "6000.0.40f1"
    changeset: str        # part of the Unity player's download URL
    openxr_version: str   # com.unity.xr.openxr version whose ARM64 (UWP) plugin is used


@dataclass(frozen=True)
class Pins:
    engines: tuple[Engine, ...]
    proton_tags: tuple[str, ...]   # Proton versions this release was tested with
    monomod_core_version: str
    monomod_core_match: str        # regex for the BSIPA MonoMod.Core builds we replace

    @classmethod
    def load(cls) -> "Pins":
        path = _RELEASE_DIR / "versions.env"
        if not path.is_file():
            path = _REPO_DIR / "versions.env"
        env = read_env_file(path)
        return cls(
            engines=tuple(_engine(env, version) for version in env["UNITY_VERSIONS"].split()),
            proton_tags=tuple((env.get("PROTON_TAGS") or env["PROTON_TAG"]).split()),
            monomod_core_version=env["MONOMOD_CORE_VERSION"],
            monomod_core_match=env["MONOMOD_CORE_MATCH"],
        )

    def engine(self, version: str | None) -> Engine | None:
        """The pins for an instance's Unity engine; None if the release doesn't support it."""
        return next((engine for engine in self.engines if engine.version == version), None)

    def engine_versions(self) -> str:
        return ", ".join(engine.version for engine in self.engines)


def _engine(env: dict[str, str], version: str) -> Engine:
    key = "UNITY_" + version.replace(".", "_")
    return Engine(version, env[f"{key}_CHANGESET"], env[f"{key}_OPENXR_VERSION"])
