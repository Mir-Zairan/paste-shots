#!/usr/bin/env python3
"""paste-shots CLI — paste recent screenshots into the focused terminal."""

import json
import sys
from enum import Enum, auto

from . import config
from . import core
from . import tray_ipc


class _Mode(Enum):
    SINCE = auto()
    LAST = auto()
    PICK = auto()


_USAGE = """Usage: paste-shots [N | --pick | --set key=value | --get [key] | --settings | --focused-class | --quit]
  (no args)        paste all screenshots since last paste
  N                paste the last N screenshots
  --pick           interactive picker
  --set k=v        set a config key (e.g. --set tray_icon=true) and reload tray
  --get [k]        print one config value, or the whole config if k omitted
  --settings       open the settings dialog
  --focused-class  print the wm_class of the currently focused window (use to
                   discover patterns for custom_paste_targets)
  --quit           gracefully shut down the running tray"""


def _settable_keys() -> set[str]:
    """All defaults are settable from the CLI. Derived from DEFAULT_CONFIG so
    new keys don't get accidentally rejected here."""
    return set(config.DEFAULT_CONFIG.keys())


def _cmd_set(arg: str) -> int:
    if '=' not in arg:
        print('paste-shots: --set requires key=value', file=sys.stderr)
        return 2
    key, raw = arg.split('=', 1)
    key = key.strip()
    settable = _settable_keys()
    if key not in settable:
        print(f'paste-shots: unknown key {key!r}. valid: {sorted(settable)}',
              file=sys.stderr)
        return 2
    try:
        value = json.loads(raw)  # parses true/false/numbers/strings
    except json.JSONDecodeError:
        value = raw  # bare string fallback
    cfg = dict(config.get_config())
    cfg[key] = value
    config.save_config(cfg)
    print(f'paste-shots: {key} = {json.dumps(value)}  →  {config.CONFIG_FILE}')
    tray_ipc.signal_tray(tray_ipc.SIG_RELOAD)
    return 0


def _cmd_get(key: str | None) -> int:
    cfg = config.get_config()
    if key is None:
        print(json.dumps(cfg, indent=2))
        return 0
    if key in cfg:
        print(json.dumps(cfg[key]))
        return 0
    # Fall back to DEFAULT_CONFIG so users querying a key that exists in
    # defaults but is missing from settings.json (e.g. legacy file) get a
    # useful answer instead of an error.
    if key in config.DEFAULT_CONFIG:
        print(json.dumps(config.DEFAULT_CONFIG[key]))
        return 0
    print(f'paste-shots: no such key {key!r}', file=sys.stderr)
    return 2


def _cmd_quit() -> int:
    """SIGTERM the running tray. The handler hides the floating widget and
    unregisters indicators before exit."""
    if tray_ipc.signal_tray(tray_ipc.SIG_QUIT):
        print('paste-shots: tray shutdown signal sent')
        return 0
    print('paste-shots: no tray was running')
    return 0


def _cmd_focused_class() -> int:
    """Print the wm_class of the currently focused window. Useful when
    discovering what to add to custom_paste_targets — the user runs this
    while the unsupported app is focused and pastes the result into the
    settings dialog."""
    from . import window
    cls = window.focused_class()
    print(cls or '(none)')
    return 0


def _cmd_settings() -> int:
    """Open the settings dialog standalone, save on OK, signal tray to reload."""
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from .settings_dialog import SettingsDialog
    from . import shortcuts as sc_mod
    dlg = SettingsDialog()
    response = dlg.run()
    if response == Gtk.ResponseType.OK:
        new_cfg = dlg.get_values()
        sc = new_cfg.pop('shortcuts', {})
        config.save_config(new_cfg)
        try:
            sc_mod.apply(sc)
        except Exception as e:
            print(f'paste-shots: shortcuts apply failed: {e}', file=sys.stderr)
        tray_ipc.signal_tray(tray_ipc.SIG_RELOAD)
        print('paste-shots: settings saved')
    dlg.destroy()
    return 0


def _pick() -> list:
    d = config.get_watch_dir()
    if not d.exists():
        print(f'paste-shots: folder not found: {d}', file=sys.stderr)
        return []
    from . import picker
    return picker.pick_from(d)


def main(argv: list) -> int:
    config.load_config()

    mode = _Mode.SINCE
    count = 0
    if argv:
        a = argv[0]
        if a in ('--pick', '-p'):
            mode = _Mode.PICK
        elif a in ('--help', '-h'):
            print(_USAGE)
            return 0
        elif a == '--set':
            if len(argv) < 2:
                print('paste-shots: --set requires key=value', file=sys.stderr)
                return 2
            return _cmd_set(argv[1])
        elif a == '--get':
            return _cmd_get(argv[1] if len(argv) > 1 else None)
        elif a == '--quit':
            return _cmd_quit()
        elif a == '--settings':
            return _cmd_settings()
        elif a == '--focused-class':
            return _cmd_focused_class()
        elif a.isdigit():
            mode = _Mode.LAST
            count = int(a)
        else:
            print(_USAGE, file=sys.stderr)
            return 2

    if mode is _Mode.SINCE:
        files = core.find_since_marker()
    elif mode is _Mode.LAST:
        files = core.find_last_n(count)
    else:
        files = _pick()

    if not files:
        print('paste-shots: no screenshots to paste')
        return 0

    total = len(files)
    print(f'paste-shots: pasting {total} screenshot(s)...')
    for f in files:
        print(f'  → {f.name}')
    advance_partial = mode is _Mode.LAST
    pasted, _, failures = core.paste_files_sync(files, advance_on_partial=advance_partial)
    for f, err in failures:
        print(f'  ✗ {f.name}: {err}', file=sys.stderr)
    print(f'paste-shots: done ({pasted}/{total} pasted)')
    # Mirror result as a desktop notification — important for the
    # floating-widget click path (CLI is launched headless, user has no
    # terminal to read print() output from).
    from .notify import notify_paste_result
    notify_paste_result(pasted, total, failures)
    if failures:
        if not pasted:
            print('paste-shots: marker not advanced — "paste new" will retry failed files',
                  file=sys.stderr)
        elif advance_partial:
            print('paste-shots: partial success — marker advanced to last pasted file; '
                  f'{len(failures)} file(s) failed',
                  file=sys.stderr)
    # Marker advanced (or didn't); either way the tray's badge needs a refresh.
    # Lightweight refresh signal — not a full config reload.
    tray_ipc.signal_tray(tray_ipc.SIG_REFRESH)
    return 0 if pasted == total else 1


def main_entry() -> None:
    """Console-script entrypoint (paste-shots wrapper)."""
    sys.exit(main(sys.argv[1:]))


if __name__ == '__main__':
    main_entry()
