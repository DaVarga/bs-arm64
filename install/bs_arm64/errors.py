"""Failures the user can act on. The code is for programs (BSManager), the message for people."""
from enum import Enum


class Code(str, Enum):
    NOT_AN_INSTANCE = "NOT_AN_INSTANCE"          # no Beat Saber_Data/globalgamemanagers
    NOT_INSTALLED = "NOT_INSTALLED"              # launch/uninstall on an unpatched instance
    UNSUPPORTED_ENGINE = "UNSUPPORTED_ENGINE"    # game built with another Unity version
    PROTON_NOT_ARM64 = "PROTON_NOT_ARM64"
    PROTON_UNTESTED = "PROTON_UNTESTED"          # not in versions.env PROTON_TAGS
    PROTON_CHANGED = "PROTON_CHANGED"            # prefix runtime set up for another Proton build
    ARTIFACT_MISSING = "ARTIFACT_MISSING"        # release incomplete / build.sh not run
    PREFIX_BUSY = "PREFIX_BUSY"                  # Windows programs still running in the prefix
    PREFIX_FAILED = "PREFIX_FAILED"              # creating or setting up the prefix failed
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"


class Error(Exception):
    def __init__(self, code: Code, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
