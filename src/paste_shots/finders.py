"""Pure screenshot-finder logic — no clipboard, no keystrokes, no GTK.

Kept separate so the test suite can exercise the marker-advance and listing
rules without a live display server. The functions here are the contract
the CLI's mode-dispatch (`since` / `last N`) relies on."""

import time
from pathlib import Path

from . import config

# 10 minutes — first-run window when no marker exists yet. Makes a fresh
# install pick up screenshots the user took just before installing.
_FIRST_RUN_LOOKBACK_S = 600


def screenshots_in(directory: Path) -> list[Path]:
    return [
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in config.EXTS
    ]


def find_since_marker() -> list[Path]:
    d = config.get_watch_dir()
    if not d.exists():
        return []
    files = screenshots_in(d)
    if config.MARKER_FILE.exists():
        cutoff = config.MARKER_FILE.stat().st_mtime
    else:
        cutoff = time.time() - _FIRST_RUN_LOOKBACK_S
    files = [f for f in files if f.stat().st_mtime > cutoff]
    return sorted(files, key=lambda f: f.stat().st_mtime)


def find_last_n(n: int) -> list[Path]:
    if n <= 0:
        return []
    d = config.get_watch_dir()
    if not d.exists():
        return []
    files = screenshots_in(d)
    return sorted(files, key=lambda f: f.stat().st_mtime)[-n:]
