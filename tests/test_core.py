"""Pure-logic tests for paste-shots core.

We test the screenshot finders, marker-advance rules, and config loading.
The clipboard/keystroke paths are intentionally skipped — they depend on a
live display server and are covered manually.
"""

import time
from pathlib import Path

import pytest

from helpers import touch_image


class TestScreenshotsIn:
    def test_empty_dir(self, paste_env):
        assert paste_env['core'].screenshots_in(paste_env['watch']) == []

    def test_picks_up_png_jpg_jpeg(self, paste_env):
        watch = paste_env['watch']
        touch_image(watch / 'a', ext='.png')
        touch_image(watch / 'b', ext='.jpg')
        touch_image(watch / 'c', ext='.jpeg')
        names = {f.name for f in paste_env['core'].screenshots_in(watch)}
        assert names == {'a.png', 'b.jpg', 'c.jpeg'}

    def test_ignores_non_image_files(self, paste_env):
        watch = paste_env['watch']
        (watch / 'README.txt').write_text('nope')
        (watch / 'notes.md').write_text('nope')
        touch_image(watch / 'real', ext='.png')
        names = {f.name for f in paste_env['core'].screenshots_in(watch)}
        assert names == {'real.png'}


class TestFindSinceMarker:
    def test_no_marker_uses_10min_window(self, paste_env):
        watch = paste_env['watch']
        now = time.time()
        touch_image(watch / 'old', mtime=now - 3600)       # 1h ago — excluded
        touch_image(watch / 'recent', mtime=now - 120)     # 2min ago — included
        touch_image(watch / 'fresh', mtime=now - 5)        # 5s ago — included
        names = [f.name for f in paste_env['core'].find_since_marker()]
        assert names == ['recent.png', 'fresh.png']

    def test_marker_present_strictly_newer(self, paste_env):
        watch = paste_env['watch']
        marker_time = time.time() - 300
        paste_env['marker'].touch()
        import os
        os.utime(paste_env['marker'], (marker_time, marker_time))

        touch_image(watch / 'before', mtime=marker_time - 60)   # excluded
        touch_image(watch / 'at_marker', mtime=marker_time)     # excluded (not strictly newer)
        touch_image(watch / 'after', mtime=marker_time + 60)    # included
        names = [f.name for f in paste_env['core'].find_since_marker()]
        assert names == ['after.png']

    def test_returns_chronological_order(self, paste_env):
        watch = paste_env['watch']
        now = time.time()
        touch_image(watch / 'c', mtime=now - 10)
        touch_image(watch / 'a', mtime=now - 30)
        touch_image(watch / 'b', mtime=now - 20)
        names = [f.name for f in paste_env['core'].find_since_marker()]
        assert names == ['a.png', 'b.png', 'c.png']

    def test_missing_watch_dir(self, paste_env):
        import shutil
        shutil.rmtree(paste_env['watch'])
        assert paste_env['core'].find_since_marker() == []


class TestFindLastN:
    def test_returns_most_recent_n(self, paste_env):
        watch = paste_env['watch']
        now = time.time()
        for i, name in enumerate(['a', 'b', 'c', 'd', 'e']):
            touch_image(watch / name, mtime=now - (5 - i) * 10)
        names = [f.name for f in paste_env['core'].find_last_n(3)]
        # Chronological order, last 3
        assert names == ['c.png', 'd.png', 'e.png']

    def test_n_larger_than_available(self, paste_env):
        watch = paste_env['watch']
        touch_image(watch / 'only')
        files = paste_env['core'].find_last_n(10)
        assert len(files) == 1

    def test_zero_returns_empty(self, paste_env):
        touch_image(paste_env['watch'] / 'a')
        assert paste_env['core'].find_last_n(0) == []


class TestMarkerAdvance:
    def test_not_advanced_when_all_fail(self, paste_env):
        marker = paste_env['marker']
        assert not marker.exists()
        paste_env['core']._advance_marker_on_success([(False, 'e1'), (False, 'e2')])
        assert not marker.exists()

    def test_not_advanced_on_partial_failure(self, paste_env):
        marker = paste_env['marker']
        paste_env['core']._advance_marker_on_success([(True, None), (False, 'e')])
        assert not marker.exists()

    def test_advanced_when_all_succeed(self, paste_env):
        marker = paste_env['marker']
        paste_env['core']._advance_marker_on_success([(True, None), (True, None)])
        assert marker.exists()

    def test_empty_results_does_not_create_marker(self, paste_env):
        marker = paste_env['marker']
        paste_env['core']._advance_marker_on_success([])
        assert not marker.exists()

    def test_advance_on_partial_advances_when_some_succeed(self, paste_env):
        watch = paste_env['watch']
        now = time.time()
        f1 = touch_image(watch / 'first',  mtime=now - 60)
        f2 = touch_image(watch / 'second', mtime=now - 30)
        marker = paste_env['marker']
        paste_env['core']._advance_marker_on_success(
            [(True, None), (False, 'err')],
            files=[f1, f2],
            advance_on_partial=True,
        )
        assert marker.exists()
        # Marker mtime == first file (last success) so second run won't re-include it.
        import os
        assert abs(os.stat(marker).st_mtime - f1.stat().st_mtime) < 1

    def test_advance_on_partial_uses_last_success_mtime(self, paste_env):
        watch = paste_env['watch']
        now = time.time()
        f1 = touch_image(watch / 'a', mtime=now - 90)
        f2 = touch_image(watch / 'b', mtime=now - 60)
        f3 = touch_image(watch / 'c', mtime=now - 30)
        marker = paste_env['marker']
        # f1 and f2 succeed; f3 fails
        paste_env['core']._advance_marker_on_success(
            [(True, None), (True, None), (False, 'err')],
            files=[f1, f2, f3],
            advance_on_partial=True,
        )
        import os
        assert abs(os.stat(marker).st_mtime - f2.stat().st_mtime) < 1

    def test_advance_on_partial_no_advance_when_all_fail(self, paste_env):
        watch = paste_env['watch']
        f1 = touch_image(watch / 'x')
        marker = paste_env['marker']
        paste_env['core']._advance_marker_on_success(
            [(False, 'err')],
            files=[f1],
            advance_on_partial=True,
        )
        assert not marker.exists()


