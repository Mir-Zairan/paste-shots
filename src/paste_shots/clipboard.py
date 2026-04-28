"""Clipboard reads/writes via wl-clipboard or xclip.

Verifies the post-copy clipboard state before returning — without that check,
silent copy failures make the rest of the paste pipeline lie about success."""

import shutil
import subprocess
import time
from pathlib import Path

from .errors import PasteError


def _mime_for(path: Path) -> str:
    return 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'


def clipboard_has_image() -> bool:
    """Best-effort check that the clipboard currently holds an image mime.

    Returns False when no clipboard tool is available — the copy paths
    require one of these binaries, so reaching the no-tool branch here
    means the pipeline is degraded and we should not falsely claim
    success."""
    if shutil.which('wl-paste'):
        try:
            r = subprocess.run(['wl-paste', '--list-types'],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                return any(t.strip().startswith('image/') for t in r.stdout.splitlines())
        except subprocess.TimeoutExpired:
            return False
    if shutil.which('xclip'):
        try:
            r = subprocess.run(['xclip', '-selection', 'clipboard', '-t', 'TARGETS', '-o'],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                return any(t.strip().startswith('image/') for t in r.stdout.splitlines())
        except subprocess.TimeoutExpired:
            return False
    return False


def copy_to_clipboard(path: Path) -> None:
    """Copy path to clipboard. Raises PasteError on failure.

    wl-copy reads stdin in its parent, then forks a daemon child that owns
    the selection; the parent exits 0 as soon as that handoff has happened.
    Waiting on the parent is ~3x faster than a fixed 200ms sleep and more
    precise — the clipboard is guaranteed ready when wait() returns.
    """
    mime = _mime_for(path)
    if shutil.which('wl-copy'):
        with open(path, 'rb') as f:
            proc = subprocess.Popen(
                ['wl-copy', '--type', mime],
                stdin=f,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        try:
            rc = proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise PasteError('wl-copy did not hand off within 1.5s')
        if rc != 0:
            raise PasteError(f'wl-copy exited {rc}')
    elif shutil.which('xclip'):
        proc = subprocess.Popen(
            ['xclip', '-selection', 'clipboard', '-t', mime, '-i', str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # xclip daemonizes similarly; give it a short window to settle and
        # then verify via targets. We can't proc.wait() it because xclip
        # without --silent keeps the parent alive.
        time.sleep(0.05)
        if proc.poll() is not None and proc.returncode != 0:
            raise PasteError(f'xclip exited {proc.returncode}')
    else:
        raise PasteError('no clipboard tool found (install wl-clipboard or xclip)')

    if not clipboard_has_image():
        raise PasteError('clipboard does not report image mime after copy')
