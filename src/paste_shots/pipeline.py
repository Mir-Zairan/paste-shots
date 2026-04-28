"""Paste pipeline: focus check → clipboard → keystroke.

The orchestration that ties clipboard, keys, and window/focus together
into one user-visible action. `paste_files` is the async (background-thread)
form used by the tray; `paste_files_sync` is the blocking form used by the
CLI."""

import os
import threading
import time
from pathlib import Path

from . import config
from . import window
from .clipboard import copy_to_clipboard
from .errors import PasteError
from .keys import send_ctrl_v


def _paste_one(path: Path) -> tuple[bool, str | None]:
    """Return (success, error_msg_or_None).

    Focus check FIRST: if the wrong app is focused, copying first spawns
    an orphan wl-copy daemon per file that races with a retry, and the
    first retry file intermittently times out on hand-off. Bailing before
    any clipboard work keeps the wl-copy fleet clean."""
    try:
        cls = window.focused_class()
        if not window.is_paste_target(cls):
            raise PasteError(
                f'no terminal focused (focus: {cls or "none"}). '
                f'Click into a terminal first.'
            )
        copy_to_clipboard(path)
        send_ctrl_v()
        return True, None
    except PasteError as e:
        return False, str(e)


def _advance_marker_on_success(
    results: list[tuple[bool, str | None]],
    files: list[Path] | None = None,
    advance_on_partial: bool = False,
) -> None:
    """Advance the marker file after paste.

    Default (advance_on_partial=False): only advance when every paste succeeded.
    This gives "paste new" retry semantics — failed files reappear next run.

    advance_on_partial=True (last-N / pick mode): advance even when some files
    failed, setting the marker mtime to the last successfully pasted file so
    the next "paste new" doesn't re-include already-pasted shots.
    """
    if not results:
        return
    all_ok = all(ok for ok, _ in results)
    if not all_ok and not advance_on_partial:
        return
    if advance_on_partial and not any(ok for ok, _ in results):
        return
    config._ensure_data_dir()
    config.MARKER_FILE.touch()
    if advance_on_partial and files:
        last_ok: Path | None = None
        for f, (ok, _) in zip(files, results):
            if ok:
                last_ok = f
        if last_ok is not None:
            mtime = last_ok.stat().st_mtime
            os.utime(config.MARKER_FILE, (mtime, mtime))


def paste_files(
    files: list[Path],
    on_done=None,
    on_progress=None,
    advance_on_partial: bool = False,
) -> None:
    """Paste files sequentially on a background thread.

    on_done(pasted, total, failures) — failures is list[(Path, error_str)].
    on_progress(i, total, path) — called before each file.
    advance_on_partial: pass True for last-N / pick mode so the marker
    advances even when some files failed (avoids re-pasting on next "paste new").
    """
    delay = config.get('paste_delay', 0.6)
    total = len(files)

    def _run():
        results = []
        failures = []
        for i, f in enumerate(files):
            ok, err = _paste_one(f)
            results.append((ok, err))
            if not ok:
                failures.append((f, err))
            if on_progress:
                on_progress(i + 1, total, f)
            if i < total - 1:
                time.sleep(delay)
        _advance_marker_on_success(results, files=files, advance_on_partial=advance_on_partial)
        pasted = sum(1 for ok, _ in results if ok)
        if on_done:
            on_done(pasted, total, failures)

    threading.Thread(target=_run, daemon=True).start()


def paste_files_sync(
    files: list[Path],
    advance_on_partial: bool = False,
) -> tuple[int, int, list[tuple[Path, str]]]:
    """Blocking version — returns (pasted, total, failures).

    advance_on_partial: same semantics as paste_files.
    """
    delay = config.get('paste_delay', 0.6)
    total = len(files)
    results: list[tuple[bool, str | None]] = []
    failures: list[tuple[Path, str]] = []
    for i, f in enumerate(files):
        ok, err = _paste_one(f)
        results.append((ok, err))
        if not ok:
            failures.append((f, err or ''))
        if i < total - 1:
            time.sleep(delay)
    _advance_marker_on_success(results, files=files, advance_on_partial=advance_on_partial)
    pasted = sum(1 for ok, _ in results if ok)
    return pasted, total, failures
