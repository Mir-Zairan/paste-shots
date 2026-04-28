// paste-shots GNOME Shell extension (GNOME 45+ / ESM).
//
// Same functionality as the legacy (imports.*) build — see gnome-extension/legacy/
// for the pre-45 port. Keep the two in sync when changing behaviour.

import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

// We register on org.gnome.Shell rather than owning a separate bus name —
// the same pattern used by window-calls and other well-behaved extensions.
// Clients address us as --dest org.gnome.Shell --object-path /org/pasteshots/Shell
const CLIENT_BUS_NAME = 'org.gnome.Shell';
const OBJECT_PATH = '/org/pasteshots/Shell';
const CLI_PATH = GLib.get_home_dir() + '/.local/bin/paste-shots';
const STATE_FILE = GLib.get_home_dir() + '/.local/share/paste-shots/widget-state.json';

// Pure terminal emulators only. IDEs with integrated terminals (VS Code,
// Cursor) are excluded — they expose a single window so Ctrl+V lands in
// whichever pane was last focused. Run Claude Code in a real terminal.
const TERMINAL_CLASSES = [
    'gnome-terminal', 'gnome-terminal-server',
    'org.gnome.terminal', 'org.gnome.ptyxis', 'ptyxis',
    'alacritty', 'kitty', 'wezterm', 'foot',
    'terminator', 'tilix', 'xterm', 'urxvt', 'rxvt',
    'ghostty', 'konsole', 'warp', 'warp-terminal',
];

const DBUS_XML = `
<node>
  <interface name="org.pasteshots.Shell">
    <method name="Ping"><arg type="b" direction="out"/></method>
    <method name="SnapshotFocused"><arg type="s" direction="out"/></method>
    <method name="RaiseWindow">
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="RaiseLastTerminal"><arg type="b" direction="out"/></method>
    <method name="DescribeWindow">
      <arg type="s" direction="in"/>
      <arg type="s" direction="out"/>
    </method>
    <method name="ShowFloatingWidget">
      <arg type="b" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="UpdateBadge">
      <arg type="u" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="FocusedClass">
      <arg type="s" direction="out"/>
    </method>
  </interface>
</node>
`;


function _windowClass(w) {
    if (!w) return '';
    try {
        return (w.get_wm_class() || '').toLowerCase();
    } catch (_) {
        return '';
    }
}

function _isTerminal(w) {
    const cls = _windowClass(w);
    if (!cls) return false;
    return TERMINAL_CLASSES.some(t => cls.includes(t));
}

function _findWindowById(idStr) {
    const id = parseInt(idStr, 10);
    if (!Number.isFinite(id)) return null;
    const actors = global.get_window_actors();
    for (let i = 0; i < actors.length; i++) {
        const w = actors[i].meta_window;
        if (w && w.get_id && w.get_id() === id) return w;
    }
    return null;
}

function _activate(w) {
    if (!w) return false;
    try {
        const workspace = w.get_workspace();
        if (workspace) workspace.activate_with_focus(w, global.get_current_time());
        w.activate(global.get_current_time());
        return true;
    } catch (e) {
        console.error(`[paste-shots] activate failed: ${e}`);
        return false;
    }
}


