"""GTK floating widget — fallback for X11 sessions where the GNOME Shell
extension's chrome-layer widget isn't available.

On GNOME Wayland the extension is preferred because Mutter doesn't honor
`keep_above` for regular client windows; this GTK fallback is best-effort.
"""

import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

from . import config


_POS_KEY = 'floating_pos'  # persisted in settings.json as [x, y]


class FloatingWidget(Gtk.Window):
    def __init__(self, on_click, on_menu=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_resizable(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_app_paintable(True)

        # Transparent background so rounded corners render cleanly.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        evbox = Gtk.EventBox()
        evbox.set_above_child(True)
        evbox.set_visible_window(True)
        self.add(evbox)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(10)
        box.set_margin_end(10)

        icon = Gtk.Image.new_from_icon_name('camera-photo-symbolic', Gtk.IconSize.BUTTON)
        box.pack_start(icon, False, False, 0)

        self._badge = Gtk.Label(label='')
        self._badge.get_style_context().add_class('paste-shots-badge')
        box.pack_start(self._badge, False, False, 0)
        self._badge.hide()

        evbox.add(box)

        css = b"""
        window { background-color: rgba(30, 30, 30, 0.85);
                 border-radius: 18px;
                 border: 1px solid rgba(255,255,255,0.15); }
        label { color: white; font-weight: bold; }
        .paste-shots-badge {
            background-color: rgba(220, 50, 50, 0.95);
            padding: 0 6px;
            border-radius: 9px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._dragging = False
        self._drag_start = None
        self._moved = False
        self._on_click = on_click
        self._on_menu = on_menu

        evbox.connect('button-press-event', self._on_press)
        evbox.connect('motion-notify-event', self._on_motion)
        evbox.connect('button-release-event', self._on_release)
        evbox.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK,
        )

        self.show_all()
        self.move(*self._restore_position())

    @staticmethod
    def _restore_position() -> tuple[int, int]:
        """Pull saved [x, y] from config, falling back to (80, 120) if the
        value is missing, malformed, or contains non-numeric entries."""
        pos = config.get(_POS_KEY)
        if isinstance(pos, list) and len(pos) == 2:
            try:
                return int(pos[0]), int(pos[1])
            except (TypeError, ValueError):
                pass
        return 80, 120

    def set_badge(self, count: int):
        if count > 0:
            self._badge.set_text(str(count))
            self._badge.show()
        else:
            self._badge.hide()

    def _on_press(self, _, event):
        # Right-click → context menu. Critical when tray_icon=False, since
        # the widget is then the only way to reach Settings/Quit.
        if event.button == 3 and self._on_menu:
            self._on_menu(event)
            return True
        if event.button != 1:
            return False
        self._dragging = True
        self._moved = False
        self._drag_start = (event.x_root, event.y_root, *self.get_position())
        return True

    def _on_motion(self, _, event):
        if not self._dragging:
            return False
        sx, sy, wx, wy = self._drag_start
        dx = event.x_root - sx
        dy = event.y_root - sy
        if abs(dx) > 3 or abs(dy) > 3:
            self._moved = True
        self.move(int(wx + dx), int(wy + dy))
        return True

    def _on_release(self, _, event):
        if event.button != 1:
            return False
        self._dragging = False
        if self._moved:
            cfg = dict(config.get_config())
            cfg[_POS_KEY] = list(self.get_position())
            config.save_config(cfg)
        else:
            if self._on_click:
                self._on_click()
        return True
