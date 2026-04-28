"""GTK settings dialog."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from . import config
from . import shortcuts
from .config import PasteMode


_PASTE_MODES: list[tuple[PasteMode, str]] = [
    (PasteMode.TERMINAL_ONLY, 'Terminals only'),
    (PasteMode.ANY,           'Anywhere (any focused window)'),
]


class SettingsDialog(Gtk.Dialog):
    def __init__(self):
        super().__init__(title='paste-shots Settings', modal=True)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(480, -1)

        box = self.get_content_area()

        grid = Gtk.Grid()
        grid.set_row_spacing(14)
        grid.set_column_spacing(16)
        grid.set_margin_top(18)
        grid.set_margin_bottom(4)
        grid.set_margin_start(20)
        grid.set_margin_end(20)
        box.pack_start(grid, True, True, 0)

        def lbl(text):
            w = Gtk.Label(label=text, xalign=0.0)
            w.set_hexpand(True)
            return w

        row = 0

        grid.attach(lbl('Watch folder'), 0, row, 1, 1)
        self._folder_btn = Gtk.FileChooserButton(
            title='Select screenshots folder',
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self._folder_btn.set_filename(config.get('watch_dir'))
        grid.attach(self._folder_btn, 1, row, 1, 1)
        row += 1

        grid.attach(lbl('Tray icon'), 0, row, 1, 1)
        self._sw_tray = Gtk.Switch(halign=Gtk.Align.END)
        self._sw_tray.set_active(config.get('tray_icon', True))
        self._sw_tray.set_tooltip_text('Show the main paste-shots icon in the system tray.')
        grid.attach(self._sw_tray, 1, row, 1, 1)
        row += 1

        grid.attach(lbl('Show extra action icons (Paste / Last N / Pick)'), 0, row, 1, 1)
        self._sw_expanded = Gtk.Switch(halign=Gtk.Align.END)
        self._sw_expanded.set_active(config.get('expanded_icons', False))
        self._sw_expanded.set_tooltip_text(
            'Adds three quick-action icons next to the main tray icon. '
            'Independent of the "Tray icon" toggle above.'
        )
        grid.attach(self._sw_expanded, 1, row, 1, 1)
        row += 1

        grid.attach(lbl('Floating widget (draggable)'), 0, row, 1, 1)
        self._sw_floating = Gtk.Switch(halign=Gtk.Align.END)
        self._sw_floating.set_active(config.get('floating_widget', False))
        grid.attach(self._sw_floating, 1, row, 1, 1)
        row += 1

        grid.attach(lbl('Paste delay (seconds)'), 0, row, 1, 1)
        self._spin_delay = Gtk.SpinButton.new_with_range(0.1, 3.0, 0.1)
        self._spin_delay.set_digits(1)
        self._spin_delay.set_value(config.get('paste_delay', 0.6))
        self._spin_delay.set_halign(Gtk.Align.END)
        grid.attach(self._spin_delay, 1, row, 1, 1)
        row += 1

        grid.attach(lbl('Paste target'), 0, row, 1, 1)
        self._combo_paste_mode = Gtk.ComboBoxText()
        self._paste_mode_ids = [m[0] for m in _PASTE_MODES]
        for _, label in _PASTE_MODES:
            self._combo_paste_mode.append_text(label)
        current_mode = config.get('paste_mode', PasteMode.TERMINAL_ONLY)
        idx = self._paste_mode_ids.index(current_mode) if current_mode in self._paste_mode_ids else 0
        self._combo_paste_mode.set_active(idx)
        self._combo_paste_mode.set_tooltip_text(
            'Controls which windows accept a paste.\n'
            '• Terminals only — terminal emulators only (default)\n'
            '• Anywhere — whatever window has focus, no validation\n'
            'To paste into an editor or chat app, use Anywhere mode\n'
            'or add its wm_class to Custom paste targets below.'
        )
        self._combo_paste_mode.set_halign(Gtk.Align.END)
        grid.attach(self._combo_paste_mode, 1, row, 1, 1)
        row += 1

        # Custom paste targets
        targets_lbl = lbl('Custom paste targets (one wm_class substring per line)')
        targets_lbl.set_tooltip_text(
            'Extra wm_class patterns accepted as paste targets in addition '
            'to the built-in terminal list. Substring + lowercase match.\n'
            'Use "Detect focused window" below to learn a window\'s wm_class.'
        )
        grid.attach(targets_lbl, 0, row, 2, 1)
        row += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(70)
        scrolled.set_shadow_type(Gtk.ShadowType.IN)
        self._tv_custom_targets = Gtk.TextView()
        self._tv_custom_targets.set_wrap_mode(Gtk.WrapMode.NONE)
        self._tv_custom_targets.set_monospace(True)
        existing = config.get('custom_paste_targets', []) or []
        self._tv_custom_targets.get_buffer().set_text(
            '\n'.join(p for p in existing if isinstance(p, str))
        )
        scrolled.add(self._tv_custom_targets)
        grid.attach(scrolled, 0, row, 2, 1)
        row += 1

        detect_btn = Gtk.Button(label='Detect focused window (3s)')
        detect_btn.set_tooltip_text(
            'Click, then switch to the target app within 3 seconds. Its '
            'wm_class is appended to the list above.'
        )
        detect_btn.set_halign(Gtk.Align.START)
        detect_btn.connect('clicked', self._on_detect_focused)
        self._detect_btn = detect_btn
        self._detect_timer_id = 0
        self._detect_remaining = 0
        grid.attach(detect_btn, 0, row, 2, 1)
        row += 1

        grid.attach(lbl('Desktop notifications'), 0, row, 1, 1)
        self._sw_notif = Gtk.Switch(halign=Gtk.Align.END)
        self._sw_notif.set_active(config.get('notifications', True))
        grid.attach(self._sw_notif, 1, row, 1, 1)
        row += 1

        grid.attach(lbl('Launch at login'), 0, row, 1, 1)
        self._sw_start = Gtk.Switch(halign=Gtk.Align.END)
        self._sw_start.set_active(config.AUTOSTART_FILE.exists())
        grid.attach(self._sw_start, 1, row, 1, 1)
        row += 1

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(6)
        sep.set_margin_bottom(2)
        grid.attach(sep, 0, row, 2, 1)
        row += 1

        hdr = Gtk.Label(xalign=0.0)
        hdr.set_markup('<b>Keyboard Shortcuts</b>')
        grid.attach(hdr, 0, row, 2, 1)
        row += 1

        self.connect('destroy', self._on_destroy)

        self._shortcut_btns: dict = {}
        for action_id, name, _ in shortcuts.SHORTCUT_ACTIONS:
            grid.attach(lbl(name), 0, row, 1, 1)
            current = shortcuts.get_binding(action_id)
            btn = Gtk.Button(label=shortcuts.binding_label(current))
            btn.set_halign(Gtk.Align.END)
            btn.connect('clicked', self._on_shortcut_btn, action_id, btn)
            self._shortcut_btns[action_id] = {'button': btn, 'binding': current}
            grid.attach(btn, 1, row, 1, 1)
            row += 1

        box.show_all()

    def _on_shortcut_btn(self, _, action_id, btn):
        result = shortcuts.capture_shortcut(self)
        if result is None:
            return
        self._shortcut_btns[action_id]['binding'] = result
        btn.set_label(shortcuts.binding_label(result))

    def _on_destroy(self, _w):
        if self._detect_timer_id:
            from gi.repository import GLib
            GLib.source_remove(self._detect_timer_id)
            self._detect_timer_id = 0

    def _on_detect_focused(self, btn):
        if self._detect_timer_id:
            return
        self._detect_remaining = 3
        btn.set_sensitive(False)
        btn.set_label(f'Switch focus now... {self._detect_remaining}')
        from gi.repository import GLib
        self._detect_timer_id = GLib.timeout_add(1000, self._detect_tick)

    def _detect_tick(self):
        from gi.repository import GLib
        self._detect_remaining -= 1
        if self._detect_remaining > 0:
            self._detect_btn.set_label(f'Switch focus now... {self._detect_remaining}')
            return True

        from . import window
        cls = (window.focused_class() or '').strip()
        own = (GLib.get_prgname() or '').lower()
        if not cls or cls.lower() == own or cls.endswith('.py'):
            line = '(focus did not change — keep the target app focused for the full 3s)'
        else:
            line = cls

        buf = self._tv_custom_targets.get_buffer()
        existing = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).rstrip()
        buf.set_text((existing + '\n' + line) if existing else line)

        self._detect_btn.set_label('Detect focused window (3s)')
        self._detect_btn.set_sensitive(True)
        self._detect_timer_id = 0
        return False

    def get_values(self) -> dict:
        tray_on = self._sw_tray.get_active()
        floating_on = self._sw_floating.get_active()
        if not tray_on and not floating_on:
            floating_on = True
        buf = self._tv_custom_targets.get_buffer()
        raw = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        custom = [
            line.strip() for line in raw.splitlines()
            if line.strip() and not line.strip().startswith('(')
        ]
        return {
            'watch_dir': self._folder_btn.get_filename() or config.DEFAULT_CONFIG['watch_dir'],
            'expanded_icons': self._sw_expanded.get_active(),
            'tray_icon': tray_on,
            'floating_widget': floating_on,
            'paste_delay': round(self._spin_delay.get_value(), 1),
            'notifications': self._sw_notif.get_active(),
            'autostart': self._sw_start.get_active(),
            'paste_mode': self._paste_mode_ids[self._combo_paste_mode.get_active()].value,
            'custom_paste_targets': custom,
            'shortcuts': {aid: d['binding'] for aid, d in self._shortcut_btns.items()},
        }
