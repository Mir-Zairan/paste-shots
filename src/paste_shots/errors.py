"""Shared exceptions for paste-shots.

Lives in its own module so clipboard.py / keys.py / pipeline.py can all
raise PasteError without forming an import cycle (clipboard ↔ pipeline)."""


class PasteError(Exception):
    """Raised when a paste step fails; message is user-readable."""
