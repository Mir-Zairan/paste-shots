"""Drift guard: every key in DEFAULT_CONFIG must be settable via `--set`.

Used to be a hand-maintained allowlist that drifted out of sync (paste_mode
was missing for a while). Now derived from DEFAULT_CONFIG; this test pins
that contract."""


def test_all_default_keys_are_settable(paste_env):
    from paste_shots import cli, config
    settable = cli._settable_keys()
    for key in config.DEFAULT_CONFIG:
        assert key in settable, f'{key!r} from DEFAULT_CONFIG not settable via --set'


def test_unknown_key_rejected(paste_env, capsys):
    from paste_shots import cli
    rc = cli._cmd_set('not_a_real_key=true')
    captured = capsys.readouterr()
    assert rc == 2
    assert 'unknown key' in captured.err
