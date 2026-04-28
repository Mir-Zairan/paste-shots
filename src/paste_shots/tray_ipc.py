"""IPC between the paste-shots CLI and the running tray.

The tray writes its PID into the singleton lock file after acquiring the
flock. The CLI reads that file and signals the tray directly via os.kill —
precise targeting that replaces the previous `pkill -f tray_app.py` pattern,
which matched any process whose argv mentioned `tray_app.py` (editors with
the file open, debuggers, grep pipelines, etc.).
"""

import os
import signal as _signal
from pathlib import Path


def lock_path() -> Path:
    runtime = os.environ.get('XDG_RUNTIME_DIR') or '/tmp'
    return Path(runtime) / 'paste-shots.lock'


def read_tray_pid() -> int | None:
    """Return the PID of the running tray, or None if no tray is running.

    Verifies the PID is still alive (stale lock files can linger after an
    abnormal exit on networked filesystems where the flock isn't released)
    via a no-op signal-zero kill probe."""
    p = lock_path()
    if not p.exists():
        return None
    try:
        text = p.read_text().strip()
        pid = int(text)
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return None
    return pid


def signal_tray(sig: int) -> bool:
    """Deliver a signal to the running tray. Returns True on delivery."""
    pid = read_tray_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


SIG_RELOAD = _signal.SIGUSR1   # full config reload + UI re-apply
SIG_REFRESH = _signal.SIGUSR2  # cheap badge refresh (marker advanced)
SIG_QUIT = _signal.SIGTERM     # graceful shutdown
