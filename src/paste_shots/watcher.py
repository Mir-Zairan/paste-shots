"""Directory watcher using GIO inotify — replaces polling for badge updates.

Falls back silently to a no-op if the Gio monitor can't be created; the tray
also runs a 60s safety refresh, so we don't need to fight file-monitor edge
cases (network mounts, FUSE) here.
"""

import sys

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gio, GLib


class WatchDirMonitor:
    def __init__(self, path_str: str, on_change):
        """on_change is called on the GLib main loop thread with no args."""
        self._on_change = on_change
        self._monitor = None
        self._debounce_id = 0
        self._start(path_str)

    def _start(self, path_str: str):
        try:
            gfile = Gio.File.new_for_path(path_str)
            self._monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._monitor.set_rate_limit(200)
            self._monitor.connect('changed', self._on_event)
        except GLib.Error as e:
            print(f'paste-shots: watcher failed for {path_str}: {e.message}',
                  file=sys.stderr)
            self._monitor = None

    def _on_event(self, _monitor, _file, _other, event):
        if event in (
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.MOVED_IN,
            Gio.FileMonitorEvent.MOVED_OUT,
            Gio.FileMonitorEvent.RENAMED,
        ):
            self._schedule()

    def _schedule(self):
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(150, self._fire)

    def _fire(self):
        self._debounce_id = 0
        try:
            self._on_change()
        except Exception as e:
            # Callback runs on the GLib main thread; we don't want a buggy
            # listener to terminate the whole tray, but silent swallow hides
            # real bugs. Surface to stderr so `paste-shots-tray` from a
            # terminal shows them.
            print(f'paste-shots: watcher callback raised: {e!r}',
                  file=sys.stderr)
        return False

    def rebind(self, new_path: str):
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        self._start(new_path)

    def stop(self):
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