class TestConfigLoadSave:
    def test_defaults_when_no_file(self, paste_env):
        cfg = paste_env['config'].load_config()
        # PASTE_SHOTS_WATCH_DIR env override applies via load_config.
        assert cfg['watch_dir'] == str(paste_env['watch'])
        assert cfg['paste_delay'] == 0.6
        assert cfg['notifications'] is True

    def test_save_then_load_roundtrip(self, paste_env):
        cfg = dict(paste_env['config'].DEFAULT_CONFIG)
        cfg['paste_delay'] = 1.4
        cfg['floating_widget'] = True
        paste_env['config'].save_config(cfg)

        reloaded = paste_env['config'].load_config()
        # Env override still wins over the saved watch_dir.
        assert reloaded['paste_delay'] == 1.4
        assert reloaded['floating_widget'] is True

    def test_malformed_file_falls_back_to_defaults(self, paste_env):
        cfg_path = paste_env['config'].CONFIG_FILE
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text('{ not valid json')
        cfg = paste_env['config'].load_config()
        assert cfg['paste_delay'] == 0.6  # default, not crashed


class TestPasteError:
    def test_is_exception(self):
        from paste_shots import core
        assert issubclass(core.PasteError, Exception)


class TestPasteTargetClassification:
    """is_paste_target gates Ctrl+V; regressions here cause silent paste
    failures into apps that ignore image clipboard, or false rejections
    of legitimate terminals/editors."""

    def test_terminal_class_accepted(self, paste_env):
        from paste_shots import window
        assert window.is_paste_target('alacritty')
        assert window.is_paste_target('Alacritty')  # case-insensitive
        assert window.is_paste_target('org.gnome.Ptyxis')

    def test_editor_class_rejected(self, paste_env):
        from paste_shots import window
        assert not window.is_paste_target('code')
        assert not window.is_paste_target('jetbrains-pycharm')

    def test_non_target_rejected(self, paste_env):
        from paste_shots import window
        assert not window.is_paste_target('firefox')
        assert not window.is_paste_target('gedit')
        assert not window.is_paste_target('gnome-shell')
        assert not window.is_paste_target('')

    def test_custom_target_accepted_when_configured(self, paste_env):
        from paste_shots import config, window
        cfg = dict(config.get_config())
        cfg['custom_paste_targets'] = ['phpstorm', 'helix']
        config.save_config(cfg)
        try:
            assert window.is_paste_target('jetbrains-PhpStorm-2024.3')
            assert window.is_paste_target('helix')
        finally:
            cfg['custom_paste_targets'] = []
            config.save_config(cfg)

    def test_empty_pattern_in_custom_does_not_match_everything(self, paste_env):
        """Without filtering, '' in <anything> is True and disables the
        silent-fail guard for every window."""
        from paste_shots import config, window
        cfg = dict(config.get_config())
        cfg['custom_paste_targets'] = ['', '  ', '\t']
        config.save_config(cfg)
        try:
            assert not window.is_paste_target('firefox')
            assert not window.is_paste_target('gedit')
        finally:
            cfg['custom_paste_targets'] = []
            config.save_config(cfg)

    def test_non_string_pattern_in_custom_skipped(self, paste_env):
        """User editing settings.json by hand could put a non-string in;
        we should ignore it rather than crash."""
        from paste_shots import config, window
        cfg = dict(config.get_config())
        cfg['custom_paste_targets'] = [123, None, 'phpstorm']
        config.save_config(cfg)
        try:
            assert window.is_paste_target('jetbrains-phpstorm')
            assert not window.is_paste_target('firefox')
        finally:
            cfg['custom_paste_targets'] = []
            config.save_config(cfg)


class TestConfigDefaults:
    def test_custom_paste_targets_default_empty(self, paste_env):
        cfg = paste_env['config'].load_config()
        assert cfg.get('custom_paste_targets') == []

    def test_legacy_config_without_new_key_loads_default(self, paste_env):
        """Pre-existing settings.json files won't have custom_paste_targets;
        load_config must merge defaults so we don't KeyError."""
        cfg_path = paste_env['config'].CONFIG_FILE
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        cfg_path.write_text(json.dumps({'paste_delay': 1.0}))
        cfg = paste_env['config'].load_config()
        assert cfg['custom_paste_targets'] == []
        assert cfg['paste_delay'] == 1.0
