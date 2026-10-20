"""Messages for people (text) or programs (--json, one JSON object per line on stdout).

Text mode is what bs-arm64.sh always printed: "==> step" on stdout, "warning: ..." and
"error: ..." on stderr. BSManager versions before the --json interface rely on that.
"""
import json
import sys

from .errors import Error


class Output:
    def __init__(self) -> None:
        self.json = False
        self._percent = -1

    def _emit(self, kind: str, **fields) -> None:
        print(json.dumps({"type": kind, **fields}), flush=True)

    def log(self, message: str) -> None:
        if self.json:
            self._emit("log", message=message)
        else:
            print(f"==> {message}", flush=True)

    def warn(self, message: str) -> None:
        if self.json:
            self._emit("warning", message=message)
        else:
            print(f"warning: {message}", file=sys.stderr, flush=True)

    def progress(self, done: int, total: int) -> None:
        """Download progress; only --json shows it, at most once per percent."""
        percent = done * 100 // total if total else 0
        if self.json and percent != self._percent:
            self._percent = percent
            self._emit("progress", percent=percent)

    def result(self, data: dict) -> None:
        """The answer of status/doctor --json."""
        self._emit("result", **data)

    def error(self, error: Error) -> None:
        if self.json:
            self._emit("error", code=error.code.value, message=error.message)
        else:
            print(f"error: {error.message}", file=sys.stderr, flush=True)


out = Output()
