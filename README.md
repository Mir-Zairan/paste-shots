# paste-shots

[![PyPI](https://img.shields.io/pypi/v/paste-shots)](https://pypi.org/project/paste-shots/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<!-- demo GIF: record a short clip of the tray icon → paste into Claude Code / Teams, then replace the line below -->
<img width="1102" height="648" alt="paste-shots-demo" src="https://github.com/user-attachments/assets/ccfed55c-8a1a-4fcd-898a-907a2d886568" />

A utility that lets you batch multiple screenshots and paste them into
any app in one action — terminal AI tools like
[Claude Code](https://claude.ai/code) and [OpenCode](https://opencode.ai),
chat apps like Teams and Slack, issue trackers, email, and anywhere else
that accepts image paste. The niche it fills: **sending several screenshots
in a single action**, which the system clipboard alone can't do.

Runs as a system-tray icon with an optional **floating draggable widget**
(via a small bundled GNOME Shell extension). No cloud, no background
scanning.

## Supported versions

Targets **Ubuntu 22.04 LTS through 26.04 LTS** (GNOME 42–50). Everything
`install.sh` does is apt-based; other distributions (Fedora, Arch,
Debian-non-Ubuntu) aren't supported out of the box, though the Python/JS
code itself is distro-neutral if you install the dependencies by hand.

| Ubuntu | GNOME | Default session | Extension build used |
|---|---|---|---|
| 22.04 LTS (Jammy) | 42 | Wayland (X11 available) | `gnome-extension/legacy` (imports.*) |
| 22.10, 23.04 | 43, 44 | Wayland (X11 available) | `gnome-extension/legacy` |
| 23.10, 24.04 LTS, 24.10 | 45, 46, 47 | Wayland (X11 available) | `gnome-extension/modern` (ESM) |
| 25.04 | 48 | Wayland (X11 available) | `gnome-extension/modern` |
| 25.10, 26.04 LTS | 49, 50 | **Wayland-only** (GNOME-on-Xorg removed) | `gnome-extension/modern` |

Ubuntu 25.10 dropped GNOME-on-Xorg, and 26.04 LTS removed X11 from GDM
entirely — on those releases the GNOME session is Wayland under all
circumstances. paste-shots prefers the Wayland code path on those
systems automatically; the X11 fallback paths still fire for legacy
applications running under XWayland.

`install.sh` detects the GNOME Shell version and copies the correct
extension build to `~/.local/share/gnome-shell/extensions/`. Non-GNOME
desktops (KDE, XFCE) can use the core tray and paste pipeline but don't
get the focus-raise DBus service or the floating widget.

### Other distributions

`install.sh` only knows apt, but the runtime has no Ubuntu-specific
dependencies. To run on a non-Ubuntu system, install these packages by
hand (names vary by distro):

| Component | Ubuntu (apt) | Fedora (dnf) | Arch (pacman / AUR) |
|---|---|---|---|
| GTK + GObject Introspection | `python3-gi`, `gir1.2-gtk-3.0` | `python3-gobject`, `gtk3` | `python-gobject`, `gtk3` |
| Tray icon | `gir1.2-ayatanaappindicator3-0.1` | `libayatana-appindicator-gtk3` | `libayatana-appindicator` (AUR) |
| Tray host inside GNOME 41+ | `gnome-shell-extension-appindicator` | `gnome-shell-extension-appindicator` | `gnome-shell-extension-appindicator` |
| Wayland clipboard | `wl-clipboard` | `wl-clipboard` | `wl-clipboard` |
| X11 clipboard fallback | `xclip` | `xclip` | `xclip` |
| Wayland keystrokes | `ydotool` | `ydotool` | `ydotool` |
| X11 keystrokes | `xdotool` | `xdotool` | `xdotool` |
| Notifications | `libnotify-bin` | `libnotify` | `libnotify` |

After installing the deps, run paste-shots directly from a checkout —
`./scripts/paste-shots-tray` and `./scripts/paste-shots` work on any
distro. The `ydotoold` systemd user service that `install.sh` sets up on
Ubuntu also needs to be enabled for Wayland keystroke injection to work.

---

## Installation

### Recommended — installer script (Ubuntu)

```bash
git clone https://github.com/Mir-Zairan/paste-shots.git
cd paste-shots
./install.sh
```

### Via pip (any distro — system deps required)

```bash
pip install paste-shots
```

> The pip package installs the Python code and CLI entry points. You still need
> the system dependencies (GTK, clipboard, keystroke tools) listed in the
> **Other distributions** table above, and the GNOME Shell extension won't be
> installed automatically — use the installer script on Ubuntu for the full setup.

The installer takes care of:

- apt dependencies (clipboard, keystroke, GTK tray)
- CLI scripts into `~/.local/bin`
- `ydotoold` systemd **user** service + `uinput` udev rule (required for
  Ctrl+V injection on Wayland)
- GNOME Shell extension (`paste-shots@zaiarn`)
- Autostart for the tray

**If you're on Wayland, you MUST log out and log back in after the first
install** so the `input` group membership and the Shell extension load.

---

## Usage

### Tray menu

| Item | Behavior |
|---|---|
| **Paste new screenshots** | Everything taken since the last successful paste |
| **Paste last N…** | Dialog — pick how many recent shots |
| **Pick screenshots…** | GTK thumbnail picker with All / Last 3 / Last 5 shortcuts |
| **Open screenshots folder** | xdg-opens the watch folder |
| **Settings…** | See below |

The tray icon shows a live count of new (since last paste) screenshots,
updated via `inotify`.

### Floating widget

Optional — enable it in Settings. On **GNOME Wayland** the widget is drawn
by the Shell extension on the chrome layer: always above other windows,
draggable, position persists across sessions. On **X11** a plain GTK
always-on-top window is used as a fallback. Click the widget to run
"paste new"; drag it to reposition.

### Command line

**Paste actions** (the same three bound by Settings → Keyboard Shortcuts):

```bash
paste-shots             # paste everything since last paste
paste-shots 3           # paste the last 3
paste-shots --pick      # thumbnail picker
```

**Configuration from the shell** — useful for scripting, dotfile management,
or keybindings outside GNOME:

```bash
paste-shots --get                   # print whole config as JSON
paste-shots --get tray_icon         # print one value
paste-shots --set tray_icon=false   # write one value (parses JSON: true/false/numbers/strings)
paste-shots --set paste_delay=0.4
paste-shots --set 'custom_paste_targets=["jetbrains-phpstorm","helix"]'
paste-shots --settings              # open the settings dialog standalone
```

`--set` writes to `~/.config/paste-shots/settings.json` and signals the
running tray to hot-reload — no restart required. Settable keys are derived
from the defaults: `watch_dir`, `tray_icon`, `expanded_icons`,
`floating_widget`, `paste_delay`, `paste_mode`, `notifications`,
`autostart`, `custom_paste_targets`, `floating_pos`.

**Diagnostics & lifecycle:**

```bash
paste-shots --focused-class   # print the wm_class of the currently focused window
paste-shots --quit            # gracefully shut down the running tray
paste-shots --help            # full usage
```

`--focused-class` is the recommended way to discover the wm_class for an
unsupported app: focus that app, run the command from another terminal,
copy the output into Settings → Custom paste targets.

---

## Settings

| Setting | Default | Notes |
|---|---|---|
| Watch folder | `~/Pictures/Screenshots` | |
| Tray icon | on | |
| Floating widget | off | GNOME Shell extension preferred; GTK fallback on X11 |
| Paste delay | 0.6 s | Interval between multi-image pastes |
| Desktop notifications | on | |
| Launch at login | on | |
| **Paste target** | Terminals only | Controls which focused windows accept a paste. **Terminals only** *(default)* — paste only into terminal emulators. **Anywhere** — no focus validation, Ctrl+V fires into whatever has focus. To paste into a non-terminal app (IDE, chat, browser) either switch to Anywhere or list the app's WM\_CLASS in **Custom paste targets** below. |
| **Custom paste targets** | _(empty)_ | Extends the built-in terminal allowlist with your own WM\_CLASS substrings. Use this for apps not recognised by default — IDE terminals, chat apps with image-paste support, anything else. Run `paste-shots --focused-class` while the target app is focused to find its WM\_CLASS. |

### IDEs and other non-terminal apps

To paste into an IDE (VS Code, JetBrains, Cursor, Zed, Sublime, …), a chat
app, or anything else that isn't a terminal emulator, either:

- Switch **Paste target** to **Anywhere**, *or*
- Add the app's WM\_CLASS to **Custom paste targets** (run
  `paste-shots --focused-class` while the app is focused to read it).

Either way, **make sure the cursor / terminal pane / message field that
should receive the paste has keyboard focus before triggering paste-shots.**
The tool sends Ctrl+V to whatever currently has focus inside the target
window — it has no way to navigate to a specific pane.

Environment override: `PASTE_SHOTS_WATCH_DIR` takes precedence over the
settings-file value.

---

## Paste targets (where can it paste?)

paste-shots only sends Ctrl+V into windows on its **paste-target allowlist**.
Many apps silently drop image-clipboard paste (gedit, file managers, browsers
on certain pages, the desktop) and `ydotool` would falsely report success —
so the allowlist exists as a silent-fail guard. The mode controls how
aggressive the guard is:

| `paste_mode` | Accepts | Use case |
|---|---|---|
| `terminal_only` *(default)* | Standalone terminal emulators only. Other apps are accepted only if their WM\_CLASS is in **Custom paste targets**. | The intended path: paste screenshots into Claude Code, OpenCode, or any other terminal-driven assistant. |
| `any` | **Anything that has keyboard focus**, including IDEs, chat apps, browsers, image-aware text fields, document editors. | Unlocks paste-shots for general use beyond terminal AI tools — see below. |

### "Anywhere" mode — pasting outside terminal AI tools

Set **paste_mode = any** (Settings → Paste target → "Anywhere", or
`paste-shots --set paste_mode=any`) to bypass the allowlist entirely. Any
focused window receives Ctrl+V. With this turned on, the same batch and
picker flows work in:

- **Chat apps** that accept image paste — Discord, Slack, Element, Telegram
  Desktop, Signal, Matrix clients, Zulip, Mattermost, Rocket.Chat.
- **Issue trackers / docs** in a browser — GitHub/GitLab issue & PR comment
  fields, Linear, Jira, Notion, Confluence, Google Docs, Outline, HackMD.
- **Email composers** — Thunderbird, Geary, web Gmail, Outlook web.
- **Note-taking apps** — Obsidian, Logseq, Joplin, Standard Notes.
- **Anywhere a normal Ctrl+V on an image would work**, plus the things that
  the focus-allowlist would otherwise block.

The "batch multiple screenshots into one turn" workflow that motivates the
tool extends straight to multi-image messages on those services — drop three
before/after shots into a single Slack thread or GitHub comment in one
action, with the same focus-lock and paste-delay behaviour.

Note: the allowlist exists for a reason. With `any` you may occasionally
fire Ctrl+V into a window that silently swallows image paste; the marker
will still advance because `ydotool` reports success. If you find a class
of app where this happens, switch back to `terminal_only` and add a
`custom_paste_targets` entry instead.

---

## How pasting is verified

Each paste step is checked end-to-end:

1. Clipboard copy runs (`wl-copy` / `xclip`) — non-zero exit = failure.
2. Clipboard is then polled with `wl-paste --list-types` to confirm an image
   mime actually landed.
3. The target window is re-raised before each keystroke (see **Focus-lock** below).
4. `ydotool` / `xdotool` sends Ctrl+V — non-zero exit = failure.

**The "last paste" marker only advances when every file in the batch
succeeded.** If anything failed, the marker stays put so the next
"Paste new" run re-picks the failed files.

---

## Focus-lock

Before sending each Ctrl+V, paste-shots re-raises the window that had focus
when the paste was triggered, so a stray click partway through a multi-image
batch can't redirect the paste mid-flight. Always-on; not configurable.

| Session | Mechanism |
|---|---|
| X11 / XWayland | `xdotool windowactivate --sync` |
| Wayland + GNOME + extension | DBus into `org.pasteshots.Shell.RaiseWindow` |
| Wayland + GNOME (no extension) | Countdown notification, user switches manually |
| Wayland + sway/Hyprland | Countdown fallback (plug-in points exist for native protocols) |

---

## "New since last paste" logic

Each successful batch touches `~/.local/share/paste-shots/last-paste`. The
next run includes only files with `mtime > marker`. On first ever run,
everything from the past 10 minutes is eligible. Files that failed their
previous paste stay eligible until they succeed.

---

## GNOME Shell extension

Two parallel builds live in `gnome-extension/`:

- `legacy/paste-shots@zaiarn/` — GNOME 42–44 (`imports.*` module system)
- `modern/paste-shots@zaiarn/` — GNOME 45+ (ESM with `import`/`export`)

`install.sh` runs `gnome-shell --version` and copies the matching package
to `~/.local/share/gnome-shell/extensions/paste-shots@zaiarn/`. GNOME 45
broke the extension module system with no single-codebase backport, so the
two builds have to be maintained in parallel — keep them in sync when
changing behaviour.

The extension registers its DBus object on GNOME Shell's existing
`org.gnome.Shell` bus name (standard pattern for extensions) at object
path `/org/pasteshots/Shell`, interface `org.pasteshots.Shell`:

- `Ping() -> bool`
- `SnapshotFocused() -> string`
- `RaiseWindow(wid: string) -> bool`
- `RaiseLastTerminal() -> bool`
- `DescribeWindow(wid: string) -> string`
- `ShowFloatingWidget(bool) -> bool`
- `UpdateBadge(uint) -> bool`

The tool works without the extension — focus-lock falls back to a
countdown notification, and the floating widget falls back to the GTK
window.

---

## Supported formats

PNG, JPG, JPEG.

---

## Performance & footprint

Numbers from `scripts/bench` on Ubuntu 22.04 / Wayland / Python 3.10,
4-thread tray idle for ~4.5 hours:

| Metric | Value |
|---|---|
| Resident memory (RSS) | **45 MB** (peak = current — no growth) |
| Proportional set size (PSS) | **21 MB** (the more meaningful "private + share of shared") |
| Anonymous (Python heap) | **18 MB** |
| Swap used | **0 KB** |
| Threads | **4** — Python main, GLib mainloop, GDBus worker, dconf worker |
| Open file descriptors | **17** |
| Idle CPU | **0.0%** averaged over a 5-second sample |

Microbench timings (median of 200 runs unless noted):

| Hot path | n = 1 | n = 100 | n = 1000 |
|---|---:|---:|---:|
| `screenshots_in` (dir scan) | 9 µs | 440 µs | 4.7 ms |
| `find_since_marker` (no marker) | 24 µs | 800 µs | 8.6 ms |
| `find_since_marker` (with marker) | 21 µs | 625 µs | 6.9 ms |
| `find_last_n(3)` | 18 µs | 635 µs | 8.4 ms |

| Hot path | Median |
|---|---:|
| `is_paste_target("alacritty")` | 1.5 µs |
| `is_paste_target("firefox")` | 3.9 µs |
| `is_paste_target` × 8 mixed classes | 21 µs |
| Cold import of `paste_shots.cli` (CLI startup) | **2 ms** |

Real clipboard round-trip (1.2 MB PNG, wl-copy + verify):

| Step | Median | Mean |
|---|---:|---:|
| `copy_to_clipboard` end-to-end | 113 ms | 115 ms |
| `clipboard_has_image` (verify only) | 81 ms | 81 ms |

So the per-file paste budget is roughly: ~115 ms clipboard + ~5 ms focus
check + ~10 ms keystroke + the user-configurable `paste_delay` (default
**600 ms**, dwarfing everything else). Lowering `paste_delay` to 0.2–0.3 s
keeps multi-image pastes snappy on most receiving apps; the floor is
whatever the receiving terminal needs to consume one Ctrl+V before the
next.

Reproduce these numbers locally:

```bash
scripts/bench                # full report
scripts/bench --no-clipboard # skip the wl-copy round-trip
```

The harness uses an isolated tmp directory so it doesn't disturb your
live tray, real screenshots folder, or `settings.json`.

---

## Troubleshooting

### "no terminal/editor focused" on every paste
The paste-target allowlist is rejecting whatever window has focus — this
is the silent-fail guard that stops Ctrl+V firing into apps that ignore
image clipboard (gedit, browsers, file managers, the desktop). Click into
a real terminal or editor and try again. If you're using an unsupported
IDE, run `paste-shots --focused-class` while it's focused and paste the
result into **Settings → Custom paste targets**.

### Paste does nothing on Wayland
Most likely `ydotoold` isn't running, your user isn't in the `input`
group, or the `uinput` device isn't accessible. Run `install.sh` once,
then **log out and log back in** — the `input` group membership only
takes effect on a new session. To verify:

```bash
systemctl --user status ydotoold     # should be 'active (running)'
groups | tr ' ' '\n' | grep -x input # should print 'input'
ls -l /dev/uinput                    # should show a non-error stat
```

### "clipboard does not report image mime after copy"
The clipboard tool succeeded but the image never landed on the
selection. Confirm the right tool for your session is installed —
`wl-clipboard` for Wayland, `xclip` for X11. On Wayland, multiple
clipboard managers (e.g. `clipman`, `cliphist`) sometimes consume the
selection before paste-shots can verify it; quit the manager
temporarily to test.

### Paste lands in the wrong window
Focus-lock re-raises the window that had focus the moment you triggered
paste-shots — so the fix is to focus the right window *first*, then click
the tray icon (or run the CLI). If a stray window is winning the focus
race, run `paste-shots --focused-class` while you've focused the intended
target and confirm it returns the right WM\_CLASS. If paste-shots is
rejecting your target, add its WM\_CLASS to **Settings → Custom paste
targets** or switch **Paste target** to **Anywhere**.

### Tray icon doesn't appear on GNOME
GNOME 41+ removed legacy SystemTray support. The tray relies on the
`gnome-shell-extension-appindicator` extension, which `install.sh`
installs via apt. Verify it's present and enabled:

```bash
gnome-extensions list --enabled | grep appindicator
```

If missing, install it (`sudo apt install gnome-shell-extension-appindicator`
on Ubuntu, equivalent on other distros) and **log out / log back in**.

### Floating widget doesn't stay on top under Wayland
Under GNOME the widget should be drawn by the bundled Shell extension,
not GTK. Verify:

```bash
gnome-extensions list --enabled | grep paste-shots
```

If the extension isn't enabled, `install.sh` either failed to copy it
or you didn't log out and back in afterwards. The GTK fallback (X11)
honors `keep_above`, but Mutter intentionally ignores `keep_above` for
regular client windows on Wayland — that's why the extension exists.

### "tray already running; exiting"
A second tray instance was rejected by the singleton lock at
`$XDG_RUNTIME_DIR/paste-shots.lock`. If no tray is actually running
(crash, reboot quirk on a networked filesystem), run `paste-shots
--quit` to clean up; if that says "no tray was running," remove the
lock file manually.

### Marker keeps re-picking the same files
The "since last paste" marker only advances when **every** file in a
batch succeeded. If even one paste failed, the next "Paste new" run
re-picks the failed files so you can retry. To force-advance manually,
`touch ~/.local/share/paste-shots/last-paste`.

### How to confirm a paste really succeeded
paste-shots checks each step end-to-end:

1. Clipboard tool exit code (non-zero = failure)
2. Clipboard MIME via `wl-paste --list-types` / `xclip -t TARGETS`
3. Target window re-raise (when focus-lock is on)
4. Keystroke tool exit code

If any step fails, the marker stays put and a notification surfaces the
specific error. Step-level logging isn't on by default — running the
tray from a terminal (`paste-shots-tray`) prints any exceptions to
stderr.

---

## Development

```bash
python3 -m pytest tests/
```

Tests cover the pure logic (finders, marker-advance rules, config
load/save). Clipboard and keystroke paths require a live display and are
tested manually.

Layout:

```
paste-shots/
├── install.sh
├── pyproject.toml          # package metadata + console_scripts
├── scripts/
│   ├── paste-shots         # bash shim → python3 -m paste_shots.cli
│   └── paste-shots-tray    # bash shim → python3 -m paste_shots.tray_app
├── src/paste_shots/
│   ├── config.py           # settings.json + paths
│   ├── finders.py          # screenshot listing, marker rules (pure)
│   ├── clipboard.py        # wl-copy / xclip
│   ├── keys.py             # ydotool / xdotool keystroke injection
│   ├── pipeline.py         # focus → copy → raise → keystroke orchestration
│   ├── errors.py           # PasteError
│   ├── core.py             # back-compat re-export shim
│   ├── picker.py           # GTK thumbnail picker
│   ├── watcher.py          # inotify for the badge
│   ├── window.py           # focus-lock + DBus into the Shell extension
│   ├── floating.py         # GTK fallback widget
│   ├── shortcuts.py        # GNOME custom keybindings
│   ├── settings_dialog.py
│   ├── notify.py
│   ├── tray_app.py         # AppIndicator tray
│   ├── tray_ipc.py         # PID-file IPC between CLI and tray
│   └── cli.py              # CLI entrypoint
├── gnome-extension/paste-shots@zaiarn/
└── tests/
```

---

## License

MIT
