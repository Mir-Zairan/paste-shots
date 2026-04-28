"""Keystroke injection via ydotool (Wayland) or xdotool (X11).

Both tools accept the same `mod+mod+key` combo syntax, so callers can use
one string regardless of session type."""

import os
import shutil
import subprocess

from .errors import PasteError


def _ydotool_env() -> dict:
    """Discover ydotoold's socket so the tray works even when `.profile`
    hasn't been sourced (e.g. started from a graphical launcher)."""
    env = dict(os.environ)
    if env.get('YDOTOOL_SOCKET'):
        return env
    xdg = env.get('XDG_RUNTIME_DIR')
    if xdg:
        candidate = f'{xdg}/.ydotool_socket'
        if os.path.exists(candidate):
            env['YDOTOOL_SOCKET'] = candidate
    return env


def send_keys(combo: str) -> None:
    """Send a keyboard combo (e.g. 'ctrl+v', 'ctrl+alt+t'). Raises
    PasteError if no keystroke tool works."""
    errors = []
    for cmd in (['ydotool', 'key', combo],
                ['xdotool', 'key', '--clearmodifiers', combo]):
        if shutil.which(cmd[0]):
            env = _ydotool_env() if cmd[0] == 'ydotool' else None
            r = subprocess.run(cmd, capture_output=True, env=env)
            if r.returncode == 0:
                return
            err = (r.stderr or b'').decode(errors='replace').strip() or f'exit {r.returncode}'
            errors.append(f'{cmd[0]}: {err}')
    if errors:
        raise PasteError('keystroke failed — ' + '; '.join(errors))
    raise PasteError('no keystroke tool found (install ydotool or xdotool)')


def send_ctrl_v() -> None:
    """Send Ctrl+V. Kept as a named convenience for the common case."""
    send_keys('ctrl+v')
