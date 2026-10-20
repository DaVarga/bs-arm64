"""Everything outside the instance the commands work with, and its defaults."""
import os
from dataclasses import dataclass
from pathlib import Path

from . import pins, steam
from .pins import Pins
from .prefix import Prefix
from .proton import Proton

DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "bs-arm64"
DEFAULT_PREFIX = Path.home() / ".local/share/BSManager/SharedContent/compatdata"   # BSManager's
DEFAULT_PROTON = Path.home() / ".steam/steam/steamapps/common/Proton 11.0 (ARM64)"


@dataclass(frozen=True)
class Setup:
    pins: Pins
    artifacts: Path       # the built DLLs (the release dir, or out/ in a checkout)
    cache: Path           # downloads (Unity player, OpenXR plugin)
    prefix: Prefix
    proton: Proton
    steam_root: Path

    @classmethod
    def create(cls, artifacts: Path | None = None, cache: Path | None = None,
               prefix: Path | None = None, proton: Path | None = None) -> "Setup":
        return cls(pins=Pins.load(),
                   artifacts=artifacts or pins.default_artifacts(),
                   cache=cache or DEFAULT_CACHE,
                   prefix=Prefix(prefix or DEFAULT_PREFIX),
                   proton=Proton(proton or DEFAULT_PROTON),
                   steam_root=steam.DEFAULT_ROOT)
