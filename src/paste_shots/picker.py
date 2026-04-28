"""GTK thumbnail picker — replaces the zenity checkbox list."""

from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf, GLib, Gdk

from . import config
from . import core


_THUMB_W = 160
_THUMB_H = 100


class _ThumbItem(Gtk.Box):
    def __init__(self, path: Path):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.path = path
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(4)
        self.set_margin_end(4)

        img = Gtk.Image()
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(path), _THUMB_W, _THUMB_H, True,
            )
            img.set_from_pixbuf(pb)
        except Exception:
            img.set_from_icon_name('image-missing', Gtk.IconSize.DIALOG)
        img.set_size_request(_THUMB_W, _THUMB_H)
        # Wrap image in an EventBox so clicks on the thumbnail toggle selection.
        ebox = Gtk.EventBox()
        ebox.add(img)
        ebox.connect('button-press-event', self._on_click)
        self.pack_start(ebox, False, False, 0)

        self.check = Gtk.CheckButton(label=path.name)
        self.check.set_halign(Gtk.Align.CENTER)
        self.pack_start(self.check, False, False, 0)

    def _on_click(self, _widget, event):
        if event.button == 1:
            self.check.set_active(not self.check.get_active())

    @property
    def selected(self) -> bool:
        return self.check.get_active()

    @selected.setter
    def selected(self, v: bool):
        self.check.set_active(v)


class ThumbnailPicker(Gtk.Dialog):
    def __init__(self, files: list):
        super().__init__(title='paste-shots — pick screenshots', modal=True)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         'Paste selected', Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(760, 540)

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(10)
        content.set_margin_end(10)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_all = Gtk.Button(label='All')
        btn_none = Gtk.Button(label='None')
        btn_invert = Gtk.Button(label='Invert')
        btn_last3 = Gtk.Button(label='Last 3')
        btn_last5 = Gtk.Button(label='Last 5')
        btn_all.connect('clicked', lambda _: self._set_all(True))
        btn_none.connect('clicked', lambda _: self._set_all(False))
        btn_invert.connect('clicked', lambda _: self._invert())
        btn_last3.connect('clicked', lambda _: self._select_last(3))
        btn_last5.connect('clicked', lambda _: self._select_last(5))
        for b in (btn_all, btn_none, btn_invert, btn_last3, btn_last5):
            toolbar.pack_start(b, False, False, 0)
        self._count_label = Gtk.Label(label='')
        self._count_label.set_halign(Gtk.Align.END)
        self._count_label.set_hexpand(True)
        toolbar.pack_start(self._count_label, True, True, 0)
        content.pack_start(toolbar, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content.pack_start(scrolled, True, True, 0)

        self._flow = Gtk.FlowBox()
        self._flow.set_valign(Gtk.Align.START)
        self._flow.set_max_children_per_line(6)
        self._flow.set_min_children_per_line(2)
        self._flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow.set_row_spacing(6)
        self._flow.set_column_spacing(6)
        scrolled.add(self._flow)

        self._items: list[_ThumbItem] = []
        # Most recent first so the picker shows new shots at the top.
        for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
            item = _ThumbItem(f)
            item.check.connect('toggled', lambda _: self._update_count())
            self._items.append(item)
            self._flow.add(item)

        self._update_count()
        self.connect('key-press-event', self._on_key)
        self.show_all()

    def _on_key(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        return False

    def _set_all(self, v: bool):
        for it in self._items:
            it.selected = v
        self._update_count()

    def _invert(self):
        for it in self._items:
            it.selected = not it.selected
        self._update_count()

    def _select_last(self, n: int):
        # _items are sorted most-recent-first, so the first N are the latest.
        for i, it in enumerate(self._items):
            it.selected = i < n
        self._update_count()

    def _update_count(self):
        n = sum(1 for it in self._items if it.selected)
        self._count_label.set_text(f'{n} of {len(self._items)} selected')

    def get_selected(self) -> list[Path]:
        # Return in chronological order (oldest first) so Claude sees them in capture order.
        picked = [it.path for it in self._items if it.selected]
        return sorted(picked, key=lambda p: p.stat().st_mtime)


def pick_from(dir_path: Path, limit: int = 50) -> list[Path]:
    """Show the picker for the last `limit` screenshots. Returns selected paths."""
    files = sorted(core.screenshots_in(dir_path),
                   key=lambda f: f.stat().st_mtime,
                   reverse=True)[:limit]
    if not files:
        return []
    dlg = ThumbnailPicker(files)
    try:
        response = dlg.run()
        if response == Gtk.ResponseType.OK:
            return dlg.get_selected()
        return []
    finally:
        dlg.destroy()
        # Let Gtk process the destroy so the dialog actually closes before we return.
        while Gtk.events_pending():
            Gtk.main_iteration()