// Extend St.BoxLayout directly so the widget auto-sizes to its children.
const FloatingWidget = GObject.registerClass({
    GTypeName: 'PasteShotsFloating',
}, class FloatingWidget extends St.BoxLayout {
    _init({ onClick, onMoved, onMenu, initialX, initialY }) {
        super._init({
            style_class: 'paste-shots-floating',
            reactive: true,
            can_focus: false,
            track_hover: true,
            vertical: false,
            x: initialX,
            y: initialY,
        });

        this._icon = new St.Icon({
            icon_name: 'camera-photo-symbolic',
            style_class: 'paste-shots-floating-icon',
        });
        this.add_child(this._icon);

        this._badge = new St.Label({
            text: '',
            style_class: 'paste-shots-floating-badge',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._badge.visible = false;
        this.add_child(this._badge);

        this._onClick = onClick;
        this._onMoved = onMoved;
        this._onMenu = onMenu;
        this._dragging = false;
        this._dragStart = null;
        this._moved = false;
        this._grab = null;

        this.connect('button-press-event', this._onPress.bind(this));
        this.connect('motion-event', this._onMotion.bind(this));
        this.connect('button-release-event', this._onRelease.bind(this));
        this.connect('destroy', () => this._endDrag(false));
    }

    setBadge(n) {
        if (n > 0) {
            this._badge.text = String(n);
            this._badge.visible = true;
        } else {
            this._badge.visible = false;
        }
    }

    _onPress(_actor, event) {
        if (event.get_button() === 3) {
            if (this._onMenu) this._onMenu();
            return Clutter.EVENT_STOP;
        }
        if (event.get_button() !== 1) return Clutter.EVENT_PROPAGATE;
        // Defensive: clean up any lingering grab from a drag that somehow
        // didn't end.
        this._endDrag(false);
        this._dragging = true;
        this._moved = false;
        const [x, y] = event.get_coords();
        this._dragStart = { ex: x, ey: y, wx: this.x, wy: this.y };
        // Modal grab so Mutter routes every pointer event to us for the
        // duration of the drag — without this, the moment the cursor
        // outruns the widget onto another app's window, Mutter delivers
        // events to that client's Wayland surface and we stop seeing
        // motion/release entirely, stranding _dragging at true (the bug
        // where hovering over the widget later resumed tracking with
        // no button held).
        try {
            this._grab = Main.pushModal(this, { timestamp: event.get_time() });
        } catch (_) {
            this._grab = null;
        }
        return Clutter.EVENT_STOP;
    }

    _onMotion(_actor, event) {
        if (!this._dragging) return Clutter.EVENT_PROPAGATE;
        const [x, y] = event.get_coords();
        const dx = x - this._dragStart.ex;
        const dy = y - this._dragStart.ey;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this._moved = true;
        this.set_position(Math.round(this._dragStart.wx + dx),
                          Math.round(this._dragStart.wy + dy));
        return Clutter.EVENT_STOP;
    }

    _onRelease(_actor, event) {
        if (event.get_button() !== 1) return Clutter.EVENT_PROPAGATE;
        this._endDrag(true);
        return Clutter.EVENT_STOP;
    }

    _endDrag(fireCallbacks) {
        if (this._grab) {
            try { Main.popModal(this._grab); } catch (_) {}
            this._grab = null;
        }
        if (!this._dragging) return;
        this._dragging = false;
        if (!fireCallbacks) return;
        if (this._moved) {
            if (this._onMoved) this._onMoved(this.x, this.y);
        } else {
            if (this._onClick) this._onClick();
        }
    }
});


export default class PasteShotsExtension extends Extension {
    enable() {
        console.log('[paste-shots] enable() starting');
        this._lastTerminalWin = null;
        this._badgeCount = 0;
        this._widget = null;
        this._focusSignal = 0;
        this._dbus = null;

        this._connectFocusTracker();
        this._exportDBus();
        this._maybeShowWidget();
        console.log('[paste-shots] enable() complete — DBus exported on ' + OBJECT_PATH);
    }

    disable() {
        if (this._focusSignal) {
            global.display.disconnect(this._focusSignal);
            this._focusSignal = 0;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        this._hideWidget();
        this._lastTerminalWin = null;
    }

    _connectFocusTracker() {
        this._focusSignal = global.display.connect('notify::focus-window', () => {
            const w = global.display.focus_window;
            if (_isTerminal(w)) this._lastTerminalWin = w;
        });
        const w = global.display.focus_window;
        if (_isTerminal(w)) this._lastTerminalWin = w;
    }

    _exportDBus() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_XML, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
    }

    // ---- DBus methods --------------------------------------------------

    Ping() { return true; }

    SnapshotFocused() {
        const w = global.display.focus_window;
        if (!w || !w.get_id) return '';
        if (!_isTerminal(w)) return '';
        return String(w.get_id());
    }

    RaiseWindow(idStr) {
        const w = _findWindowById(idStr);
        return _activate(w);
    }

    RaiseLastTerminal() {
        if (this._lastTerminalWin) {
            try { this._lastTerminalWin.get_id(); }
            catch (_) { this._lastTerminalWin = null; }
        }
        if (this._lastTerminalWin && _activate(this._lastTerminalWin)) return true;

        const actors = global.get_window_actors();
        const candidates = [];
        for (let i = 0; i < actors.length; i++) {
            const w = actors[i].meta_window;
            if (_isTerminal(w)) candidates.push(w);
        }
        if (!candidates.length) return false;
        candidates.sort((a, b) => b.get_user_time() - a.get_user_time());
        if (_activate(candidates[0])) {
            this._lastTerminalWin = candidates[0];
            return true;
        }
        return false;
    }

    DescribeWindow(idStr) {
        const w = _findWindowById(idStr);
        if (!w) return '';
        try {
            const title = w.get_title() || '';
            const cls = w.get_wm_class() || '';
            return title ? `${title} (${cls})` : cls;
        } catch (_) {
            return '';
        }
    }

    ShowFloatingWidget(show) {
        if (show) this._showWidget();
        else this._hideWidget();
        this._persistWidgetState({ visible: !!show });
        return true;
    }

    UpdateBadge(count) {
        this._badgeCount = count | 0;
        if (this._widget) this._widget.setBadge(this._badgeCount);
        return true;
    }

    FocusedClass() {
        const w = global.display.focus_window;
        if (!w) return '';
        try { return (w.get_wm_class() || '').toLowerCase(); }
        catch (_) { return ''; }
    }

    // ---- Floating widget -----------------------------------------------

    _loadWidgetState() {
        try {
            const [ok, contents] = GLib.file_get_contents(STATE_FILE);
            if (!ok) return {};
            return JSON.parse(new TextDecoder().decode(contents));
        } catch (_) {
            return {};
        }
    }

    _persistWidgetState(patch) {
        const state = Object.assign(this._loadWidgetState(), patch);
        try {
            GLib.mkdir_with_parents(GLib.path_get_dirname(STATE_FILE), 0o755);
            GLib.file_set_contents(STATE_FILE, JSON.stringify(state));
        } catch (e) {
            console.error(`[paste-shots] persist state failed: ${e}`);
        }
    }

    _maybeShowWidget() {
        const state = this._loadWidgetState();
        if (state.visible) this._showWidget();
    }

    _showWidget() {
        if (this._widget) return;
        const state = this._loadWidgetState();
        this._widget = new FloatingWidget({
            onClick: () => { GLib.spawn_command_line_async(CLI_PATH); },
            initialX: Number.isFinite(state.x) ? state.x : 80,
            initialY: Number.isFinite(state.y) ? state.y : 120,
            onMoved: (x, y) => this._persistWidgetState({ x, y }),
            onMenu: () => this._toggleMenu(),
        });
        Main.layoutManager.addChrome(this._widget, { affectsInputRegion: true });
        this._widget.setBadge(this._badgeCount);
        this._buildMenu();
    }

    _hideWidget() {
        this._destroyMenu();
        if (!this._widget) return;
        Main.layoutManager.removeChrome(this._widget);
        this._widget.destroy();
        this._widget = null;
    }

    _buildMenu() {
        if (this._menu) return;
        this._menu = new PopupMenu.PopupMenu(this._widget, 0.0, St.Side.TOP);
        const items = [
            ['Paste new screenshots', CLI_PATH],
            ['Paste last 3',          CLI_PATH + ' 3'],
            ['Pick…',                 CLI_PATH + ' --pick'],
            null,
            ['Settings…',             CLI_PATH + ' --settings'],
            ['Quit paste-shots',      CLI_PATH + ' --quit'],
        ];
        for (let i = 0; i < items.length; i++) {
            const it = items[i];
            if (it === null) {
                this._menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                continue;
            }
            const m = new PopupMenu.PopupMenuItem(it[0]);
            const cmd = it[1];
            m.connect('activate', () => {
                try { GLib.spawn_command_line_async(cmd); }
                catch (e) { console.error(`[paste-shots] cmd failed: ${cmd} — ${e}`); }
            });
            this._menu.addMenuItem(m);
        }
        this._menuManager = new PopupMenu.PopupMenuManager(this._widget);
        this._menuManager.addMenu(this._menu);
        Main.uiGroup.add_child(this._menu.actor);
        this._menu.actor.hide();
    }

    _destroyMenu() {
        if (this._menu) {
            try { this._menu.destroy(); } catch (_) {}
            this._menu = null;
        }
        this._menuManager = null;
    }

    _toggleMenu() {
        if (this._menu) this._menu.toggle();
    }
}
