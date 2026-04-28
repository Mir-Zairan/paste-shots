"""pytest fixtures.

Each test gets an isolated watch dir, marker file, and config file so we can
exercise the finders and config loader without touching the user's real state.
"""

import sys
from pathlib import Path

import pytest

# Put src/ on the path so `from paste_shots import ...` resolves.
SRC = Path(__file__).resolve().parent.parent / 'src'
sys.path.insert(0, str(SRC))


# Sub-modules that capture a `config` reference at import time. The fixture
# deletes them from sys.modules so each test gets a fresh import that picks
# up the env overrides applied via monkeypatch.
_PKG_MODULES = (
    'paste_shots.config', 'paste_shots.core', 'paste_shots.window',
    'paste_shots.errors', 'paste_shots.finders', 'paste_shots.clipboard',
    'paste_shots.keys', 'paste_shots.pipeline',
    'paste_shots.tray_ipc', 'paste_shots.cli',
)


@pytest.fixture
def paste_env(tmp_path, monkeypatch):
    """Redirect XDG dirs and the config file to a tmp location, then reload
    config so the module-level paths pick up the override."""
    xdg = tmp_path / 'xdg'
    home_cfg = tmp_path / 'home_cfg'
    watch = tmp_path / 'screenshots'
    watch.mkdir()

    monkeypatch.setenv('XDG_DATA_HOME', str(xdg))
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('PASTE_SHOTS_WATCH_DIR', str(watch))
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)

    for mod in _PKG_MODULES:
        sys.modules.pop(mod, None)

    from paste_shots import config as _config  # noqa: E402
    from paste_shots import core as _core      # noqa: E402

    # Point CONFIG_FILE / DATA_DIR / MARKER_FILE at tmp.
    _config.DATA_DIR = xdg / 'paste-shots'
    _config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _config.MARKER_FILE = _config.DATA_DIR / 'last-paste'
    _config.CONFIG_FILE = home_cfg / 'paste-shots' / 'settings.json'
    _config.load_config()

    return {
        'config': _config,
        'core': _core,
        'watch': watch,
        'marker': _config.MARKER_FILE,
        'tmp': tmp_path,
    }
