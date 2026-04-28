"""Desktop notifications via libnotify."""

import shutil
import subprocess
from pathlib import Path

from . import config


def notify(title: str, body: str, urgency: str = 'normal') -> None:
    if not config.get('notifications', True):
        return
    if not shutil.which('notify-send'):
        return
    subprocess.run(
        ['notify-send', '-a', 'paste-shots', '-i', 'camera-photo',
         '-u', urgency, title, body],
        capture_output=True,
    )


def notify_paste_result(pasted: int, total: int,
                        failures: list[tuple[Path, str]]) -> None:
    """Single source of truth for the post-paste user notification.

    Used by both the tray (background paste) and the CLI (sync paste) so the
    wording stays consistent. When some files succeeded and some failed, the
    body explains that the marker was kept (so the user knows the next "paste
    new" run will retry the failed files)."""
    if failures and pasted:
        body = (f'Pasted {pasted}/{total}. {len(failures)} failed — '
                f'marker kept.\n{failures[0][1]}')
        notify('paste-shots', body)
    elif failures:
        notify('paste-shots', f'Paste failed: {failures[0][1]}')
    else:
        notify('paste-shots', f'Pasted {pasted}/{total} screenshot(s)')
