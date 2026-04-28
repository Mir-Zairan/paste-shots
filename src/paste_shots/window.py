"""Window-class detection and DBus bridge to the GNOME Shell extension."""

import os
import subprocess
import sys
from pathlib import Path

import gi
from gi.repository import GLib

from . import config


# Mirror of TERMINAL_CLASSES in gnome-extension/*/extension.js.
_TERMINAL_CLASSES = (
    'gnome-terminal', 'gnome-terminal-server',
    'org.gnome.terminal', 'org.gnome.ptyxis', 'ptyxis',
    'alacritty', 'kitty', 'wezterm', 'foot',
    'terminator', 'tilix', 'xterm', 'urxvt', 'rxvt',
    'ghostty', 'konsole', 'warp', 'warp-terminal',
)


def is_terminal_class(cls: str) -> bool:
    cls = (cls or '').lower()
    return any(t in cls for t in _TERMINAL_CLASSES)


def _matches_custom(cls: str) -> bool:
    """Substring match against the user-defined custom_paste_targets list.

    Empty/whitespace patterns are skipped — without this, a stray empty
    string would `'' in <anything>` → True and silently disable the guard."""
    cls_lower = (cls or '').lower()
    if not cls_lower:
        return False
    custom = config.get('custom_paste_targets', []) or []
    for pattern in custom:
        if not isinstance(pattern, str):
            continue
        p = pattern.strip().lower()
        if p and p in cls_lower:
            return True
    return False


def is_paste_target(cls: str) -> bool:
    """True when cls is an acceptable paste target given the current paste_mode.

    See config.PasteMode for valid values.

    Gates paste so we don't fire Ctrl+V into apps that silently ignore
    image clipboard (gedit, browsers, file managers, desktop) and
    falsely report success."""
    mode = config.get('paste_mode', config.PasteMode.TERMINAL_ONLY)
    if mode == config.PasteMode.ANY:
        return True
    return is_terminal_class(cls) or _matches_custom(cls)


# ---- Session detection ---------------------------------------------------

def session_type() -> str:
    return os.environ.get('XDG_SESSION_TYPE', 'unknown').lower()


def is_gnome() -> bool:
    return 'GNOME' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper()


def is_wayland() -> bool:
    return session_type() == 'wayland'


# ---- GNOME Shell extension via DBus --------------------------------------

_EXT_BUS_NAME = 'org.gnome.Shell'
_EXT_OBJ_PATH = '/org/pasteshots/Shell'
_EXT_IFACE = 'org.pasteshots.Shell'

_session_bus = None


def _get_session_bus():
    global _session_bus
    if _session_bus is not None:
        return _session_bus
    from gi.repository import Gio
    _session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return _session_bus


def _dbus_call(method: str, params: GLib.Variant | None, reply_sig: str) -> tuple | None:
    try:
        from gi.repository import Gio
        bus = _get_session_bus()
        result = bus.call_sync(
            _EXT_BUS_NAME, _EXT_OBJ_PATH, _EXT_IFACE, method,
            params, GLib.VariantType.new(reply_sig),
            Gio.DBusCallFlags.NONE, 1500, None,
        )
        return result.unpack()
    except GLib.Error as e:
        # Extension not installed / not enabled is the common case (tray
        # works without it). Don't spam stderr for that — only surface
        # genuinely unexpected DBus errors. NameHasNoOwner / ServiceUnknown
        # are the "extension not present" signatures.
        msg = e.message or ''
        if 'NameHasNoOwner' not in msg and 'ServiceUnknown' not in msg:
            print(f'paste-shots: DBus {method} failed: {msg}', file=sys.stderr)
        return None


def extension_available() -> bool:
    return _dbus_call('Ping', None, '(b)') is not None


def push_badge(count: int) -> bool:
    r = _dbus_call('UpdateBadge', GLib.Variant('(u)', (max(0, int(count)),)), '(b)')
    return bool(r and r[0])


def show_floating_widget(show: bool) -> bool:
    r = _dbus_call('ShowFloatingWidget', GLib.Variant('(b)', (bool(show),)), '(b)')
    return bool(r and r[0])


def focused_class() -> str:
    """Return wm_class of the currently focused window (lowercased), or ''.

    Used to abort paste when there's no real text-accepting target — without
    this, ydotool fires Ctrl+V into the void and falsely reports success."""
    if is_wayland() and is_gnome():
        r = _dbus_call('FocusedClass', None, '(s)')
        if r is not None:
            return r[0]
    try:
        wid_r = subprocess.run(['xdotool', 'getactivewindow'],
                               capture_output=True, text=True, timeout=1)
        wid = wid_r.stdout.strip()
        if wid_r.returncode == 0 and wid:
            cls_r = subprocess.run(['xdotool', 'getwindowclassname', wid],
                                   capture_output=True, text=True, timeout=1)
            if cls_r.returncode == 0:
                return cls_r.stdout.strip().lower()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ''
