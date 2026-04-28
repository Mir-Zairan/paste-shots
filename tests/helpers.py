"""Shared test helpers — kept out of conftest.py because pytest discourages
`from conftest import ...` patterns (works in many setups, but not all)."""

import os
from pathlib import Path


def touch_image(path: Path, mtime: float | None = None, ext: str = '.png') -> Path:
    """Create a tiny fake image file; optionally stamp a specific mtime."""
    full = path.with_suffix(ext) if path.suffix != ext else path
    full.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16)  # PNG header stub
    if mtime is not None:
        os.utime(full, (mtime, mtime))
    return full
