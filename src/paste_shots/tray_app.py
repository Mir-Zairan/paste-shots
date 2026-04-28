#!/usr/bin/env python3
"""paste-shots tray — system tray icon for pasting screenshots."""

import gi
gi.require_version('AyatanaAppIndicator3', '0.1')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import AyatanaAppIndicator3 as AppIndicator3, Gtk, GLib

import fcntl
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path


from . import config
from . import core
from . import picker
from . import shortcuts
from . import tray_ipc
from . import window
from .notify import notify, notify_paste_result
from .settings_dialog import SettingsDialog
from .watcher import WatchDirMonitor

_FloatingWidget = None  # lazy-imported only when the GTK fallback is used


_EXTRA_INDICATOR_DEFS = [
    ('paste-shots-paste', 'document-send',       'Paste',  '_on_paste_new'),
    ('paste-shots-lastn', 'format-list-ordered', 'Last N', '_on_paste_last_n'),
    ('paste-shots-pick',  'edit-find',           'Pick',   '_on_pick'),
]


class PasteShotsApp:
    def __init__(self):
        # Indicators are built once at startup based on config. They cannot
        # be reliably hidden mid-session against gnome-shell-extension-
        # appindicator (Status PASSIVE is ignored, dropped DBus paths leave
        # stale entries in the watcher). Toggling tray_icon / expanded_icons
        # therefore triggers a self-restart instead of a live update.
        self.indicator = None
        self._extra_indicators: list = []
        self._floating = None
        self._watch = WatchDirMonitor(str(config.get_watch_dir()), self._refresh_badge)
        self._safety_timer_id = GLib.timeout_add_seconds(60, self._safety_refresh_tick)

        if config.get('tray_icon', True):
            self.indicator = self._build_main_indicator()
        if config.get('expanded_icons', False):
            self._extra_indicators = self._build_extra_indicators()

        self._refresh_badge()
        self._apply_floating_widget()

    def _build_main_indicator(self):
        ind = AppIndicator3.Indicator.new(
            'paste-shots',
            'camera-photo',
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        ind.set_title('paste-shots')
        ind.set_menu(self._build_menu())
        return ind

    def _build_extra_indicators(self) -> list:
        """Build the optional 'expanded' tray icons (Paste / Last N / Pick).

        AppIndicator API has no plain 'click handler' — every indicator must
        own a Gtk.Menu, which pops up on click. We make each indicator behave
        like a button by giving it a single-item menu that immediately
        pops down on `map` (i.e. as soon as the user clicks the icon) and
        schedules the action on idle. Without the popdown the user would
        have to click twice (once to open the menu, once to choose the only
        item).
        """
        def _click_handler(action):
            def _on_map(menu):
                menu.popdown()
                GLib.idle_add(action, None)
            return _on_map

        indicators = []
        for ind_id, icon, label, method_name in _EXTRA_INDICATOR_DEFS:
            ind = AppIndicator3.Indicator.new(
                ind_id, icon, AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            ind.set_title(label)
            action = getattr(self, method_name)
            menu = Gtk.Menu()
            item = Gtk.MenuItem(label=label)
            item.connect('activate', action)
            menu.append(item)
            menu.show_all()
            menu.connect('map', _click_handler(action))
            ind.set_menu(menu)
            indicators.append(ind)
        return indicators

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        self._item_new = Gtk.MenuItem(label='Paste new screenshots')
        self._item_new.connect('activate', self._on_paste_new)
        menu.append(self._item_new)

        item_n = Gtk.MenuItem(label='Paste last N…')
        item_n.connect('activate', self._on_paste_last_n)
        menu.append(item_n)

        item_pick = Gtk.MenuItem(label='Pick screenshots…')
        item_pick.connect('activate', self._on_pick)
        menu.append(item_pick)

        menu.append(Gtk.SeparatorMenuItem())

        item_folder = Gtk.MenuItem(label='Open screenshots folder')
        item_folder.connect('activate', lambda _: subprocess.Popen(['xdg-open', str(config.get_watch_dir())]))
        menu.append(item_folder)

        menu.append(Gtk.SeparatorMenuItem())

        item_settings = Gtk.MenuItem(label='Settings…')
        item_settings.connect('activate', self._open_settings)
        menu.append(item_settings)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label='Quit')
        item_quit.connect('activate', lambda _: self._quit())
        menu.append(item_quit)

        menu.show_all()
        return menu

    def _set_badge(self, count: int):
        label = f'{count} new' if count else ''
        if self.indicator is not None:
            self.indicator.set_label(label, '99 new')
        # Mirror to whichever floating UI is active.
        window.push_badge(count)
        if self._floating is not None:
            self._floating.set_badge(count)

    def _refresh_badge(self):
        self._set_badge(len(core.find_since_marker()))
        return False

    def _safety_refresh_tick(self):
        self._refresh_badge()
        return True  # keep the 60s timer running

    def _on_paste_done(self, pasted, total, failures):
        # Avoid urgency='critical' — Ubuntu Dock pulses the paste-shots
        # .desktop entry on critical notifications (phantom taskbar flash).
        # Normal urgency still surfaces the toast.
        notify_paste_result(pasted, total, failures)
        self._refresh_badge()

    def _paste_done_bridge(self, p, t, failures):
        GLib.idle_add(self._on_paste_done, p, t, failures)

    def _progress_bridge(self, done, total, _path):
        # Called from background thread after each file completes.
        GLib.idle_add(self._set_badge, total - done)

    def _start_paste(self, files, advance_on_partial=False):
        """Kick off paste with live badge decrement and done callback."""
        self._set_badge(len(files))
        core.paste_files(files,
                         on_done=self._paste_done_bridge,
                         on_progress=self._progress_bridge,
                         advance_on_partial=advance_on_partial)

    def _on_paste_new(self, _):
        files = core.find_since_marker()
        if not files:
            notify('paste-shots', 'No new screenshots found')
            return
        self._start_paste(files)

    def _on_paste_last_n(self, _):
        dialog = Gtk.Dialog(title='Paste last N', modal=True)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        box.pack_start(Gtk.Label(label='How many screenshots?'), False, False, 0)

        spin = Gtk.SpinButton.new_with_range(1, 50, 1)
        spin.set_value(3)
        spin.set_activates_default(True)
        box.pack_start(spin, False, False, 0)

        box.show_all()
        response = dialog.run()
        n = int(spin.get_value())
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            files = core.find_last_n(n)
            if not files:
                notify('paste-shots', 'No screenshots found')
                return
            self._start_paste(files, advance_on_partial=True)

    def _on_pick(self, _):
        d = config.get_watch_dir()
        if not d.exists():
            notify('paste-shots', f'Folder not found: {d}')
            return

        selected = picker.pick_from(d)
        if selected:
            self._start_paste(selected, advance_on_partial=True)

    def _open_settings(self, _):
        dialog = SettingsDialog()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_cfg = dialog.get_values()
            dialog.destroy()
            sc = new_cfg.pop('shortcuts', {})
            config.save_config(new_cfg)
            shortcuts.apply(sc)
            self._apply_config(new_cfg)
        else:
            dialog.destroy()

    def _apply_config(self, cfg: dict):
        config.set_autostart(cfg.get('autostart', True))
        # Indicator visibility cannot be applied live (see __init__ note).
        # If either toggle has changed, restart the process so the host
        # gets a clean unregister-then-register cycle via NameOwnerChanged.
        wants_main = cfg.get('tray_icon', True)
        wants_extras = cfg.get('expanded_icons', False)
        has_main = self.indicator is not None
        has_extras = bool(self._extra_indicators)
        if wants_main != has_main or wants_extras != has_extras:
            self._restart()
            return  # execv replaces us; nothing after this runs
        # Soft updates only beyond this point.
        if self.indicator is not None:
            self.indicator.set_menu(self._build_menu())
        self._watch.rebind(str(config.get_watch_dir()))
        self._apply_floating_widget()
        self._refresh_badge()

    def _apply_floating_widget(self):
        """Show/hide the floating widget per current config. Soft-toggleable —
        the GNOME Shell extension cleanly hides on DBus request, and the GTK
        fallback can be created/destroyed at will."""
        want = config.get('floating_widget', False)
        if want:
            if window.is_wayland() and window.is_gnome() and window.extension_available():
                window.show_floating_widget(True)
                self._destroy_gtk_floating()
            else:
                self._ensure_gtk_floating()
        else:
            if window.is_wayland() and window.is_gnome() and window.extension_available():
                window.show_floating_widget(False)
            self._destroy_gtk_floating()

    def _restart(self):
        """Restart to apply indicator-visibility changes.

        libappindicator + gnome-shell-extension-appindicator can't reliably
        toggle indicator visibility within a session (PASSIVE is silently
        ignored on this stack). The cleanest workaround is to drop our DBus
        connection — the host removes our items on NameOwnerChanged — and
        come back fresh.

        We spawn a *delayed* child rather than os.execv-ing immediately:
        with execv the new image registers indicators before the host has
        finished processing the old NameOwnerChanged, producing a brief
        flicker where both sets are visible. A short delay (0.4s) lets the
        host fully clean up before the replacement registers.

        We deliberately do NOT hide the extension's floating widget here:
        it lives in gnome-shell, persists across our process restart, and
        hiding it would cause a 400ms blink during the gap. The new
        process inherits its visible state. The GTK fallback (X11) is
        local to us so it does need to go.

        Spawn pattern: a small Python helper that sleeps then os.execv's
        the tray binary. Using a Python subprocess (not `sh -c "$tray_exec"`)
        avoids any shell-quoting concerns on the path string.
        """
        self._destroy_gtk_floating()
        if self._safety_timer_id:
            GLib.source_remove(self._safety_timer_id)
            self._safety_timer_id = 0
        self._watch.stop()
        tray_exec = str(Path.home() / '.local/bin/paste-shots-tray')
        helper = (
            'import os, sys, time; '
            'time.sleep(0.4); '
            'os.execv(sys.argv[1], [sys.argv[1]])'
        )
        subprocess.Popen(
            [sys.executable, '-c', helper, tray_exec],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        Gtk.main_quit()

    def _ensure_gtk_floating(self):
        if self._floating is not None:
            return
        global _FloatingWidget
        if _FloatingWidget is None:
            from .floating import FloatingWidget as _FW
            _FloatingWidget = _FW
        self._floating = _FloatingWidget(
            on_click=lambda: self._on_paste_new(None),
            on_menu=self._popup_floating_menu,
        )

    def _popup_floating_menu(self, event):
        """Right-click on floating widget → same menu as the tray icon.

        Critical when tray_icon=False — without this, the floating widget is
        the only entry point and there'd be no way to reach Settings.
        """
        menu = self._build_menu()
        menu.popup_at_pointer(event)

    def _destroy_gtk_floating(self):
        if self._floating is not None:
            self._floating.destroy()
            self._floating = None

    def _quit(self):
        """Tear down all visible UI surfaces, then exit the GTK main loop.

        The bus connection drops on process exit — that's what actually
        unregisters our indicators from the host (NameOwnerChanged). The
        floating widget lives in the GNOME Shell extension, so we have to
        explicitly tell it to hide before we go.
        """
        if window.is_wayland() and window.is_gnome() and window.extension_available():
            window.show_floating_widget(False)
        self._destroy_gtk_floating()
        if self._safety_timer_id:
            GLib.source_remove(self._safety_timer_id)
            self._safety_timer_id = 0
        self._watch.stop()
        Gtk.main_quit()


_lock_fd = -1  # module-scoped so the FD outlives main() and keeps the flock alive
_app: 'PasteShotsApp | None' = None  # set in main() so SIGUSR1 can reach it


def _acquire_singleton_lock() -> bool:
    """Refuse a second tray instance. Returns True if we got the lock.

    FD_CLOEXEC is set so a self-restart via execv (used to apply indicator
    visibility changes) drops the old lock cleanly before the new image
    tries to reacquire it. Without CLOEXEC, the kernel sees the same PID
    holding two separate open file descriptions on the same file and the
    second flock() call fails.

    After acquiring the lock we write our PID into the file so the CLI can
    signal us by PID (precise) instead of by `pkill -f tray_app.py` (which
    would also hit editors and grep pipelines that mention the filename)."""
    global _lock_fd
    fd = os.open(str(tray_ipc.lock_path()),
                 os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return False
    # Stamp our PID. ftruncate + write keeps the same inode (so CLI readers
    # that already opened the file see the new content on their next read).
    os.ftruncate(fd, 0)
    os.write(fd, f'{os.getpid()}\n'.encode())
    os.fsync(fd)
    _lock_fd = fd
    return True


def _idle_once(callback) -> None:
    """Schedule callback to run once on the GLib main loop.

    Wraps the common signal-handler pattern: signal handlers run in a
    signal context where calling GTK is unsafe, so we defer to idle. The
    inner function returns False so GLib drops the source after one run."""
    def _run():
        callback()
        return False
    GLib.idle_add(_run)


def _hot_reload(*_):
    """SIGUSR1 handler: re-read settings.json and re-apply.

    Called when config changes (`paste-shots --set`, settings dialog OK)
    so the running tray picks up the change without a restart."""
    if _app is None:
        return
    _idle_once(lambda: _app._apply_config(config.load_config()))


def _refresh_badge_signal(*_):
    """SIGUSR2 handler: cheap badge refresh after a CLI paste.

    The CLI emits this instead of SIGUSR1 because rebuilding menus,
    rebinding the watcher, and re-applying autostart on every paste was
    pure overhead — the only thing that changed is the marker file."""
    if _app is None:
        return
    _idle_once(_app._refresh_badge)


def _graceful_exit(*_):
    """SIGTERM handler: clean shutdown via _quit so the extension widget
    gets hidden and indicators are unregistered before we go."""
    if _app is None:
        Gtk.main_quit()
        return
    _idle_once(_app._quit)


def main():
    global _app
    if not _acquire_singleton_lock():
        sys.stderr.write('paste-shots tray already running; exiting.\n')
        sys.exit(0)
    config.load_config()
    _app = PasteShotsApp()
    signal.signal(signal.SIGUSR1, _hot_reload)
    signal.signal(signal.SIGUSR2, _refresh_badge_signal)
    signal.signal(signal.SIGTERM, _graceful_exit)
    signal.signal(signal.SIGINT, _graceful_exit)
    Gtk.main()


if __name__ == '__main__':
    main()
