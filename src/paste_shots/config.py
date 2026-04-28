"""paste-shots config: settings file, defaults, autostart, paths."""

import json
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path


class PasteMode(str, Enum):
    """Paste-target gating mode. (str, Enum) so members compare equal to
    their JSON-serialized string form, e.g. PasteMode.ANY == 'any'."""
    TERMINAL_ONLY = 'terminal_only'
    ANY = 'any'

CONFIG_FILE = Path.home() / '.config' / 'paste-shots' / 'settings.json'
DATA_DIR = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'paste-shots'
MARKER_FILE = DATA_DIR / 'last-paste'


def _ensure_data_dir() -> None:
    """Create DATA_DIR on first use rather than at import time.

    Import-time side effects bite tests (which reassign DATA_DIR after import,
    leaving the real path already created) and IDE/lint tooling that just
    wants to read the module."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

AUTOSTART_FILE = Path.home() / '.config' / 'autostart' / 'paste-shots.desktop'
SYSTEMD_USER_UNIT = Path.home() / '.config' / 'systemd' / 'user' / 'paste-shots-tray.service'
SYSTEMD_USER_WANTS = (
    Path.home() / '.config' / 'systemd' / 'user'
    / 'default.target.wants' / 'paste-shots-tray.service'
)
TRAY_EXEC = str(Path.home() / '.local/bin/paste-shots-tray')
CLI_EXEC = str(Path.home() / '.local/bin/paste-shots')

_DESKTOP_ENTRY = f"""\
[Desktop Entry]
Name=paste-shots
Comment=Paste screenshots into Claude Code
Exec={TRAY_EXEC}
Icon=camera-photo
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=false
"""

EXTS = {'.png', '.jpg', '.jpeg'}

DEFAULT_CONFIG: dict = {
    'watch_dir': str(Path.home() / 'Pictures/Screenshots'),
    'expanded_icons': False,
    'paste_delay': 0.6,
    'notifications': True,
    'autostart': True,
    'floating_widget': False,
    'tray_icon': True,
    # Substrings appended to the built-in terminal allowlist used
    # by window.is_paste_target(). Lowercased substring match against the
    # focused window's wm_class. Example: ["code", "discord"].
    'custom_paste_targets': [],
    # Controls which focused windows are accepted as paste targets.
    # See PasteMode enum above for valid values.
    'paste_mode': PasteMode.TERMINAL_ONLY.value,
    # Persisted [x, y] of the GTK floating-widget fallback. None until the
    # user drags it; the widget falls back to (80, 120) in that case.
    'floating_pos': None,
}

_config: dict = dict(DEFAULT_CONFIG)


def load_config() -> dict:
    global _config
    _ensure_data_dir()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except (json.JSONDecodeError, OSError) as e:
            # Surface the failure so users with a corrupt settings.json
            # don't get silent default-fallback they can't explain.
            print(f'paste-shots: failed to parse {CONFIG_FILE}: {e}; '
                  'using defaults', file=sys.stderr)
    if 'PASTE_SHOTS_WATCH_DIR' in os.environ:
        cfg['watch_dir'] = os.environ['PASTE_SHOTS_WATCH_DIR']
    _config = cfg
    return cfg


def save_config(cfg: dict) -> None:
    global _config
    _config = cfg
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: rename is the single visible state transition. A crash
    # mid-write leaves the prior settings.json intact.
    tmp = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + '.tmp')
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, CONFIG_FILE)


def get_config() -> dict:
    return _config


def get(key, default=None):
    return _config.get(key, DEFAULT_CONFIG.get(key, default))


def get_watch_dir() -> Path:
    return Path(_config.get('watch_dir', DEFAULT_CONFIG['watch_dir']))


def _purge_systemd_user_unit():
    """Disable and remove a stray systemd user unit shadowing the XDG autostart.

    The tool ships only the XDG `.desktop` entry; if a systemd unit was
    installed by hand (or by an older install.sh), it would race the desktop
    entry at login and produce duplicate tray instances. Owning autostart
    from one place is the only way to keep instance count == 1.
    """
    if not (SYSTEMD_USER_UNIT.exists() or SYSTEMD_USER_WANTS.exists()):
        return
    try:
        subprocess.run(
            ['systemctl', '--user', 'disable', '--now', 'paste-shots-tray.service'],
            capture_output=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    SYSTEMD_USER_UNIT.unlink(missing_ok=True)
    SYSTEMD_USER_WANTS.unlink(missing_ok=True)
    try:
        subprocess.run(
            ['systemctl', '--user', 'daemon-reload'],
            capture_output=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def set_autostart(enabled: bool) -> None:
    _purge_systemd_user_unit()
    if enabled:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(_DESKTOP_ENTRY)
    else:
        AUTOSTART_FILE.unlink(missing_ok=True)
