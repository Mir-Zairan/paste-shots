"""Backwards-compatible re-export shim.

The pieces that used to live here have been split by concern:

  * finders.py    — screenshot listing + marker rules (pure)
  * clipboard.py  — wl-copy / xclip
  * keys.py       — ydotool / xdotool
  * pipeline.py   — orchestration: focus → copy → keystroke
  * errors.py     — PasteError

Prefer importing from the focused modules in new code.
"""

# pylint: disable=unused-import
from .clipboard import (  # noqa: F401
    clipboard_has_image,
    copy_to_clipboard,
)
from .errors import PasteError  # noqa: F401
from .finders import (  # noqa: F401
    find_last_n,
    find_since_marker,
    screenshots_in,
)
from .keys import (  # noqa: F401
    send_ctrl_v,
    send_keys,
)
from .pipeline import (  # noqa: F401
    _advance_marker_on_success,
    _paste_one,
    paste_files,
    paste_files_sync,
)
