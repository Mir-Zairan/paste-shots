"""GNOME custom keybindings via gsettings."""

import ast
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from . import config

_GS_TOP_SCHEMA = 'org.gnome.settings-daemon.plugins.media-keys'
_GS_BINDING_SCHEMA = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
_GS_BINDING_BASE = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/'

SHORTCUT_ACTIONS = [
    ('paste-shots-paste',   'Paste new screenshots',    f'{config.CLI_EXEC}'),
    ('paste-shots-lastn',   'Paste last 3 screenshots', f'{config.CLI_EXEC} 3'),
    ('paste-shots-pick',    'Pick screenshots',          f'{config.CLI_EXEC} --pick'),
]


def _gs_get_list() -> list:
    r = subprocess.run(
        ['gsettings', 'get', _GS_TOP_SCHEMA, 'custom-keybindings'],
        capture_output=True, text=True,
    )
    text = r.stdout.strip()
    if not text or text in ('@as []', '[]'):
        return []
    try:
        return list(ast.literal_eval(text))
    except Exception:
        return []


def _gs_set_list(paths: list):
    # GVariant.print_ produces the exact gsettings array syntax with
    # correct escaping. Hand-rolled "'a','b'" formatting breaks if any path
    # contains a quote or backslash (rare, but possible if the user's
    # existing custom-keybindings list — which we round-trip through here —
    # was created by another tool that allowed weird names).
    val = GLib.Variant('as', list(paths)).print_(True)
    subprocess.run(
        ['gsettings', 'set', _GS_TOP_SCHEMA, 'custom-keybindings', val],
        capture_output=True,
    )


def get_binding(action_id: str) -> str:
    path = f'{_GS_BINDING_BASE}{action_id}/'
    r = subprocess.run(
        ['gsettings', 'get', f'{_GS_BINDING_SCHEMA}:{path}', 'binding'],
        capture_output=True, text=True,
    )
    val = r.stdout.strip().strip("'")
    return val if val and val != '' else ''


def apply(shortcuts: dict):
    """Write/remove GNOME custom keybindings. shortcuts: {action_id: binding_str}"""
    paths = _gs_get_list()
    for action_id, name, command in SHORTCUT_ACTIONS:
        path = f'{_GS_BINDING_BASE}{action_id}/'
        binding = shortcuts.get(action_id, '')
        if binding:
            if path not in paths:
                paths.append(path)
            for key, val in [('name', name), ('command', command), ('binding', binding)]:
                subprocess.run(
                    ['gsettings', 'set', f'{_GS_BINDING_SCHEMA}:{path}', key, val],
                    capture_output=True,
                )
        else:
            if path in paths:
                paths.remove(path)
                subprocess.run(
                    ['gsettings', 'set', f'{_GS_BINDING_SCHEMA}:{path}', 'binding', "''"],
                    capture_output=True,
                )
    _gs_set_list(paths)


def binding_label(binding: str) -> str:
    if not binding:
        return 'Disabled'
    keyval, mods = Gtk.accelerator_parse(binding)
    if keyval == 0:
        return binding
    return Gtk.accelerator_get_label(keyval, mods)


_MODIFIER_ONLY = {
    Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Shift_L,   Gdk.KEY_Shift_R,
    Gdk.KEY_Alt_L,     Gdk.KEY_Alt_R,
    Gdk.KEY_Super_L,   Gdk.KEY_Super_R,
    Gdk.KEY_Hyper_L,   Gdk.KEY_Hyper_R,
    Gdk.KEY_Meta_L,    Gdk.KEY_Meta_R,
}


def capture_shortcut(parent_dialog):
    """Open a modal dialog to capture one key combination.
    Returns binding string, '' to clear, or None to cancel."""
    dlg = Gtk.Dialog(title='Set shortcut', transient_for=parent_dialog, modal=True)
    dlg.set_default_size(320, -1)

    box = dlg.get_content_area()
    lbl = Gtk.Label()
    lbl.set_markup('<b>Press a key combination</b>\n'
                   '<small>Backspace to disable · Escape to cancel</small>')
    lbl.set_justify(Gtk.Justification.CENTER)
    lbl.set_margin_top(24)
    lbl.set_margin_bottom(24)
    lbl.set_margin_start(16)
    lbl.set_margin_end(16)
    box.pack_start(lbl, True, True, 0)
    box.show_all()

    result: dict = {'binding': None}

    def on_key(widget, event):
        if event.keyval == Gdk.KEY_Escape:
            dlg.response(Gtk.ResponseType.CANCEL)
            return True
        if event.keyval == Gdk.KEY_BackSpace:
            result['binding'] = ''
            dlg.response(Gtk.ResponseType.OK)
            return True
        if event.keyval in _MODIFIER_ONLY:
            return True
        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        binding = Gtk.accelerator_name(event.keyval, mods)
        if binding:
            result['binding'] = binding
            dlg.response(Gtk.ResponseType.OK)
        return True

    dlg.connect('key-press-event', on_key)
    dlg.run()
    dlg.destroy()
    return result['binding']
