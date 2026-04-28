#!/usr/bin/env bash
# paste-shots installer.
#
# What it does:
#   1. Installs apt dependencies (clipboard, keystroke tools)
#   2. Installs scripts into ~/.local/bin
#   3. Sets up the ydotoold systemd *user* service (Wayland Ctrl+V needs it)
#   4. Installs the GNOME Shell extension (focus-lock DBus + floating widget)
#   5. Registers autostart for the tray
#
# Idempotent — safe to re-run.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/share/paste-shots/lib"
AUTOSTART_DIR="$HOME/.config/autostart"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
EXT_ROOT="$REPO_DIR/gnome-extension"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/paste-shots@zaiarn"

SESSION="${XDG_SESSION_TYPE:-x11}"
DESKTOP="${XDG_CURRENT_DESKTOP:-}"

say()   { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[warn]\033[0m %s\n" "$*" >&2; }
fail()  { printf "\033[1;31m[fail]\033[0m %s\n" "$*" >&2; exit 1; }

need_sudo() {
    if ! sudo -n true 2>/dev/null; then
        say "sudo needed for apt and /dev/uinput setup — you may be prompted."
    fi
}

# ---------- 1. apt dependencies ------------------------------------------

say "Installing core dependencies (session: $SESSION, desktop: $DESKTOP)..."
need_sudo

CORE_PKGS=(
    gir1.2-ayatanaappindicator3-0.1
    gnome-shell-extension-appindicator
    python3-gi
    libnotify-bin
)

if [[ "$SESSION" == "wayland" ]]; then
    # ydotoold is a separate apt package on every Ubuntu from 22.04 onward.
    # Note: on Jammy (22.04) the apt version is 0.1.8, whose daemon has a
    # known SIGSEGV on every accepted client (ReimuNotMoe/ydotool#103). We
    # install the daemon package regardless (ydotool depends on it), but
    # below we skip setting up the systemd unit on that version so ydotool
    # reliably uses its direct-uinput fallback instead.
    SESSION_PKGS=(wl-clipboard ydotool ydotoold)
else
    SESSION_PKGS=(xclip xdotool)
fi

sudo apt-get update -qq
sudo apt-get install -y "${CORE_PKGS[@]}" "${SESSION_PKGS[@]}"

# ---------- 2. scripts ---------------------------------------------------

say "Installing Python package to $LIB_DIR..."
mkdir -p "$LIB_DIR"
# Wipe any prior install. We used to ship loose *.py files at $LIB_DIR root
# (pre-package layout) — purge those too so an upgrade doesn't leave shadow
# modules that take precedence over the package on import.
rm -f "$LIB_DIR"/*.py
rm -rf "$LIB_DIR/paste_shots"
mkdir -p "$LIB_DIR/paste_shots"
install -m 644 "$REPO_DIR/src/paste_shots/"*.py "$LIB_DIR/paste_shots/"

say "Installing CLI shims to $BIN_DIR..."
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/paste-shots" <<EOF
#!/usr/bin/env bash
exec env PYTHONPATH="$LIB_DIR\${PYTHONPATH:+:\$PYTHONPATH}" python3 -m paste_shots.cli "\$@"
EOF
chmod 755 "$BIN_DIR/paste-shots"

cat > "$BIN_DIR/paste-shots-tray" <<EOF
#!/usr/bin/env bash
exec env PYTHONPATH="$LIB_DIR\${PYTHONPATH:+:\$PYTHONPATH}" python3 -m paste_shots.tray_app "\$@"
EOF
chmod 755 "$BIN_DIR/paste-shots-tray"

# ---------- 3. ydotool + ydotoold user service (Wayland) -----------------

if [[ "$SESSION" == "wayland" ]]; then
    say "Configuring ydotool / ydotoold (Wayland keystroke injection)..."

    if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
        echo "    user already in 'input' group"
    else
        sudo usermod -aG input "$USER"
        warn "Added $USER to the 'input' group — you MUST log out and back in for this to take effect."
    fi

    # Udev rule so /dev/uinput stays group-writable across reboots.
    UDEV_RULE="/etc/udev/rules.d/60-paste-shots-uinput.rules"
    if [[ ! -f "$UDEV_RULE" ]]; then
        echo 'KERNEL=="uinput", MODE="0660", GROUP="input", TAG+="uaccess"' | \
            sudo tee "$UDEV_RULE" >/dev/null
        sudo udevadm control --reload-rules
        sudo udevadm trigger --name-match=uinput || true
    fi

    sudo modprobe uinput || warn "could not modprobe uinput; Ctrl+V injection may fail until reboot"

    # ydotoold would speed things up, but the Jammy apt package (0.1.8) has
    # a SIGSEGV after every accepted client (ReimuNotMoe/ydotool#103, #139,
    # #201). That crash is what causes paste-shots's "only the first
    # screenshot lands" symptom: the first ctrl+v hits a live daemon, the
    # daemon dies, subsequent ctrl+v calls fall into the 2s systemd restart
    # window and injection becomes unreliable.
    #
    # ydotool without the daemon uses direct /dev/uinput (the "latency+delay"
    # notice it prints is cosmetic — every Ctrl+V lands, verified). So on
    # 0.1.x we deliberately DON'T run the daemon.
    YDOTOOLD_BIN="$(command -v ydotoold || true)"
    YDOTOOLD_PKG_VER="$(dpkg-query -W -f='${Version}' ydotoold 2>/dev/null || true)"
    YDOTOOLD_BROKEN=0
    if [[ -n "$YDOTOOLD_BIN" && "$YDOTOOLD_PKG_VER" == 0.1.* ]]; then
        YDOTOOLD_BROKEN=1
    fi

    if [[ -n "$YDOTOOLD_BIN" && "$YDOTOOLD_BROKEN" -eq 0 ]]; then
        mkdir -p "$SYSTEMD_USER_DIR"
        cat > "$SYSTEMD_USER_DIR/ydotoold.service" <<EOF
[Unit]
Description=ydotoold user daemon for paste-shots keystroke injection

[Service]
Type=simple
ExecStart=$YDOTOOLD_BIN --socket-path=%t/.ydotool_socket --socket-own=%U:%G
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable --now ydotoold.service || \
            warn "ydotoold failed to start — run 'journalctl --user -u ydotoold' to investigate"

        # Tell ydotool where the socket is. Written to .profile so it applies
        # to graphical sessions started via GDM (.bashrc does NOT run there).
        if ! grep -q YDOTOOL_SOCKET "$HOME/.profile" 2>/dev/null; then
            cat >> "$HOME/.profile" <<'EOF'

# paste-shots: tell ydotool where ydotoold's socket lives
export YDOTOOL_SOCKET="$XDG_RUNTIME_DIR/.ydotool_socket"
EOF
            warn "Added YDOTOOL_SOCKET to ~/.profile — log out/in so the tray picks it up."
        fi
    else
        if [[ "$YDOTOOLD_BROKEN" -eq 1 ]]; then
            warn "Skipping ydotoold setup: apt ships ydotool $YDOTOOLD_PKG_VER, whose"
            warn "daemon segfaults on every client connection. paste-shots will use"
            warn "ydotool's direct-uinput mode instead, which is slightly slower but"
            warn "reliable for multi-image paste."
        else
            echo "    ydotoold binary not present — ydotool will run in direct uinput mode"
        fi
        # Tear down a previously-installed (broken) service unit and the
        # YDOTOOL_SOCKET export so ydotool stops trying to use the daemon.
        if systemctl --user is-enabled ydotoold.service >/dev/null 2>&1 \
           || systemctl --user is-active ydotoold.service >/dev/null 2>&1; then
            systemctl --user disable --now ydotoold.service 2>/dev/null || true
        fi
        if [[ -f "$SYSTEMD_USER_DIR/ydotoold.service" ]]; then
            rm -f "$SYSTEMD_USER_DIR/ydotoold.service"
            systemctl --user daemon-reload
        fi
        if grep -q 'paste-shots: tell ydotool where ydotoold' "$HOME/.profile" 2>/dev/null; then
            sed -i '/# paste-shots: tell ydotool where ydotoold/,/^export YDOTOOL_SOCKET=/d' "$HOME/.profile"
            warn "Removed stale YDOTOOL_SOCKET export from ~/.profile — log out/in so"
            warn "the tray no longer inherits it."
        fi
        # If a stale socket file was left behind by the crashed daemon,
        # ydotool will keep trying to use it. Remove it.
        rm -f /tmp/.ydotool_socket 2>/dev/null || true
    fi
fi

# ---------- 4. GNOME Shell extension -------------------------------------

if [[ "$DESKTOP" == *GNOME* && -d "$EXT_ROOT" ]]; then
    # Detect GNOME Shell major version to pick the right package.
    # GNOME 42-44: legacy imports.* module system.
    # GNOME 45+:   ESM — import/export syntax, different Extension base class.
    # These are incompatible source-trees; we ship both and install one.
    GNOME_VER="$(gnome-shell --version 2>/dev/null | awk '{print $3}' | cut -d. -f1)"
    if [[ -n "$GNOME_VER" && "$GNOME_VER" -ge 45 ]]; then
        EXT_SRC="$EXT_ROOT/modern/paste-shots@zaiarn"
        say "Installing GNOME Shell extension (modern / ESM build for GNOME $GNOME_VER)..."
    else
        EXT_SRC="$EXT_ROOT/legacy/paste-shots@zaiarn"
        say "Installing GNOME Shell extension (legacy build for GNOME ${GNOME_VER:-unknown})..."
    fi

    if [[ -d "$EXT_SRC" ]]; then
        mkdir -p "$(dirname "$EXT_DIR")"
        rm -rf "$EXT_DIR"
        cp -r "$EXT_SRC" "$EXT_DIR"

        if command -v gnome-extensions >/dev/null; then
            gnome-extensions enable paste-shots@zaiarn 2>/dev/null || \
                warn "Could not enable the extension automatically. Log out and back in, then run:
         gnome-extensions enable paste-shots@zaiarn"
        else
            warn "gnome-extensions CLI not found — enable manually via Extensions app after relog."
        fi

        if [[ "$SESSION" == "wayland" ]]; then
            warn "GNOME Wayland requires a full log out to load the extension (Alt+F2 r does not work on Wayland)."
        else
            warn "Run  Alt+F2 → type 'r' → Enter  to reload GNOME Shell and activate the extension (no logout needed on X11)."
        fi
    else
        warn "Extension source missing at $EXT_SRC — skipping."
    fi
fi

# ---------- 5a. App launcher entry (Activities / app grid) ---------------

# Distinct from the autostart entry below — this one shows in the GNOME
# Activities overview / app grid so the user can re-launch the tray after
# explicitly Quitting it without dropping to a terminal.
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/paste-shots.desktop" <<EOF
[Desktop Entry]
Name=Paste Shots
Comment=Paste recent screenshots into the focused window
Exec=$BIN_DIR/paste-shots-tray
Icon=camera-photo
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=false
Keywords=screenshot;paste;clipboard;
EOF
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

# ---------- 5. Autostart -------------------------------------------------

# Purge any pre-existing systemd user unit. We standardise on the XDG
# autostart entry below; a parallel systemd unit (sometimes installed by
# hand, or by older revisions of this script) races the .desktop entry at
# login and produces *two* tray instances. Singleton locking now refuses
# the duplicate, but cleaning up the unit keeps the system tidy.
STRAY_UNIT="$SYSTEMD_USER_DIR/paste-shots-tray.service"
STRAY_WANT="$SYSTEMD_USER_DIR/default.target.wants/paste-shots-tray.service"
if [[ -f "$STRAY_UNIT" || -L "$STRAY_WANT" ]]; then
    say "Removing stray systemd user unit (paste-shots-tray.service)..."
    systemctl --user disable --now paste-shots-tray.service 2>/dev/null || true
    rm -f "$STRAY_UNIT" "$STRAY_WANT"
    systemctl --user daemon-reload 2>/dev/null || true
fi

say "Setting up autostart for the tray..."
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/paste-shots.desktop" <<EOF
[Desktop Entry]
Name=paste-shots
Comment=Paste screenshots into the focused terminal
Exec=$BIN_DIR/paste-shots-tray
Icon=camera-photo
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=false
EOF

# ---------- 6. Restart running tray (upgrade path) -----------------------

TRAY_PID="$(pgrep -f 'paste_shots.tray_app|tray_app.py' | head -1 || true)"
if [[ -n "$TRAY_PID" ]]; then
    say "Restarting running tray (PID $TRAY_PID) to pick up new code..."
    # Give the tray a chance to exit cleanly via its signal handler.
    kill -TERM "$TRAY_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        sleep 0.5
        kill -0 "$TRAY_PID" 2>/dev/null || break
    done
    # Force-kill if it didn't exit.
    kill -KILL "$TRAY_PID" 2>/dev/null || true
    sleep 0.3
    nohup "$BIN_DIR/paste-shots-tray" >/dev/null 2>&1 &
    say "Tray restarted (PID $!)."
fi

# ---------- Summary ------------------------------------------------------

# Warn if ~/.local/bin is not yet on PATH so the user isn't left confused.
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR is not in your PATH."
    warn "Add this to ~/.bashrc (or ~/.profile for graphical sessions):"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

say "Done."
echo
echo "Next steps:"
echo "  • Start the tray now:  paste-shots-tray &"
if [[ "$SESSION" == "wayland" ]]; then
    echo "  • LOG OUT and back in so the 'input' group membership and the"
    echo "    GNOME Shell extension take effect."
fi
echo
echo "Usage:"
echo "  paste-shots            # paste all screenshots since last paste"
echo "  paste-shots 3          # paste the last 3"
echo "  paste-shots --pick     # thumbnail picker"
